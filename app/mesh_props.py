"""Mesh property calculation. A function-form port of `.claude/skills/mesh-processing/scripts/mesh_props.py`.

Same calculations as the original (unit guess, watertight check, density-based mass,
COM-relative inertia). Adds `bbox_center_m`, used to place the collision box.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import trimesh


def analyze(path: str, unit: Optional[str] = None, mass: Optional[float] = None,
            density: Optional[float] = None) -> dict:
    mesh = trimesh.load(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError("메시에 삼각형 면이 없음")
    warnings = []
    ext = float(np.max(mesh.extents))
    if unit:
        scale = 0.001 if unit == "mm" else 1.0
        guess, conf = unit, "user"
    else:
        guess, scale = ("mm", 0.001) if ext > 5 else ("m", 1.0)
        conf = "low"
        warnings.append("unit_guess_low_confidence")
    mesh = mesh.copy()
    mesh.apply_scale(scale)
    if not mesh.is_watertight:
        warnings.append("not_watertight")
    volume = float(abs(mesh.volume)) if mesh.is_watertight else float(np.prod(mesh.extents))
    if mass is None:
        mass = (density or 1000.0) * volume
        if density is None:
            warnings.append("mass_assumed_density_1000")
    if mass <= 0 or not np.isfinite(mass):
        mass = 1e-3
        warnings.append("mass_fallback_0.001kg")
    mesh.density = mass / volume if volume > 0 else 1.0
    com = mesh.center_mass if mesh.is_watertight else mesh.bounds.mean(axis=0)
    if mesh.is_watertight:
        i = mesh.moment_inertia
    else:
        x, y, z = mesh.extents
        i = np.diag([mass / 12 * (y**2 + z**2), mass / 12 * (x**2 + z**2), mass / 12 * (x**2 + y**2)])
    return {
        "unit_guess": guess,
        "confidence": conf,
        "scale_to_m": scale,
        "bbox_m": [float(v) for v in mesh.extents],
        "bbox_center_m": [float(v) for v in mesh.bounds.mean(axis=0)],
        "volume_m3": volume,
        "mass_kg": float(mass),
        "com_m": [float(v) for v in com],
        "inertia": {
            "ixx": float(i[0, 0]), "iyy": float(i[1, 1]), "izz": float(i[2, 2]),
            "ixy": float(i[0, 1]), "ixz": float(i[0, 2]), "iyz": float(i[1, 2]),
        },
        "warnings": warnings,
    }
