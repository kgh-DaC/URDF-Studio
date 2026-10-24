"""Shared schema for the URDF web app (single source of truth).

The LLM never writes URDF XML directly. It fills in `RobotSpec` (structure-spec
JSON); `builder.py` turns the spec into URDF and computes inertia from geometry.
API request/response field names live here too, and `GET /api/schema` exposes
them to the frontend.
"""
from __future__ import annotations

import re
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

NAME_RE = r"^[A-Za-z_][A-Za-z0-9_\-]*$"
MESH_FILE_RE = r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*\.(stl|dae|obj)$"

# Limits for untrusted input (shared with main.py).
MAX_URDF_CHARS = 2_000_000
MAX_PROMPT_CHARS = 8_000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_MESH_EXT = (".stl", ".dae", ".obj")
MAX_LINKS = 200


class _Strict(BaseModel):
    # QA W9: nan/inf would end up in the URDF as is, so reject them at the spec stage
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


# ---------------------------------------------------------------------------
# Structure spec (what Claude returns)
# ---------------------------------------------------------------------------
class Origin(_Strict):
    xyz: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3,
                             description="Position in meters, in the PARENT frame.")
    rpy: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3,
                             description="Roll-pitch-yaw in radians.")


class BoxGeometry(_Strict):
    type: Literal["box"]
    size: list[float] = Field(min_length=3, max_length=3, description="Box edge lengths x y z in meters (>0).")

    @field_validator("size")
    @classmethod
    def _pos(cls, v: list[float]) -> list[float]:
        if min(v) <= 0:
            raise ValueError("box size components must be > 0")
        return v


class CylinderGeometry(_Strict):
    type: Literal["cylinder"]
    radius: float = Field(gt=0, description="Meters.")
    length: float = Field(gt=0, description="Meters, along the local z axis.")


class SphereGeometry(_Strict):
    type: Literal["sphere"]
    radius: float = Field(gt=0, description="Meters.")


class MeshGeometry(_Strict):
    type: Literal["mesh"]
    mesh_file: str = Field(pattern=MESH_FILE_RE,
                           description="stored_name of an uploaded mesh (from /api/upload).")
    scale: Optional[list[float]] = Field(default=None, min_length=3, max_length=3,
                                         description="Mesh scale. Omit to use the upload's scale_to_m.")

    @field_validator("scale")
    @classmethod
    def _pos(cls, v):
        if v is not None and min(v) <= 0:
            raise ValueError("mesh scale components must be > 0")
        return v


Geometry = Union[BoxGeometry, CylinderGeometry, SphereGeometry, MeshGeometry]


class LinkSpec(_Strict):
    name: str = Field(pattern=NAME_RE)
    geometry: Optional[Geometry] = Field(
        default=None, discriminator="type",
        description="Visual geometry. null means a virtual (frame-only) link.")
    visual_origin: Origin = Field(default_factory=Origin,
                                  description="Pose of the geometry center in the LINK frame.")
    collision: Optional[Geometry] = Field(
        default=None, discriminator="type",
        description="Optional collision geometry. Default: same primitive; for meshes a bounding box.")
    collision_origin: Optional[Origin] = None
    mass: float = Field(gt=0, description="kg. Must be > 0. Inertia is computed from geometry by code.")
    color: Optional[list[float]] = Field(default=None, min_length=4, max_length=4, description="RGBA 0..1")


class Limit(_Strict):
    lower: Optional[float] = Field(default=None, description="rad or m. Required for revolute/prismatic.")
    upper: Optional[float] = Field(default=None, description="rad or m. Required for revolute/prismatic.")
    effort: float = Field(gt=0, description="N*m or N.")
    velocity: float = Field(gt=0, description="rad/s or m/s.")


