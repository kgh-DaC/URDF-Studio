"""FreeCAD → URDF → 검증 → ROS 2 워크스페이스 설치 데모 (FreeCAD 없이 실행 가능).

1단계에서 FreeCAD 가 내보낸 결과(부품별 STL[mm] + parts.json)를 '흉내 내서' 만든다.
실제 사용에서는 1단계 대신 .claude/skills/freecad-export/scripts/export_parts.py 가 같은 형식의 파일을 만든다.
사용:  python run_demo.py --ws <워크스페이스 폴더>      (폴더가 없으면 만든다)
"""
import argparse, json, os, pathlib, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
os.environ.setdefault("URDF_APP_DATA", tempfile.mkdtemp(prefix="demo_data_"))
sys.path.insert(0, str(REPO / "app"))
import trimesh                                   # noqa: E402
from builder import build_urdf                   # noqa: E402
from mesh_props import analyze                   # noqa: E402
from schema import JointSpec, LinkSpec, Limit, MeshProps, MeshGeometry, Origin, RobotSpec  # noqa: E402

DENSITY = 2700.0   # 알루미늄 kg/m3 (가정)
MESH_DIR = HERE / "meshes"
OUT = HERE / "output"

# ── 1단계: FreeCAD 내보내기 결과 흉내 (mm, 월드 좌표) ──────────────────────────
PARTS = [  # (이름, 크기 x,y,z mm, 월드 중심 z mm)
    ("base",  (120, 120, 20), 10),     # z 0~20
    ("arm1",  (20, 20, 150), 95),      # z 20~170, 어깨 pivot z=20
    ("arm2",  (16, 16, 100), 220),     # z 170~270, 팔꿈치 pivot z=170
]


def fake_freecad_export():
    MESH_DIR.mkdir(exist_ok=True)
    parts = []
    for name, size, zc in PARTS:
        m = trimesh.creation.box(size)
        m.apply_translation([0, 0, zc])
        m.export(MESH_DIR / f"{name}.stl")
        parts.append({"name": name, "file": f"{name}.stl", "unit": "mm", "bbox_mm": list(size),
                      "center_of_mass_mm": [0, 0, zc], "frame": "world"})
    (HERE / "parts.json").write_text(json.dumps({"unit": "mm", "parts": parts}, indent=2))
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", required=True)
    a = ap.parse_args()

    print("① FreeCAD 내보내기 결과 준비 (흉내)")
    parts = {p["name"]: p for p in fake_freecad_export()}

    print("② 메시 물성 계산 (단위 mm 명시, 알루미늄 밀도)")
    props = {}
    for n, p in parts.items():
        r = analyze(str(MESH_DIR / p["file"]), unit="mm", density=DENSITY)
        props[p["file"]] = MeshProps(stored_name=p["file"], status="ok", **r)
        print(f"   {n}: 질량 {r['mass_kg']:.3f} kg, 경고 {r['warnings']}")

    print("③ 링크·조인트 구성 → URDF")
    # 링크 프레임 = 조인트 pivot(월드, m). 메시는 월드 좌표라 visual_origin = -pivot.
    pivots = {"base": (0, 0, 0), "arm1": (0, 0, 0.020), "arm2": (0, 0, 0.170)}

    def link(n):
        px = pivots[n]
        return LinkSpec(name=f"{n}_link", mass=props[parts[n]["file"]].mass_kg,
                        geometry=MeshGeometry(type="mesh", mesh_file=parts[n]["file"]),
                        visual_origin=Origin(xyz=[-v for v in px]))

    def joint(n, parent, child, axis):
        d = [c - p for c, p in zip(pivots[child], pivots[parent])]
        return JointSpec(name=n, type="revolute", parent=f"{parent}_link", child=f"{child}_link",
                         origin=Origin(xyz=d), axis=axis,
                         limit=Limit(lower=-1.57, upper=1.57, effort=10, velocity=2.0))

    spec = RobotSpec(
        robot_name="freecad_demo_arm",
        links=[link("base"), link("arm1"), link("arm2")],
        joints=[joint("shoulder_joint", "base", "arm1", [0, 1, 0]),
                joint("elbow_joint", "arm1", "arm2", [0, 1, 0])],
        assumptions=["밀도 2700 kg/m3(알루미늄) 가정", "회전축은 Y축, 범위 ±90° 가정(사용자 확인 필요)"])
    urdf, notes = build_urdf(spec, lambda f: props.get(f))
    OUT.mkdir(exist_ok=True)
    urdf_path = OUT / "freecad_demo_arm.urdf"
    urdf_path.write_text(urdf, encoding="utf-8")
    # xacro: 현재는 URDF 에 xacro 네임스페이스와 공통 속성만 얹은 최소 형태
    xacro = urdf.replace("<robot ", '<robot xmlns:xacro="http://www.ros.org/wiki/xacro" ', 1)
    xacro = xacro.replace(">", '>\n  <xacro:property name="density" value="2700"/>', 1)
    (OUT / "freecad_demo_arm.urdf.xacro").write_text(xacro, encoding="utf-8")
    for n in notes:
        print("   -", n)

    print("④ 검증 + 워크스페이스 설치")
    os.makedirs(a.ws, exist_ok=True)
    cmd = [sys.executable, "-I", str(REPO / ".claude/skills/ros2-workspace-install/scripts/install_to_workspace.py"),
           "--urdf", str(urdf_path), "--xacro", str(OUT / "freecad_demo_arm.urdf.xacro"),
           "--meshes", str(MESH_DIR), "--ws", a.ws, "--force"]
    sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
