---
name: urdf-authoring
description: ROS 2용 URDF/xacro를 작성·수정하는 규칙. 링크·조인트 트리 설계, 좌표계, 관성 공식, xacro 매크로, 메시 참조, ROS 2 패키징을 다룬다. 로봇 구조 설계, URDF 생성·수정·리팩터링, xacro 변환, 'URDF 만들어줘' 요청 시 사용한다.
---

# URDF 작성 규칙

## 1. 설계 순서 (이유: 트리 구조를 먼저 고정해야 좌표계 오류가 줄어든다)
1. 요구를 표준 구조 명세 형식 **RobotSpec**(원본: `app/schema.py`, 요약: `_workspace/03_webapp_schema.md`)으로 구조화해 `_workspace/01_architect_spec.json`에 저장한다. 최상위 필드는 `robot_name`, `links[]`, `joints[]`, `assumptions[]`만 허용한다(그 밖의 필드 금지: `robot`, `description`, `parameters`, `tree` 등).
   - `links[]`: `name`, `geometry`(box{size[3]} | cylinder{radius,length} | sphere{radius} | mesh{mesh_file, scale?} | null=가상 링크), `visual_origin`{xyz, rpy}(링크 좌표계 기준 형상 중심), 선택 `collision`/`collision_origin`, `mass`(kg, >0), 선택 `color`(rgba[4]).
   - 원기둥은 로컬 z축 기준이다. 다른 축이 필요하면 `visual_origin.rpy`로 돌린다(y축: `[1.5708, 0, 0]`, x축: `[0, 1.5708, 0]`).
   - `joints[]`: `name`, `type`(fixed|revolute|continuous|prismatic), `parent`, `child`, `origin`{xyz, rpy}, `axis`[3](fixed 외 필수), `limit`{lower?, upper?, effort, velocity}.
   - **관성 텐서와 inertial origin은 명세에 넣지 않는다.** 코드(`app/builder.py`)나 3장 공식이 `geometry`·`mass`·`visual_origin`에서 계산한다(inertial origin = visual_origin).
   - 저장 전후 확인: `RobotSpec.model_validate(json)` → `builder.check_spec()` 오류 0 → `builder.build_urdf()` 결과를 `validator.validate_urdf()`로 PASS 확인(app 가상환경 `app/.venv`에서 실행).
   - RobotSpec 파일을 `builder.architect_to_spec()`에 넣지 않는다. 이 함수는 예전 형식(`robot`, 실린더 `geometry.axis`, `inertial_origin`) 전용 호환 변환기라서, RobotSpec 입력을 넣으면 `visual_origin`(xyz·rpy)을 오류 없이 버린다(바퀴 회전과 팔 COM 오프셋이 사라짐).
   - xacro에서 손으로 쓴 관성은 inertial rpy=0 기준(예: y축 바퀴는 iyy=m r²/2)으로 적어도 된다. builder는 inertial rpy=visual_origin rpy로 원기둥 자체 축 기준 텐서를 쓰므로 비교할 때는 R·I·Rᵀ(`builder.inertia_in_parent`)로 링크 좌표계 텐서를 맞춘다.
2. 루트 링크는 `base_link` 하나. URDF는 트리만 가능하므로 폐루프는 허용하지 않는다.
3. 조인트 `origin`은 부모 링크 좌표계 기준임을 항상 확인한다.
4. 가정한 수치는 `assumptions[]`에 남긴다. RobotSpec에 필드가 없는 URDF 요소(`<dynamics>` 등)를 xacro에 넣었다면 그 사실도 기록한다.

## 2. 조인트 규칙
- revolute·prismatic은 `<limit lower upper effort velocity>` 모두 필수. continuous는 limit에서 effort/velocity만.
- `axis`는 단위벡터. 조인트 좌표계 기준.
- 이름은 `<부모>_to_<자식>_joint` 또는 의미 있는 이름(`shoulder_pan_joint`). 링크/조인트 이름은 전체에서 유일.

## 3. 관성 (임의 값 금지)
질량 m, 크기로 계산:
- 박스(x,y,z): ixx=m/12(y²+z²), iyy=m/12(x²+z²), izz=m/12(x²+y²)
- 원기둥(반지름 r, 높이 h, 축 z): ixx=iyy=m/12(3r²+h²), izz=m r²/2
- 구: 2/5 m r²
- 메시는 mesh-processing 스킬 결과를 쓴다. 모든 링크에 양의 질량과 양의 정부호 관성을 준다(0 금지; 가상 링크는 1e-6 정도).

## 4. 메시
- visual은 상세 메시, collision은 단순 형상 또는 단순화 메시.
- 경로는 `package://<pkg>/meshes/<file>`. 스케일이 필요하면 `<mesh scale="..."/>`.

## 5. xacro
- `xacro:property`로 치수, `xacro:macro`로 반복 구조(바퀴·다리). 최상위 `<robot name xmlns:xacro="http://www.ros.org/wiki/xacro">`.
- 변환: `xacro in.urdf.xacro -o out.urdf`.

## 6. ROS 2 패키징
`<robot>_description/{package.xml, CMakeLists.txt, urdf/, meshes/, launch/display.launch.py, rviz/}`. launch는 robot_state_publisher(`robot_description`는 `Command(['xacro ', path])`), joint_state_publisher_gui, rviz2. ros2_control 태그는 요청 시에만 추가한다.

## 7. 수정 요청
기존 파일을 먼저 읽고 변경 부분만 Edit한다. 전체를 다시 쓰면 사용자의 수동 수정이 사라진다.