class JointSpec(_Strict):
    name: str = Field(pattern=NAME_RE)
    type: Literal["fixed", "revolute", "continuous", "prismatic"]
    parent: str = Field(pattern=NAME_RE)
    child: str = Field(pattern=NAME_RE)
    origin: Origin = Field(default_factory=Origin,
                           description="Pose of the child frame in the PARENT link frame.")
    axis: Optional[list[float]] = Field(default=None, min_length=3, max_length=3,
                                        description="Axis in the joint frame; normalized by code.")
    limit: Optional[Limit] = None


class RobotSpec(_Strict):
    robot_name: str = Field(pattern=NAME_RE)
    links: list[LinkSpec] = Field(min_length=1, max_length=MAX_LINKS)
    joints: list[JointSpec] = Field(default_factory=list, max_length=MAX_LINKS)
    assumptions: list[str] = Field(default_factory=list,
                                   description="Every value you had to guess (dimensions, masses, limits).")


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------
class Issue(BaseModel):
    severity: Literal["error", "warn"]
    where: str            # link/joint name, "tree", or "xml"
    message: str          # cause
    suggestion: str = ""  # suggested fix
    link: Optional[str] = None  # link to highlight in the viewer (if any)


class ValidationResult(BaseModel):
    ok: bool
    summary: str          # "PASS · error 0 · warn 1"
    errors: int
    warnings: int
    issues: list[Issue]


# ---------------------------------------------------------------------------
# Mesh upload
# ---------------------------------------------------------------------------
class MeshProps(BaseModel):
    stored_name: Optional[str] = None
    original_name: Optional[str] = None
    status: Literal["ok", "failed"] = "ok"
    error: Optional[str] = None
    unit_guess: Optional[str] = None
    confidence: Optional[str] = None
    scale_to_m: Optional[float] = None
    bbox_m: Optional[list[float]] = None
    bbox_center_m: Optional[list[float]] = None
    volume_m3: Optional[float] = None
    mass_kg: Optional[float] = None
    com_m: Optional[list[float]] = None
    inertia: Optional[dict[str, float]] = None
    warnings: list[str] = Field(default_factory=list)


class UploadResponse(BaseModel):
    meshes: list[MeshProps]


# ---------------------------------------------------------------------------
# API requests / responses
# ---------------------------------------------------------------------------
class ValidateRequest(BaseModel):
    urdf: str = Field(max_length=MAX_URDF_CHARS)
    check_meshes: bool = True


class ValidateResponse(BaseModel):
    validation: ValidationResult
    artifact_id: Optional[str] = None   # id for /api/download/{id}
    robot_name: Optional[str] = None


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    meshes: list[str] = Field(default_factory=list, max_length=50,
                              description="stored_name values from /api/upload")
    baseUrdf: Optional[str] = Field(default=None, max_length=MAX_URDF_CHARS)

    @field_validator("meshes")
    @classmethod
    def _mesh_names(cls, v: list[str]) -> list[str]:
        for n in v:
            if not re.fullmatch(MESH_FILE_RE, n):
                raise ValueError(f"invalid mesh name: {n!r}")
        return v


class AttemptLog(BaseModel):
    attempt: int
    status: Literal["ok", "spec_invalid", "urdf_invalid", "api_error"]
    detail: list[str] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    urdf: str
    spec: RobotSpec
    assumptions: list[str]
    validation: ValidationResult
    artifact_id: str
    attempts: list[AttemptLog]
    model: str


class ErrorResponse(BaseModel):
    error: str     # machine-readable code, e.g. "missing_api_key"
    message: str   # human-readable


def robot_spec_json_schema() -> dict:
    """RobotSpec JSON schema with $ref inlined (used as the Claude tool input_schema)."""
    raw = RobotSpec.model_json_schema()
    defs = raw.pop("$defs", {})

    def inline(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                merged = {**inline(defs[name]), **{k: v for k, v in node.items() if k != "$ref"}}
                return merged
            return {k: inline(v) for k, v in node.items() if k not in ("title", "discriminator")}
        if isinstance(node, list):
            return [inline(x) for x in node]
        return node

    return inline(raw)
