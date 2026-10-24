"""File storage for uploaded meshes and generated/validated artifacts.

Layout (DATA_DIR defaults to app/data, env URDF_APP_DATA overrides):
  data/meshes/<stored_name>              uploaded mesh
  data/meshes/<stored_name>.props.json   mesh_props result
  data/artifacts/<id>.json               {"urdf", "robot_name", "created"}
The validator's mesh_root is DATA_DIR, so package://<pkg>/meshes/<f> resolves to data/meshes/<f>.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import secrets
import time
from typing import Optional

from schema import ALLOWED_MESH_EXT, MESH_FILE_RE, MeshProps

APP_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = pathlib.Path(os.environ.get("URDF_APP_DATA", APP_DIR / "data")).resolve()
MESH_DIR = DATA_DIR / "meshes"
ARTIFACT_DIR = DATA_DIR / "artifacts"
ARTIFACT_ID_RE = re.compile(r"[a-f0-9]{32}")
ARTIFACT_TTL_S = float(os.environ.get("URDF_APP_ARTIFACT_TTL_S", 24 * 3600))
MAX_ARTIFACTS = int(os.environ.get("URDF_APP_MAX_ARTIFACTS", 500))

for d in (MESH_DIR, ARTIFACT_DIR):
    d.mkdir(parents=True, exist_ok=True)


def safe_mesh_name(original: str) -> str:
    """Normalize an uploaded filename: basename only, [A-Za-z0-9_.-], lowercase ext, random prefix."""
    base = re.split(r"[\\/]", original or "")[-1]
    stem, dot, ext = base.rpartition(".")
    ext = ext.lower()
    if not dot or f".{ext}" not in ALLOWED_MESH_EXT:
        raise ValueError(f"허용되지 않은 확장자: {base!r} (stl/dae/obj만 허용)")
    stem = re.sub(r"[^A-Za-z0-9_\-]", "_", stem)[:60].strip("._-") or "mesh"
    name = f"{secrets.token_hex(4)}_{stem}.{ext}"
    assert re.fullmatch(MESH_FILE_RE, name)
    return name


def mesh_path(stored_name: str) -> Optional[pathlib.Path]:
    """Resolve a stored mesh name to a path inside MESH_DIR, or None if invalid/missing."""
    if not re.fullmatch(MESH_FILE_RE, stored_name or ""):
        return None
    p = (MESH_DIR / stored_name).resolve()
    if p.parent != MESH_DIR or not p.is_file():
        return None
    return p


def save_mesh_props(stored_name: str, props: MeshProps) -> None:
    (MESH_DIR / f"{stored_name}.props.json").write_text(props.model_dump_json(indent=2), encoding="utf-8")


def get_mesh_props(stored_name: str) -> Optional[MeshProps]:
    if mesh_path(stored_name) is None:
        return None
    pf = MESH_DIR / f"{stored_name}.props.json"
    if not pf.is_file():
        return None
    return MeshProps.model_validate_json(pf.read_text(encoding="utf-8"))


def list_meshes() -> list[MeshProps]:
    out = []
    for pf in sorted(MESH_DIR.glob("*.props.json")):
        props = get_mesh_props(pf.name[: -len(".props.json")])
        if props:
            out.append(props)
    return out


def save_artifact(urdf: str, robot_name: Optional[str]) -> str:
    """Save an artifact under a content-hash id (identical content = one file), then prune (QA W1)."""
    aid = hashlib.sha256(f"{robot_name or ''}\0{urdf}".encode("utf-8")).hexdigest()[:32]
    p = ARTIFACT_DIR / f"{aid}.json"
    if p.is_file():
        os.utime(p)  # refresh TTL
    else:
        p.write_text(json.dumps({"urdf": urdf, "robot_name": robot_name, "created": time.time()}),
                     encoding="utf-8")
    prune_artifacts(keep=aid)
    return aid


def prune_artifacts(keep: Optional[str] = None) -> int:
    """Delete artifacts older than the TTL, then the oldest beyond the count cap. Returns the number deleted."""
    now = time.time()
    files = []
    for f in ARTIFACT_DIR.glob("*.json"):
        try:
            files.append((f.stat().st_mtime, f))
        except FileNotFoundError:
            continue
    files.sort()
    removed = 0
    survivors = []
    for mtime, f in files:
        if f.stem != keep and now - mtime > ARTIFACT_TTL_S:
            f.unlink(missing_ok=True)
            removed += 1
        else:
            survivors.append(f)
    excess = len(survivors) - MAX_ARTIFACTS
    for f in survivors:
        if excess <= 0:
            break
        if f.stem == keep:
            continue
        f.unlink(missing_ok=True)
        removed += 1
        excess -= 1
    return removed


def load_artifact(aid: str) -> Optional[dict]:
    if not ARTIFACT_ID_RE.fullmatch(aid or ""):
        return None
    p = ARTIFACT_DIR / f"{aid}.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
