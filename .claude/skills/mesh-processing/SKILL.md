---
name: mesh-processing
description: STL/DAE/OBJ 메시에서 단위, 바운딩 박스, 부피, 질량중심, 관성 텐서, collision 단순화 값을 계산해 URDF 링크 수치로 변환한다. 사용자가 CAD/메시 파일을 URDF에 연결하거나 관성을 계산해 달라고 할 때 사용한다.
---

# 메시 처리

## 절차
1. `python -I scripts/mesh_props.py <mesh...> [--mass kg | --density kg/m3] [--unit mm|m] --out _workspace/02_mesh_props.json` 실행 (trimesh 필요: `pip install trimesh numpy`).
2. 결과의 `warnings`를 확인한다: `not_watertight`(부피·관성이 부정확), `unit_guess_low_confidence`.
3. 단위 판단: 바운딩 박스 최대 변이 > 5 이면 mm로 추정하되 `confidence`를 낮게 표기하고 사용자에게 확인 요청한다.
4. collision은 박스/원기둥 근사(바운딩 박스) 또는 convex hull을 제안한다.

## 출력 스키마
`{ "meshes": [ { "file", "unit_guess", "scale_to_m", "bbox_m":[x,y,z], "origin_offset_m", "volume_m3", "mass_kg", "com_m", "inertia": {ixx,iyy,izz,ixy,ixz,iyz}, "warnings":[] } ] }`

관성은 질량중심 기준이며 URDF `<inertial><origin xyz=com>`과 함께 써야 한다.
