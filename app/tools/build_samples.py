"""Regenerate samples/*.urdf from samples/*.spec.json with the builder.

Usage (from app/): python tools/build_samples.py
"""
import json
import pathlib
import sys

APP = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from builder import build_urdf  # noqa: E402
from schema import RobotSpec  # noqa: E402
from validator import format_report, validate_urdf  # noqa: E402

for spec_file in sorted((APP / "samples").glob("*.spec.json")):
    spec = RobotSpec.model_validate(json.loads(spec_file.read_text(encoding="utf-8")))
    xml, notes = build_urdf(spec)
    out = spec_file.with_name(spec_file.name.replace(".spec.json", ".urdf"))
    out.write_text(xml, encoding="utf-8")
    print(f"{out.name}: {format_report(validate_urdf(xml)).splitlines()[0]}")
