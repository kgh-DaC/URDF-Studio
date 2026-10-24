"""FreeCAD 문서의 최상위 부품(Body/Part)을 STL로 내보내고 parts.json(위치·부피·bbox)을 만든다.

실행 방법 두 가지 (둘 다 같은 결과):
  A) FreeCAD GUI: 모델을 연 상태에서 메뉴 매크로 > 매크로... 로 이 파일을 실행. 출력 폴더는 OUT_DIR(아래) 또는 환경변수 FC_OUT.
  B) 명령줄:      set FC_FILE=C:\\cad\\robot.FCStd & set FC_OUT=C:\\cad\\export & FreeCADCmd export_parts.py

규칙
- 단위는 FreeCAD 기본(mm) 그대로 내보낸다. parts.json 의 unit 은 "mm" 이고 mesh-processing 이 scale 0.001 로 변환한다.
- STL 은 문서 좌표계(월드) 기준 자세로 저장된다. 즉 모든 부품 메시가 조립된 위치에 있다.
  URDF 에서는 각 링크의 visual origin 을 -(링크 기준점) 으로 맞추거나, 링크 프레임을 부품 pivot 으로 재정의한다.
- 숨김(Visibility=False) 부품, 스케치/평면/축 같은 비솔리드 객체는 건너뛴다.
- 파일명은 [a-z0-9_] 로 정규화한다(웹 앱 업로드 규칙과 동일).
"""
import json
import math
import os
import re

import FreeCAD
import Mesh

OUT_DIR = os.environ.get("FC_OUT") or os.path.join(os.path.expanduser("~"), "freecad_export")
FC_FILE = os.environ.get("FC_FILE")


def safe(name):
    s = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    return s if s and s[0].isalpha() else "part_" + s


def top_level_solids(doc):
    """부모가 없는 객체 중 Shape 가 솔리드인 것 (Body 는 Tip 형상 사용)."""
    for o in doc.Objects:
        if o.InList and any(p.isDerivedFrom("App::Part") or p.isDerivedFrom("PartDesign::Body") for p in o.InList):
            continue  # Body/Part 내부 피처는 상위 객체가 대표한다
        shape = getattr(o, "Shape", None)
        if shape is None or shape.isNull() or not shape.Solids:
            continue
        if hasattr(o, "Visibility") and not o.Visibility:
            continue
        yield o


def main():
    if FC_FILE:
        doc = FreeCAD.openDocument(FC_FILE)
    else:
        doc = FreeCAD.ActiveDocument
    if doc is None:
        raise SystemExit("열린 FreeCAD 문서가 없습니다. 모델을 열거나 FC_FILE 을 지정하세요.")
    os.makedirs(OUT_DIR, exist_ok=True)

    parts, used = [], set()
    for o in top_level_solids(doc):
        name = safe(o.Name)
        while name in used:
            name += "_"
        used.add(name)
        fname = name + ".stl"
        Mesh.export([o], os.path.join(OUT_DIR, fname))

        sh = o.Shape
        bb = sh.BoundBox
        yaw, pitch, roll = o.Placement.Rotation.toEuler()  # 도(deg), Z-Y-X 순서
        parts.append({
            "name": name,
            "label": o.Label,
            "file": fname,
            "unit": "mm",
            "volume_mm3": sh.Volume,
            "bbox_mm": [bb.XLength, bb.YLength, bb.ZLength],
            "bbox_min_mm": [bb.XMin, bb.YMin, bb.ZMin],
            "placement_xyz_mm": [o.Placement.Base.x, o.Placement.Base.y, o.Placement.Base.z],
            "placement_rpy_rad": [math.radians(roll), math.radians(pitch), math.radians(yaw)],
            "center_of_mass_mm": [sh.CenterOfMass.x, sh.CenterOfMass.y, sh.CenterOfMass.z],
            "frame": "world",
        })

    with open(os.path.join(OUT_DIR, "parts.json"), "w", encoding="utf-8") as f:
        json.dump({"source": doc.FileName or doc.Name, "unit": "mm", "parts": parts}, f, ensure_ascii=False, indent=2)
    FreeCAD.Console.PrintMessage("내보내기 완료: %d개 부품 -> %s\n" % (len(parts), OUT_DIR))


main()
