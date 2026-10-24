"""Claude call plus the spec -> URDF -> validate -> feedback loop.

- The model returns a RobotSpec only through a forced tool call (`submit_robot_spec`).
  It never writes free-form XML.
- Code assembles the URDF (builder) and validates it (validator). Any failures are
  sent back to Claude as an error tool_result, for at most MAX_FIX_ROUNDS (2) fix rounds.
- The API key comes only from the server env var ANTHROPIC_API_KEY. The model is
  ANTHROPIC_MODEL (default claude-sonnet-5-5).
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Optional

from pydantic import ValidationError

from builder import build_urdf, check_spec, urdf_to_spec
from schema import AttemptLog, MeshProps, RobotSpec, ValidationResult, robot_spec_json_schema
from validator import validate_urdf

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_FIX_ROUNDS = 2
MAX_TOKENS = 16000
TOOL_NAME = "submit_robot_spec"


def model_name() -> str:
    return os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL


def api_key_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


class GenerationError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


SYSTEM_PROMPT = """You design ROS 2 robot descriptions. You never write URDF XML. You return a structure \
spec by calling the `submit_robot_spec` tool exactly once. Server code converts the spec to URDF, \
computes inertia from geometry, and validates the result.

Rules (urdf-authoring):
1. Design the tree first. Exactly one root link, named `base_link`. URDF supports only trees: \
every non-root link has exactly one parent joint, and there are no closed loops. If the user \
describes a closed-loop mechanism, open the loop and record that in `assumptions`.
2. A joint `origin` is the pose of the child link frame expressed in the PARENT link frame. \
Units are meters and radians. ROS convention: x forward, y left, z up.
3. A link's `visual_origin` places the geometry center in that link's own frame. A cylinder's \
length runs along its local z axis, so a wheel spinning about y needs rpy [1.5707963, 0, 0].
4. revolute and prismatic joints need limit.lower < limit.upper plus limit.effort > 0 and \
limit.velocity > 0. continuous joints need only effort and velocity. fixed joints need no axis or limit.
5. `axis` is expressed in the joint frame. Use unit vectors such as [0,0,1].
6. Names must be unique across the model. Use `<parent>_to_<child>_joint` or meaningful names \
(`shoulder_pan_joint`, `left_wheel_joint`), and give links a `_link` suffix (except base_link).
7. Every link needs a positive mass in kg. Do not provide an inertia tensor; code computes it \
(box, cylinder, and sphere formulas, or mesh analysis). A frame-only link uses geometry null and mass 0.001.
8. Uploaded meshes: use geometry {"type":"mesh","mesh_file":"<stored_name>"}. Use the stored_name \
values exactly as given. Omit `scale` unless the user asks for one; the server applies the detected \
unit scale. Use the mesh bounding box (bbox_m, bbox_center_m in meters, in the mesh's own frame) to \
choose joint origins. Collision geometry for meshes is auto-generated as a bounding box.
9. Record every number you had to guess (dimensions, masses, limits, axis choices) in `assumptions`, \
one short sentence each.
10. When a current spec is supplied, change only what the request asks for. Keep every other \
link, joint, name, and value exactly as it is.
11. If the tool result reports errors, fix all of them and call the tool again with the full corrected spec."""


def _tool_def() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Submit the complete robot structure spec. Server converts it to URDF and validates it.",
        "input_schema": robot_spec_json_schema(),
    }


def _mesh_summary(meshes: list[MeshProps]) -> str:
    rows = []
    for m in meshes:
        rows.append({k: getattr(m, k) for k in ("stored_name", "original_name", "unit_guess", "confidence",
                                                 "scale_to_m", "bbox_m", "bbox_center_m", "mass_kg", "warnings")})
    return json.dumps(rows, indent=1)


def _user_message(prompt: str, meshes: list[MeshProps], base_spec: Optional[RobotSpec],
                  import_notes: list[str]) -> str:
    parts = [f"<request>\n{prompt}\n</request>"]
    if meshes:
        parts.append("<uploaded_meshes note=\"mass_kg is a density-1000 estimate; set a realistic mass\">\n"
                     f"{_mesh_summary(meshes)}\n</uploaded_meshes>")
    if base_spec is not None:
        parts.append("<current_spec note=\"imported from the user's existing URDF; modify it\">\n"
                     f"{base_spec.model_dump_json(indent=1)}\n</current_spec>")
        if import_notes:
            parts.append("<import_notes>\n" + "\n".join(import_notes) + "\n</import_notes>")
    return "\n\n".join(parts)


def _make_client():
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover
        raise GenerationError("sdk_missing", "anthropic 패키지가 설치되지 않음: pip install anthropic", 500) from e
    return anthropic.Anthropic(timeout=180.0, max_retries=2)


def _call(client, messages: list[dict]) -> Any:
    try:
        import anthropic
        errs = anthropic
    except ImportError:  # test doubles
        errs = None
    try:
        return client.messages.create(
            model=model_name(),
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[_tool_def()],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=messages,
        )
    except Exception as e:
        if errs is not None:
            if isinstance(e, errs.AuthenticationError):
                raise GenerationError("invalid_api_key", "ANTHROPIC_API_KEY가 유효하지 않습니다.", 502) from e
            if isinstance(e, errs.NotFoundError):
                raise GenerationError("model_not_found",
                                      f"모델 '{model_name()}'을 찾을 수 없습니다. ANTHROPIC_MODEL을 확인하세요.", 502) from e
            if isinstance(e, errs.RateLimitError):
                raise GenerationError("rate_limited", "Claude API 요청 한도 초과. 잠시 후 다시 시도하세요.", 429) from e
            if isinstance(e, errs.APIConnectionError):
                raise GenerationError("api_unreachable", "Claude API에 연결할 수 없습니다(네트워크 확인).", 502) from e
            if isinstance(e, errs.APIStatusError):
                raise GenerationError("api_error", f"Claude API 오류 {e.status_code}: {e.message}", 502) from e
        raise


def _tool_use(resp) -> Optional[Any]:
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
            return block
    return None


def _content_as_params(resp) -> list[dict]:
    """Echo the assistant turn back as minimal input blocks (response-only fields are dropped)."""
    out = []
    for b in getattr(resp, "content", []) or []:
        t = getattr(b, "type", None)
        if t == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        elif t == "text" and getattr(b, "text", ""):
            out.append({"type": "text", "text": b.text})
    return out


def generate(prompt: str, meshes: list[MeshProps], base_urdf: Optional[str],
             mesh_lookup: Callable[[str], Optional[MeshProps]], mesh_root: Optional[str],
             client=None) -> dict:
    if client is None:
        if not api_key_configured():
            raise GenerationError(
                "missing_api_key",
                "서버에 ANTHROPIC_API_KEY 환경변수가 설정되지 않아 생성 기능을 쓸 수 없습니다. "
                "검증·뷰어·샘플 로딩은 키 없이 동작합니다.", 503)
        client = _make_client()

    base_spec, import_notes = None, []
    if base_urdf and base_urdf.strip():
        try:
            base_spec, import_notes = urdf_to_spec(base_urdf, mesh_lookup)
        except (ValueError, ValidationError) as e:
            raise GenerationError("base_urdf_invalid", f"기존 URDF를 명세로 가져올 수 없음: {e}", 422) from e

    messages: list[dict] = [{"role": "user", "content": _user_message(prompt, meshes, base_spec, import_notes)}]
    attempts: list[AttemptLog] = []
    best: Optional[tuple[RobotSpec, str, list[str], ValidationResult]] = None

    for attempt in range(1, MAX_FIX_ROUNDS + 2):
        resp = _call(client, messages)
        block = _tool_use(resp)
        if block is None:
            attempts.append(AttemptLog(attempt=attempt, status="api_error",
                                       detail=[f"no tool call (stop_reason={getattr(resp, 'stop_reason', None)})"]))
            if getattr(resp, "stop_reason", None) == "max_tokens":
                raise GenerationError("output_truncated", "모델 출력이 max_tokens에서 잘렸습니다. 요청을 줄여 주세요.", 502)
            messages.append({"role": "assistant", "content": _content_as_params(resp) or "(empty)"})
            messages.append({"role": "user", "content": f"Call the {TOOL_NAME} tool with the full spec."})
            continue

        feedback: list[str] = []
        spec = None
        try:
            spec = RobotSpec.model_validate(block.input)
        except ValidationError as e:
            for err in e.errors()[:30]:
                loc = ".".join(str(p) for p in err["loc"])
                feedback.append(f"schema: {loc}: {err['msg']}")
            attempts.append(AttemptLog(attempt=attempt, status="spec_invalid", detail=feedback))
        if spec is not None:
            errs, _warns = check_spec(spec, mesh_lookup)
            if errs:
                feedback = errs
                attempts.append(AttemptLog(attempt=attempt, status="spec_invalid", detail=errs))
            else:
                urdf, notes = build_urdf(spec, mesh_lookup)
                result = validate_urdf(urdf, mesh_root)
                best = (spec, urdf, notes, result)
                if result.ok:
                    attempts.append(AttemptLog(attempt=attempt, status="ok",
                                               detail=[i.message for i in result.issues]))
                    break
                feedback = [f"{i.severity} · {i.where} · {i.message}" for i in result.issues if i.severity == "error"]
                attempts.append(AttemptLog(attempt=attempt, status="urdf_invalid", detail=feedback))

        if attempt > MAX_FIX_ROUNDS:
            break
        messages.append({"role": "assistant", "content": _content_as_params(resp)})
        messages.append({"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": block.id, "is_error": True,
            "content": "The spec failed validation. Fix every item and call the tool again with the "
                       "complete corrected spec:\n- " + "\n- ".join(feedback),
        }]})

    if best is None:
        raise GenerationError("generation_failed",
                              f"{len(attempts)}회 시도 후에도 유효한 명세를 얻지 못했습니다.", 422)
    spec, urdf, notes, result = best
    assumptions = list(spec.assumptions) + [f"[import] {n}" for n in import_notes] + [f"[builder] {n}" for n in notes]
    return {"urdf": urdf, "spec": spec, "assumptions": assumptions, "validation": result,
            "attempts": attempts, "model": model_name()}
