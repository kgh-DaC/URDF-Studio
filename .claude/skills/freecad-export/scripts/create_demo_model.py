"""FreeCAD 에서 실행하면 데모 모델(base/arm1/arm2 박스 3개, mm)을 새 문서로 만든다.
export_parts.py 를 시험해 볼 때 직접 모델링하지 않아도 되도록 둔 매크로.
실행: FreeCAD > 매크로 > 매크로... > 이 파일 선택 > 실행
"""
import FreeCAD
import Part

doc = FreeCAD.newDocument("demo_arm")
for name, (sx, sy, sz), z0 in [("base", (120, 120, 20), 0), ("arm1", (20, 20, 150), 20), ("arm2", (16, 16, 100), 170)]:
    o = doc.addObject("Part::Feature", name)
    o.Shape = Part.makeBox(sx, sy, sz, FreeCAD.Vector(-sx / 2, -sy / 2, z0))
doc.recompute()
FreeCAD.Console.PrintMessage("데모 모델 생성 완료: base, arm1, arm2\n")
