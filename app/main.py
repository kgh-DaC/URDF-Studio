"""URDF web app — FastAPI backend.

Run (from app/): uvicorn main:app --port 8000
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import re
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

import llm
import storage
from limits import BodyLimitMiddleware
from mesh_props import analyze
from ros_package import build_package_zip, robot_name_of
from schema import (ALLOWED_MESH_EXT, MAX_UPLOAD_BYTES, MESH_FILE_RE, GenerateRequest, GenerateResponse,
                    MeshProps, UploadResponse, ValidateRequest, ValidateResponse, robot_spec_json_schema)
from validator import validate_urdf

APP_DIR = pathlib.Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
SAMPLES_DIR = APP_DIR / "samples"
MAX_FILES_PER_UPLOAD = 10
MAX_JSON_BODY = 5 * 1024 * 1024

# Allowed Host headers (QA W10: blocks DNS rebinding). Comma-separated, override with env var.
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("URDF_APP_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
                 if h.strip()]

app = FastAPI(title="URDF Web App", version="0.1.0")

_INVALID_HOST_BODY = json.dumps({"error": "invalid_host", "message": "허용되지 않은 Host 헤더입니다."},
                                ensure_ascii=False).encode("utf-8")


class JSONTrustedHostMiddleware(TrustedHostMiddleware):
    """TrustedHostMiddleware whose rejection is JSON 400 {error, message} (QA N3).

    The host matching stays Starlette's. A marker app inside records that the request
    passed the check; if a response starts without the marker, it is the middleware's own
    rejection and gets replaced by the JSON body.
    """

    def __init__(self, app, **kw) -> None:
        async def passed(scope, receive, send):
            scope["urdf_app.host_ok"] = True
            await app(scope, receive, send)
        super().__init__(passed, **kw)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await super().__call__(scope, receive, send)
            return

        replaced = False

        async def guarded_send(message):
            nonlocal replaced
            if replaced:
                return  # body of the replaced plain-text rejection
            if (not scope.get("urdf_app.host_ok") and message["type"] == "http.response.start"
                    and message["status"] == 400):
                replaced = True
                await send({"type": "http.response.start", "status": 400, "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_INVALID_HOST_BODY)).encode())]})
                await send({"type": "http.response.body", "body": _INVALID_HOST_BODY})
                return
            await send(message)

        await super().__call__(scope, receive, guarded_send)


def _body_limit(path: str) -> int:
    return MAX_UPLOAD_BYTES * MAX_FILES_PER_UPLOAD if path == "/api/upload" else MAX_JSON_BODY


# Starlette: the last middleware added is the outermost -> Host check first, then the body limit.
app.add_middleware(BodyLimitMiddleware, limit_for=_body_limit)
app.add_middleware(JSONTrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


def err(code: str, message: str, status: int, **extra) -> JSONResponse:
    return JSONResponse({"error": code, "message": message, **extra}, status_code=status)


_HTTP_CODES = {404: ("not_found", "경로를 찾을 수 없습니다."), 405: ("method_not_allowed", "허용되지 않은 메서드입니다.")}


@app.exception_handler(StarletteHTTPException)
async def on_http_error(_request: Request, exc: StarletteHTTPException):
    """Framework 404/405 etc. also use the {error, message} format (QA W4)."""
    code, msg = _HTTP_CODES.get(exc.status_code, ("http_error", str(exc.detail)))
    return err(code, msg, exc.status_code)


@app.exception_handler(RequestValidationError)
async def on_validation_error(_request: Request, exc: RequestValidationError):
    detail = [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg")} for e in exc.errors()][:20]
    return err("invalid_request", "요청 형식이 올바르지 않습니다.", 422, detail=detail)


# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "api_key_configured": llm.api_key_configured(), "model": llm.model_name()}


@app.get("/api/schema")
def spec_schema():
    return robot_spec_json_schema()


@app.get("/api/samples")
def samples():
    return {"samples": sorted(p.stem for p in SAMPLES_DIR.glob("*.urdf"))}


@app.get("/api/samples/{name}")
def sample(name: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
        return err("not_found", "샘플 없음", 404)
    p = SAMPLES_DIR / f"{name}.urdf"
    if not p.is_file():
        return err("not_found", "샘플 없음", 404)
    return {"name": name, "urdf": p.read_text(encoding="utf-8")}


# ---------------------------------------------------------------------------
@app.post("/api/validate", response_model=ValidateResponse)
def validate(req: ValidateRequest):
    result = validate_urdf(req.urdf, str(storage.DATA_DIR) if req.check_meshes else None)
    name = robot_name_of(req.urdf)
    aid = storage.save_artifact(req.urdf, name) if req.urdf.strip() else None
    return ValidateResponse(validation=result, artifact_id=aid, robot_name=name)


# ---------------------------------------------------------------------------
@app.post("/api/upload", response_model=UploadResponse)
async def upload(files: list[UploadFile] = File(...),
                 unit: Optional[str] = Form(None),
                 mass: Optional[float] = Form(None),
                 density: Optional[float] = Form(None)):
    if len(files) > MAX_FILES_PER_UPLOAD:
        return err("too_many_files", f"한 번에 최대 {MAX_FILES_PER_UPLOAD}개까지 업로드할 수 있습니다.", 400)
    if unit not in (None, "", "mm", "m"):
        return err("invalid_unit", "unit은 mm 또는 m", 400)
    for v in (mass, density):  # QA W5: nan/inf also rejected
        if v is not None and (not math.isfinite(v) or v <= 0):
            return err("invalid_mass", "mass/density는 0보다 큰 유한한 숫자여야 합니다.", 400)
    out: list[MeshProps] = []
    for f in files:
        try:
            stored = storage.safe_mesh_name(f.filename or "")
        except ValueError as e:
            out.append(MeshProps(original_name=f.filename, status="failed", error=str(e)))
            continue
        dest = storage.MESH_DIR / stored
        size, too_big = 0, False
        with open(dest, "wb") as fh:
            while chunk := await f.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    too_big = True
                    break
                fh.write(chunk)
        if too_big or size == 0:
            dest.unlink(missing_ok=True)
            msg = f"파일이 너무 큽니다(최대 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)" if too_big else "빈 파일"
            out.append(MeshProps(original_name=f.filename, status="failed", error=msg))
            continue
        try:
            props = MeshProps(stored_name=stored, original_name=f.filename,
                              **analyze(str(dest), unit or None, mass, density))
        except Exception as e:  # untrusted file; one failure must not block the rest
            dest.unlink(missing_ok=True)
            out.append(MeshProps(original_name=f.filename, status="failed", error=f"메시 해석 실패: {e}"))
            continue
        storage.save_mesh_props(stored, props)
        out.append(props)
    return UploadResponse(meshes=out)


@app.get("/api/meshes", response_model=UploadResponse)
def meshes():
    return UploadResponse(meshes=storage.list_meshes())


@app.get("/api/pkg/{pkg}/meshes/{filename}")
def mesh_file(pkg: str, filename: str):
    """Serves package://<pkg>/meshes/<filename> for the viewer (the pkg name is ignored)."""
    p = storage.mesh_path(filename)
    if p is None:
        return err("not_found", f"메시 없음: {filename}", 404)
    return FileResponse(p, media_type="application/octet-stream")


