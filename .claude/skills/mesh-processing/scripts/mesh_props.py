"""메시 파일에서 URDF용 물성값을 계산한다.

사용: python -I mesh_props.py a.stl b.dae --mass 1.5 --out props.json
"""
import argparse
import json
import sys

import numpy as np
import trimesh


def analyze(path, unit, mass, density):
    mesh = trimesh.load(path, force="mesh")
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
    mesh.density = mass / volume if volume > 0 else 1.0
    com = mesh.center_mass if mesh.is_watertight else mesh.bounds.mean(axis=0)
    if mesh.is_watertight:
        i = mesh.moment_inertia
    else:
        x, y, z = mesh.extents
        i = np.diag([mass / 12 * (y**2 + z**2), mass / 12 * (x**2 + z**2), mass / 12 * (x**2 + y**2)])
    return {
        "file": path,
        "unit_guess": guess,
        "confidence": conf,
        "scale_to_m": scale,
        "bbox_m": [float(v) for v in mesh.extents],
        "volume_m3": volume,
        "mass_kg": float(mass),
        "com_m": [float(v) for v in com],
        "inertia": {
            "ixx": float(i[0, 0]), "iyy": float(i[1, 1]), "izz": float(i[2, 2]),
            "ixy": float(i[0, 1]), "ixz": float(i[0, 2]), "iyz": float(i[1, 2]),
        },
        "warnings": warnings,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("meshes", nargs="+")
    ap.add_argument("--mass", type=float)
    ap.add_argument("--density", type=float)
    ap.add_argument("--unit", choices=["mm", "m"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    results = []
    for p in a.meshes:
        try:
            results.append(analyze(p, a.unit, a.mass, a.density))
        except Exception as e:  # 한 파일 실패가 나머지를 막지 않게 한다
            results.append({"file": p, "status": "failed", "error": str(e)})
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"meshes": results}, f, indent=2)
    print(f"wrote {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
