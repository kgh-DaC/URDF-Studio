---
name: ros2-workspace-install
description: 검증을 통과한 URDF/xacro를 ROS 2 워크스페이스 src/ 폴더에 <robot>_description 패키지로 설치한다. '워크스페이스에 넣어줘', 'ros2_ws에 설치', 'colcon build 할 수 있게' 요청 시 사용한다.
---

# ROS 2 워크스페이스 설치

## 절차
1. 워크스페이스 경로를 사용자에게 확인한다(예: `C:\ros2_ws`, WSL은 `\\wsl$\Ubuntu\home\<user>\ros2_ws`, Linux는 `~/ros2_ws`). 폴더는 사용자가 미리 만들어 둔 것이어야 하며 스크립트가 만들지 않는다.
2. 먼저 `--dry-run`으로 패키지명·위치·메시 수를 보여 주고 사용자 확인을 받는다.
3. 실제 설치:
   `python -I .claude/skills/ros2-workspace-install/scripts/install_to_workspace.py --urdf output/<robot>.urdf [--xacro output/<robot>.urdf.xacro] [--meshes <STL 폴더>] --ws <워크스페이스>`
4. 스크립트가 알아서 하는 일: 검증(`validate_urdf.py`) error 있으면 중단 → 메시 참조 `package://<pkg>/meshes/`로 재작성·복사 → `package.xml`, `CMakeLists.txt`, `launch/display.launch.py`, `rviz/` 생성(웹 앱 zip과 같은 템플릿).
5. 같은 이름 패키지가 있으면 중단한다. 사용자가 덮어쓰기를 승인하면 `--force`: 기존 폴더는 `<ws>/backup/`으로 옮겨 보존한다(삭제 없음).
6. 출력된 `colcon build --packages-select <pkg>` 등 다음 명령을 사용자에게 안내한다.

## 한계
- `colcon build`·`ros2 launch`는 이 도구가 실행하지 않는다(ROS 2 미설치 환경이 많다). 설치 성공은 파일 배치와 정적 검증 통과를 뜻할 뿐이며, 실제 RViz 확인은 사용자 ROS 2 환경에서 한다.
- xacro는 변환하지 않는다. 변환된 `.urdf`를 `--urdf`로 주고 원본 `.xacro`는 참고용으로 같이 복사된다.
