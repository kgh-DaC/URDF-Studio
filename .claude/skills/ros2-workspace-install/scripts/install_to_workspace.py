"""검증된 URDF를 ROS 2 워크스페이스 src/ 아래에 <robot>_description 패키지로 설치한다.

사용:
  python -I install_to_workspace.py --urdf output/x.urdf --ws C:\\ros2_ws [--meshes DIR] [--xacro output/x.urdf.xacro] [--dry-run] [--force]

안전장치: 검증 error가 있으면 설치하지 않는다. 같은 이름 패키지가 있으면 --force 없이는 중단하고,
--force면 <pkg>.bak-<시각>으로 옮긴 뒤 덮어쓴다(삭제하지 않는다).
"""
import argparse
import datetime
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[3]
VALIDATE = REPO / ".claude" / "skills" / "urdf-validation" / "scripts" / "validate_urdf.py"
os.environ.setdefault("URDF_APP_DATA", tempfile.mkdtemp(prefix="urdf_install_"))  # ros_package import 부작용 격리
sys.path.insert(0, str(REPO / "app"))
import ros_package as rp  # noqa: E402  (패키지 템플릿 재사용: 웹 앱 zip과 동일 구조)
from builder import package_name  # noqa: E402


def fail(msg):
    print(f"[중단] {msg}")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urdf", required=True)
    ap.add_argument("--ws", required=True, help="ROS 2 워크스페이스 루트(src/가 있는 폴더)")
    ap.add_argument("--meshes", help="메시 폴더. package://*/meshes/<file> 참조를 여기서 찾는다")
    ap.add_argument("--xacro", help="원본 xacro. 있으면 패키지 urdf/ 에도 함께 넣는다")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    urdf_path = pathlib.Path(a.urdf)
    if not urdf_path.is_file():
        fail(f"URDF 파일이 없습니다: {urdf_path}")
    urdf = urdf_path.read_text(encoding="utf-8")
    try:
        robot = ET.fromstring(urdf).get("name") or ""
    except ET.ParseError as e:
        fail(f"URDF XML 구문 오류: {e}")
    if not robot:
        fail("<robot name> 이 없습니다")

    # 1) 검증 게이트
    mesh_root = str(pathlib.Path(a.meshes).resolve().parent) if a.meshes else None
    cmd = [sys.executable, "-I", str(VALIDATE), str(urdf_path)] + (["--mesh-root", mesh_root] if mesh_root else [])
    v = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print(v.stdout.strip())
    if v.returncode != 0:
        fail("검증 오류가 있어 설치하지 않습니다. 위 error를 먼저 고치세요.")

    # 2) 메시 수집
    pkg = package_name(robot)
    file_robot = re.sub(r"[^A-Za-z0-9_\-]", "_", robot)
    refs = sorted({m.group(1) for m in rp.MESH_REF.finditer(urdf)})
    mesh_dir = pathlib.Path(a.meshes) if a.meshes else None
    missing = [f for f in refs if not (mesh_dir and (mesh_dir / f).is_file())]
    if missing:
        fail(f"참조된 메시가 --meshes 폴더에 없습니다: {missing}")
    out_urdf = rp.MESH_REF.sub(lambda m: f"package://{pkg}/meshes/{m.group(1)}", urdf)

    # 3) 대상 경로
    ws = pathlib.Path(a.ws)
    src = ws / "src"
    target = src / pkg
    print(f"패키지: {pkg}\n설치 위치: {target}\n메시 {len(refs)}개")
    if a.dry_run:
        print("[dry-run] 파일은 쓰지 않았습니다.")
        return
    if not ws.is_dir():
        fail(f"워크스페이스 폴더가 없습니다: {ws} (먼저 만들거나 경로를 확인하세요)")
    if target.exists():
        if not a.force:
            fail(f"이미 존재합니다: {target}. 덮어쓰려면 --force (기존 폴더는 .bak으로 보존됨)")
        bak = target.with_name(f"{pkg}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}")
        # colcon이 .bak 패키지를 중복 패키지로 읽지 않도록 src 밖으로 이동
        bak_root = ws / "backup"
        bak_root.mkdir(exist_ok=True)
        shutil.move(str(target), str(bak_root / bak.name))
        print(f"기존 패키지를 {bak_root / bak.name} 로 옮겼습니다.")

    # 4) 패키지 작성
    for d in ("urdf", "meshes", "launch", "rviz"):
        (target / d).mkdir(parents=True)
    (target / "package.xml").write_text(rp.PACKAGE_XML.format(pkg=pkg, robot=rp.xml_escape(robot)), encoding="utf-8")
    (target / "CMakeLists.txt").write_text(rp.CMAKELISTS.format(pkg=pkg), encoding="utf-8")
    (target / "urdf" / f"{file_robot}.urdf").write_text(out_urdf, encoding="utf-8")
    if a.xacro:
        shutil.copy(a.xacro, target / "urdf" / f"{file_robot}.urdf.xacro")
    (target / "launch" / "display.launch.py").write_text(rp.LAUNCH.format(pkg=pkg, robot=file_robot), encoding="utf-8")
    (target / "rviz" / "display.rviz").write_text(rp.RVIZ, encoding="utf-8")
    (target / "README.md").write_text(rp.README.format(pkg=pkg), encoding="utf-8")
    for f in refs:
        shutil.copy(mesh_dir / f, target / "meshes" / f)
    if not refs:
        (target / "meshes" / ".keep").write_text("")

    print(f"\n설치 완료. ROS 2 쪽에서 실행:\n  cd {ws}\n  colcon build --packages-select {pkg}\n"
          f"  source install/setup.bash   (Windows: call install\\setup.bat)\n  ros2 launch {pkg} display.launch.py")


if __name__ == "__main__":
    main()