# ---------------------------------------------------------------------------
@app.post("/api/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    mesh_list = []
    for n in req.meshes:
        props = storage.get_mesh_props(n)
        if props is None:
            return err("mesh_not_found", f"업로드되지 않은 메시: {n}", 400)
        mesh_list.append(props)
    try:
        out = llm.generate(req.prompt, mesh_list, req.baseUrdf, storage.get_mesh_props, str(storage.DATA_DIR))
    except llm.GenerationError as e:
        return err(e.code, e.message, e.status)
    aid = storage.save_artifact(out["urdf"], out["spec"].robot_name)
    return GenerateResponse(artifact_id=aid, **out)


# ---------------------------------------------------------------------------
@app.get("/api/download/{artifact_id}")
def download(artifact_id: str, format: str = "urdf"):
    art = storage.load_artifact(artifact_id)
    if art is None:
        return err("not_found", "다운로드 대상이 없습니다(먼저 검증 또는 생성하세요).", 404)
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", art.get("robot_name") or "robot")
    if format == "urdf":
        return Response(art["urdf"], media_type="application/xml",
                        headers={"Content-Disposition": f'attachment; filename="{safe}.urdf"'})
    if format == "zip":
        data, pkg = build_package_zip(art["urdf"])
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{pkg}.zip"'})
    return err("invalid_format", "format은 urdf 또는 zip", 400)


# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
