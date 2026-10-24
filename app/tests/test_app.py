"""Run (from app/): python -m pytest -q"""
import io
import json
import math
import os
import pathlib
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
os.environ.setdefault("URDF_APP_DATA", tempfile.mkdtemp(prefix="urdfapp_test_"))
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["URDF_APP_ALLOWED_HOSTS"] = "testserver,127.0.0.1,localhost"  # TestClient Host = testserver

import builder  # noqa: E402
import llm  # noqa: E402
from schema import RobotSpec  # noqa: E402
from validator import validate_urdf  # noqa: E402

SKILL_SCRIPT = APP.parent / ".claude" / "skills" / "urdf-validation" / "scripts" / "validate_urdf.py"
SAMPLES = APP / "samples"


def load_spec(name):
    return RobotSpec.model_validate(json.loads((SAMPLES / f"{name}.spec.json").read_text(encoding="utf-8")))


# ---------------------------------------------------------------- validator parity
@pytest.mark.parametrize("sample", ["two_link_arm", "diff_drive_robot", "broken_arm"])
def test_validator_matches_skill_script(sample):
    if not SKILL_SCRIPT.exists():
        pytest.skip("skill script not found")
    path = SAMPLES / f"{sample}.urdf"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, "-I", "-X", "utf8", str(SKILL_SCRIPT), str(path)], capture_output=True,
                         text=True, encoding="utf-8", env=env).stdout.strip().splitlines()
    mine = validate_urdf(path.read_text(encoding="utf-8"))
    assert out[0] == mine.summary
    assert Counter(out[1:]) == Counter(f"{i.severity} · {i.where} · {i.message}" for i in mine.issues)


def test_validator_handles_garbage():
    assert not validate_urdf("<robot><link").ok
    assert not validate_urdf("<foo/>").ok
    r = validate_urdf('<robot name="r"><link name="a"/><link name="b"/>'
                      '<joint name="j" type="revolute"><parent link="a"/><child link="b"/>'
                      '<limit lower="x" upper="1" effort="1" velocity="1"/></joint></robot>')
    assert any("숫자가 아님" in i.message for i in r.issues)


# ---------------------------------------------------------------- builder
def test_inertia_formulas():
    b = builder.box_inertia(2.0, 0.1, 0.2, 0.3)
    assert math.isclose(b["ixx"], 2 / 12 * (0.04 + 0.09))
    c = builder.cylinder_inertia(1.0, 0.05, 0.2)
    assert math.isclose(c["izz"], 0.5 * 0.0025) and math.isclose(c["ixx"], 1 / 12 * (3 * 0.0025 + 0.04))
    s = builder.sphere_inertia(1.0, 0.1)
    assert math.isclose(s["ixx"], 0.4 * 0.01)


@pytest.mark.parametrize("sample", ["two_link_arm", "diff_drive_robot"])
def test_build_samples_pass(sample):
    spec = load_spec(sample)
    assert builder.check_spec(spec)[0] == []
    xml, _ = builder.build_urdf(spec)
    r = validate_urdf(xml)
    assert r.ok and r.warnings == 0, r.issues


def test_check_spec_finds_defects():
    spec = load_spec("two_link_arm").model_copy(deep=True)
    spec.joints[1].limit = None
    spec.joints[2].parent = "ghost_link"
    errs, _ = builder.check_spec(spec)
    assert any("requires limit" in e for e in errs)
    assert any("ghost_link" in e for e in errs)


def test_continuous_default_limit_and_axis_normalized():
    spec = load_spec("diff_drive_robot").model_copy(deep=True)
    spec.joints[0].limit = None
    spec.joints[0].axis = [0, 2, 0]
    xml, notes = builder.build_urdf(spec)
    assert 'xyz="0 1 0"' in xml and any("defaulted" in n for n in notes)
    assert validate_urdf(xml).ok


def test_urdf_roundtrip():
    xml = (SAMPLES / "two_link_arm.urdf").read_text(encoding="utf-8")
    spec, notes = builder.urdf_to_spec(xml)
    xml2, _ = builder.build_urdf(spec)
    assert validate_urdf(xml2).ok
    assert [l.name for l in spec.links] == [l.name for l in load_spec("two_link_arm").links]


ARCH = APP.parent / "_workspace" / "01_architect_spec.json"
REF_URDF = APP.parent / "output" / "sample_robot.urdf"
_TENSOR = ("ixx", "iyy", "izz", "ixy", "ixz", "iyz")


def _inertials(xml):
    """{link: (mass, xyz, tensor in the link frame)} from <inertial>, rotated by its origin rpy (R·I·Rᵀ)."""
    import xml.etree.ElementTree as ET
    out = {}
    for link in ET.fromstring(xml.encode("utf-8")).findall("link"):
        ie = link.find("inertial")
        if ie is None:
            continue
        o = ie.find("origin")
        xyz = [float(v) for v in (o.get("xyz", "0 0 0") if o is not None else "0 0 0").split()]
        rpy = [float(v) for v in (o.get("rpy", "0 0 0") if o is not None else "0 0 0").split()]
        t = {k: float(ie.find("inertia").get(k, "0")) for k in _TENSOR}
        out[link.get("name")] = (float(ie.find("mass").get("value")), xyz, builder.inertia_in_parent(t, rpy))
    return out


def _assert_tensor_close(name, got, ref, rel=1e-5):
    scale = max(abs(ref[k]) for k in _TENSOR)
    for k in _TENSOR:  # file values are printed to ~6 significant digits; rpy 1.5708 != pi/2 exactly
        assert abs(got[k] - ref[k]) <= rel * scale, (name, k, got, ref)


@pytest.mark.skipif(not (ARCH.exists() and REF_URDF.exists()), reason="architect spec / reference URDF not present")
def test_architect_spec_builds_and_matches_reference_urdf():
    # 01_architect_spec.json is RobotSpec format (QA W11): validate directly, no architect_to_spec conversion
    spec = RobotSpec.model_validate(json.loads(ARCH.read_text(encoding="utf-8")))
    xml, _ = builder.build_urdf(spec)
    r = validate_urdf(xml)
    assert r.ok, r.issues
    built = _inertials(xml)
    ref = _inertials(REF_URDF.read_text(encoding="utf-8"))
    assert sorted(built) == sorted(ref) == sorted(l.name for l in spec.links)
    compared = 0
    for name, (m_ref, xyz_ref, t_ref) in ref.items():  # QA W12a: full tensor in the link frame
        m, xyz, t = built[name]
        assert math.isclose(m, m_ref, rel_tol=1e-9), (name, m, m_ref)
        assert all(abs(a - b) <= 1e-9 for a, b in zip(xyz, xyz_ref)), (name, xyz, xyz_ref)
        _assert_tensor_close(name, t, t_ref)
        compared += 1
    assert compared == 9
    # visual_origin must survive (the old converter path silently dropped it)
    for link in spec.links:
        if link.name.endswith("wheel_link"):
            assert math.isclose(link.visual_origin.rpy[0], 1.5708)


@pytest.mark.skipif(not ARCH.exists(), reason="architect spec not present")
def test_architect_to_spec_rejects_robotspec_input():
    d = json.loads(ARCH.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="already RobotSpec"):
        builder.architect_to_spec(d)
    no_name = {k: v for k, v in d.items() if k != "robot_name"}  # visual_origin alone is enough
    with pytest.raises(ValueError, match="already RobotSpec"):
        builder.architect_to_spec(no_name)
    with pytest.raises(ValueError, match="already RobotSpec"):
        builder.architect_to_spec({**_arch_min("z"), "robot_name": "r"})


def _legacy_fixture():
    """Earlier urdf-architect output format (robot, geometry.axis, inertial_origin, precomputed inertia)."""
    def cyl(m, r, h):
        return m / 12 * (3 * r * r + h * h), m * r * r / 2
    wa, wz = cyl(1.0, 0.1, 0.05)
    pa, pz = cyl(0.5, 0.06, 0.05)
    return {
        "robot": "legacy_bot",
        "links": [
            {"name": "base_link", "mass": 10.0, "geometry": {"type": "box", "size": [0.6, 0.4, 0.15]},
             "inertial_origin": [0, 0, 0],
             "inertia": {"ixx": 10 / 12 * (0.16 + 0.0225), "iyy": 10 / 12 * (0.36 + 0.0225),
                         "izz": 10 / 12 * (0.36 + 0.16)}},
            {"name": "wheel_link", "mass": 1.0, "color": [0.1, 0.1, 0.1, 1.0],
             "geometry": {"type": "cylinder", "radius": 0.1, "length": 0.05, "axis": "y"},
             "inertia": {"ixx": wa, "iyy": wz, "izz": wa}},
            {"name": "pedestal_link", "mass": 0.5,
             "geometry": {"type": "cylinder", "radius": 0.06, "length": 0.05, "axis": "z"},
             "inertia": {"ixx": pa, "iyy": pa, "izz": pz}},
            {"name": "upper_arm_link", "mass": 1.0, "geometry": {"type": "box", "size": [0.05, 0.05, 0.3]},
             "inertial_origin": [0, 0, 0.15],
             "inertia": {"ixx": 1 / 12 * (0.0025 + 0.09), "iyy": 1 / 12 * (0.0025 + 0.09),
                         "izz": 1 / 12 * 0.005}},
        ],
        "joints": [
            {"name": "wheel_joint", "type": "continuous", "parent": "base_link", "child": "wheel_link",
             "origin": {"xyz": [0.2, 0.23, -0.05], "rpy": [0, 0, 0]}, "axis": [0, 1, 0],
             "limit": {"effort": 5.0, "velocity": 10.0}},
            {"name": "pedestal_joint", "type": "fixed", "parent": "base_link", "child": "pedestal_link",
             "origin": {"xyz": [0.1, 0, 0.1], "rpy": [0, 0, 0]}},
            {"name": "shoulder_joint", "type": "revolute", "parent": "pedestal_link", "child": "upper_arm_link",
             "origin": {"xyz": [0, 0, 0.025], "rpy": [0, 0, 0]}, "axis": [0, 1, 0],
             "limit": {"lower": -1.57, "upper": 1.57, "effort": 20.0, "velocity": 1.0}},
        ],
    }


def test_architect_legacy_format_converts_builds_and_inertia_agrees():
    spec, given = builder.architect_to_spec(_legacy_fixture())
    assert spec.robot_name == "legacy_bot"
    by = {l.name: l for l in spec.links}
    assert by["upper_arm_link"].visual_origin.xyz == [0, 0, 0.15]  # inertial_origin -> visual_origin xyz
    assert math.isclose(by["wheel_link"].visual_origin.rpy[0], math.pi / 2)  # axis "y" -> rpy
    xml, _ = builder.build_urdf(spec)
    r = validate_urdf(xml)
    assert r.ok and r.warnings == 0, r.issues
    assert [row["link"] for row in given] == [l["name"] for l in _legacy_fixture()["links"]]
    compared = 0
    for row in given:  # QA W12a: full tensor in the link frame, not sorted diagonals
        ref = {**{k: 0.0 for k in _TENSOR}, **row["given"]}
        _assert_tensor_close(row["link"], row["computed"], ref, rel=1e-9)
        compared += 1
    assert compared == 4
    built = _inertials(xml)  # the URDF itself agrees with the legacy tensor too
    for row in given:
        _assert_tensor_close(row["link"], built[row["link"]][2], {**{k: 0.0 for k in _TENSOR}, **row["given"]},
                             rel=1e-8)


def _arch_min(axis):
    return {"robot": "r", "links": [{"name": "base_link", "mass": 1.0,
                                     "geometry": {"type": "cylinder", "radius": 0.1, "length": 0.2, "axis": axis}}],
            "joints": []}


@pytest.mark.parametrize("axis", ["-y", [0, 1, 0], "w", None])
def test_architect_bad_axis_is_clear_error(axis):  # QA W11
    with pytest.raises(ValueError, match="geometry.axis must be 'x', 'y' or 'z'"):
        builder.architect_to_spec(_arch_min(axis))


@pytest.mark.parametrize("axis,expect", [("x", "ixx"), ("Y", "iyy"), ("z", "izz")])
def test_architect_axis_maps_to_rotation(axis, expect):
    _, given = builder.architect_to_spec(_arch_min(axis))
    assert given == []  # no precomputed inertia supplied
    _, rows = builder.architect_to_spec({**_arch_min(axis), "links": [{**_arch_min(axis)["links"][0],
                                                                       "inertia": {"ixx": 1, "iyy": 1, "izz": 1}}]})
    c = rows[0]["computed"]  # the axial moment m r^2 / 2 must land on the named axis
    assert math.isclose(c[expect], 0.5 * 1.0 * 0.01, rel_tol=1e-9)


# ---------------------------------------------------------------- QA E1-E3: edge cases, parity with the script
def _urdf(link_extra="", joint="", robot_attr='name="r"', mass="1", inertia=('0.01', '0.01', '0.01')):
    ixx, iyy, izz = inertia
    return (f'<robot {robot_attr}><link name="base_link"><inertial><mass value="1"/>'
            f'<inertia ixx="0.01" ixy="0" ixz="0" iyy="0.01" iyz="0" izz="0.01"/></inertial></link>'
            f'<link name="arm_link" {link_extra}><inertial><mass value="{mass}"/>'
            f'<inertia ixx="{ixx}" ixy="0" ixz="0" iyy="{iyy}" iyz="0" izz="{izz}"/></inertial></link>'
            f'{joint}</robot>')


def _joint(type_='revolute', limit='<limit lower="-1" upper="1" effort="5" velocity="1"/>', name='name="j1"'):
    t = f'type="{type_}"' if type_ is not None else ""
    return (f'<joint {name} {t}><parent link="base_link"/><child link="arm_link"/>'
            f'<axis xyz="0 0 1"/>{limit}</joint>')


EDGE_CASES = {
    "ok": (_urdf(joint=_joint()), True),
    "E1_nan_mass": (_urdf(mass="nan", joint=_joint()), False),
    "E1_inf_mass": (_urdf(mass="inf", joint=_joint()), False),
    "E1_text_mass": (_urdf(mass="heavy", joint=_joint()), False),
    "E1_nan_inertia": (_urdf(inertia=("nan", "nan", "nan"), joint=_joint()), False),
    "E1_inf_inertia": (_urdf(inertia=("inf", "0.01", "0.01"), joint=_joint()), False),
    "E2_empty_lower_upper": (_urdf(joint=_joint(limit='<limit lower="" upper="" effort="5" velocity="1"/>')), False),
    "E2_neg_effort_text_velocity": (_urdf(joint=_joint(limit='<limit lower="-1" upper="1" effort="-5" velocity="abc"/>')), False),
    "E2_nan_lower": (_urdf(joint=_joint(limit='<limit lower="nan" upper="1" effort="5" velocity="1"/>')), False),
    "E2_continuous_neg_velocity": (_urdf(joint=_joint("continuous", '<limit effort="5" velocity="-1"/>')), False),
    "E3_bogus_type": (_urdf(joint=_joint("bogus")), False),
    "E3_missing_type": (_urdf(joint=_joint(None)), False),
    "E3_missing_joint_name": (_urdf(joint=_joint(name="")), False),
    "E3_missing_robot_name": (_urdf(robot_attr="", joint=_joint()), False),
    "E3_missing_link_name": (_urdf(joint=_joint()).replace('<link name="arm_link" >', '<link >')
                             .replace('<child link="arm_link"/>', '<child link="base_link"/>'), False),
    "floating_type_ok": (_urdf(joint=_joint("floating", "")), True),
    # QA N1: off-diagonal inertia terms
    "N1_nan_ixy": (_urdf(joint=_joint()).replace('ixy="0" ixz="0" iyy="0.01" iyz="0" izz="0.01"/></inertial></link>'
                                                  '<joint', 'ixy="nan" ixz="0" iyy="0.01" iyz="0" izz="0.01"/>'
                                                  '</inertial></link><joint'), False),
    "N1_inf_ixz_text_iyz": (_urdf(joint=_joint()).replace('ixz="0"', 'ixz="inf"', 1)
                            .replace('iyz="0"', 'iyz="abc"', 1), False),
    "N1_offdiag_ok": (_urdf(joint=_joint()).replace('ixy="0"', 'ixy="-0.001"'), True),
    # QA N2: unnamed link + missing <parent>/<child> elements or link attributes
    "N2_unnamed_link_no_parent": (_urdf(joint=_joint()).replace('<link name="arm_link" >', '<link >')
                                  .replace('<parent link="base_link"/>', ''), False),
    "N2_no_child": (_urdf(joint=_joint()).replace('<child link="arm_link"/>', ''), False),
    "N2_empty_parent_attr": (_urdf(joint=_joint()).replace('<parent link="base_link"/>', '<parent/>'), False),
}


def _msgs(text):
    return [(i.where, i.message) for i in validate_urdf(text).issues]


def test_offdiag_inertia_not_a_number():  # QA N1
    # ixy on arm_link; ixz/iyz replaced once -> the first link (base_link)
    for case, where in (("N1_nan_ixy", "arm_link"), ("N1_inf_ixz_text_iyz", "base_link")):
        assert _msgs(EDGE_CASES[case][0]) == [(where, "관성 값이 숫자가 아님")], case


def test_missing_parent_child_reported_separately():  # QA N2
    m = _msgs(EDGE_CASES["N2_unnamed_link_no_parent"][0])
    assert ("j1", "parent 요소 누락") in m
    assert ("j1", "child 링크 'arm_link'가 존재하지 않음") in m
    roots = [msg for w, msg in m if w == "tree"]
    assert all("None" not in msg for msg in roots), roots
    assert all("None" not in msg for _, msg in m), m
    assert ("j1", "child 요소 누락") in _msgs(EDGE_CASES["N2_no_child"][0])
    assert ("j1", "parent link 속성 누락") in _msgs(EDGE_CASES["N2_empty_parent_attr"][0])


@pytest.mark.parametrize("case", sorted(EDGE_CASES))
def test_validator_edge_cases(case):
    text, ok = EDGE_CASES[case]
    r = validate_urdf(text)
    assert r.ok is ok, (case, [(i.where, i.message) for i in r.issues])


@pytest.mark.parametrize("case", sorted(EDGE_CASES))
def test_validator_parity_edge_cases(case, tmp_path):
    if not SKILL_SCRIPT.exists():
        pytest.skip("skill script not found")
    p = tmp_path / "e.urdf"
    p.write_text(EDGE_CASES[case][0], encoding="utf-8")
    out = subprocess.run([sys.executable, "-I", "-X", "utf8", str(SKILL_SCRIPT), str(p)], capture_output=True,
                         text=True, encoding="utf-8").stdout.strip().splitlines()
    mine = validate_urdf(EDGE_CASES[case][0])
    assert out[0] == mine.summary, (case, out, mine.issues)
    assert Counter(out[1:]) == Counter(f"{i.severity} · {i.where} · {i.message}" for i in mine.issues)


def test_validator_warns_non_package_mesh():  # QA W3
    t = _urdf(joint=_joint()).replace(
        '<link name="arm_link" >', '<link name="arm_link" ><visual><geometry><mesh filename="file:///nonexist/x.stl"/>'
                                   '</geometry></visual>')
    r = validate_urdf(t)
    assert any(i.severity == "warn" and "package://가 아닌" in i.message for i in r.issues)


def test_schema_rejects_nan_inf():  # QA W9
    from pydantic import ValidationError
    d = _sample_dict()
    d["links"][0]["visual_origin"]["xyz"] = [float("nan"), 0, 0]
    with pytest.raises(ValidationError):
        RobotSpec.model_validate(d)
    d = _sample_dict()
    d["links"][2]["geometry"]["size"] = [float("inf"), 1, 1]
    with pytest.raises(ValidationError):
        RobotSpec.model_validate(d)


def test_regex_no_trailing_newline():  # QA W8
    import storage
    assert storage.mesh_path("abc_x.stl\n") is None
    assert storage.load_artifact("0" * 32 + "\n") is None
    from pydantic import ValidationError
    from schema import GenerateRequest
    with pytest.raises(ValidationError):
        GenerateRequest(prompt="x", meshes=["abc_x.stl\n"])


# ---------------------------------------------------------------- Claude loop with a fake client
class _Block:
    def __init__(self, input_, id_="toolu_1"):
        self.type, self.name, self.id, self.input = "tool_use", llm.TOOL_NAME, id_, input_

    def model_dump(self, **_):
        return {"type": "tool_use", "name": self.name, "id": self.id, "input": self.input}


class FakeClient:
    def __init__(self, specs):
        self.specs, self.calls = list(specs), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw["messages"], default=str)))
        assert kw["tool_choice"] == {"type": "tool", "name": llm.TOOL_NAME}
        spec = self.specs.pop(0)
        return type("R", (), {"content": [_Block(spec, f"toolu_{len(self.calls)}")], "stop_reason": "tool_use"})()


def _sample_dict():
    return json.loads((SAMPLES / "two_link_arm.spec.json").read_text(encoding="utf-8"))


def test_generate_fixes_after_feedback():
    bad = _sample_dict()
    del bad["joints"][1]["limit"]
    fake = FakeClient([bad, _sample_dict()])
    out = llm.generate("arm", [], None, lambda n: None, None, client=fake)
    assert out["validation"].ok
    assert [a.status for a in out["attempts"]] == ["spec_invalid", "ok"]
    fb = fake.calls[1][-1]["content"][0]
    assert fb["type"] == "tool_result" and fb["is_error"] and "requires limit" in fb["content"]


def test_generate_stops_after_two_fix_rounds():
    bad = _sample_dict()
    bad["links"][0]["mass"] = -1
    fake = FakeClient([bad, bad, bad, bad])
    with pytest.raises(llm.GenerationError) as ei:
        llm.generate("arm", [], None, lambda n: None, None, client=fake)
    assert ei.value.code == "generation_failed" and len(fake.calls) == 3


def test_generate_without_key():
    with pytest.raises(llm.GenerationError) as ei:
        llm.generate("arm", [], None, lambda n: None, None)
    assert ei.value.code == "missing_api_key" and ei.value.status == 503


# ---------------------------------------------------------------- API
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def test_api_validate_and_download(client):
    good = (SAMPLES / "diff_drive_robot.urdf").read_text(encoding="utf-8")
    r = client.post("/api/validate", json={"urdf": good}).json()
    assert r["validation"]["ok"]
    d = client.get(f"/api/download/{r['artifact_id']}?format=zip")
    names = zipfile.ZipFile(io.BytesIO(d.content)).namelist()
    assert "diff_drive_robot_description/launch/display.launch.py" in names
    broken = (SAMPLES / "broken_arm.urdf").read_text(encoding="utf-8")
    rb = client.post("/api/validate", json={"urdf": broken}).json()["validation"]
    assert not rb["ok"] and rb["errors"] == 6


def test_api_generate_missing_key(client):
    r = client.post("/api/generate", json={"prompt": "arm"})
    assert r.status_code == 503 and r.json()["error"] == "missing_api_key"


def test_api_upload_and_generate_mesh_spec(client, tmp_path):
    import trimesh
    p = tmp_path / "part.stl"
    trimesh.creation.box(extents=[100, 40, 20]).export(p)
    with open(p, "rb") as fh:
        r = client.post("/api/upload", files=[("files", ("../../part.stl", fh, "model/stl"))],
                        data={"mass": "0.5"}).json()
    m = r["meshes"][0]
    assert m["status"] == "ok" and m["stored_name"].endswith("_part.stl") and "/" not in m["stored_name"]
    import storage
    spec = RobotSpec.model_validate({"robot_name": "m", "links": [
        {"name": "base_link", "geometry": {"type": "mesh", "mesh_file": m["stored_name"]}, "mass": 0.5}]})
    xml, notes = builder.build_urdf(spec, storage.get_mesh_props)
    res = validate_urdf(xml, str(storage.DATA_DIR))
    assert res.ok, res.issues
    assert 'scale="0.001 0.001 0.001"' in xml and "<box" in xml  # bbox collision


def test_api_rejects_bad_extension(client):
    r = client.post("/api/upload", files=[("files", ("x.exe", b"MZ", "application/octet-stream"))]).json()
    assert r["meshes"][0]["status"] == "failed"


@pytest.mark.parametrize("case", ["E1_nan_mass", "E2_empty_lower_upper", "E3_bogus_type"])
def test_api_validate_edge_cases_fail(client, case):
    v = client.post("/api/validate", json={"urdf": EDGE_CASES[case][0]}).json()["validation"]
    assert not v["ok"] and v["errors"] >= 1


def test_zip_package_xml_escapes_robot_name(client):  # QA E4
    import xml.etree.ElementTree as ET
    evil = (SAMPLES / "two_link_arm.urdf").read_text(encoding="utf-8").replace(
        '<robot name="two_link_arm">', '<robot name="x&lt;/description&gt;&lt;evil/&gt;&amp;">')
    aid = client.post("/api/validate", json={"urdf": evil}).json()["artifact_id"]
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/download/{aid}?format=zip").content))
    pkg_xml = next(n for n in z.namelist() if n.endswith("package.xml"))
    root = ET.fromstring(z.read(pkg_xml))  # must parse
    assert root.find("description").text.startswith("URDF description for x</description><evil/>&")
    assert all(".." not in n and not n.startswith("/") for n in z.namelist())


def test_artifacts_dedup_and_prune(client, monkeypatch):  # QA W1
    import storage
    text = (SAMPLES / "two_link_arm.urdf").read_text(encoding="utf-8")
    ids = {client.post("/api/validate", json={"urdf": text}).json()["artifact_id"] for _ in range(5)}
    assert len(ids) == 1
    monkeypatch.setattr(storage, "MAX_ARTIFACTS", 3)
    for i in range(6):
        client.post("/api/validate", json={"urdf": text.replace("two_link_arm", f"arm_{i}")})
    assert len(list(storage.ARTIFACT_DIR.glob("*.json"))) <= 3
    monkeypatch.setattr(storage, "ARTIFACT_TTL_S", -1)  # everything is expired, except the newest
    last = client.post("/api/validate", json={"urdf": text}).json()["artifact_id"]
    assert [p.stem for p in storage.ARTIFACT_DIR.glob("*.json")] == [last]
    assert client.get(f"/api/download/{last}").status_code == 200


def test_body_limit_chunked(client):  # QA W2: no Content-Length (chunked) is cut off too
    def gen():
        yield b'{"urdf": "'
        for _ in range(7):
            yield b"x" * (1024 * 1024)
        yield b'"}'
    r = client.post("/api/validate", content=gen(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"] == "payload_too_large"
    big = b"x" * (6 * 1024 * 1024)
    r = client.post("/api/validate", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_framework_errors_use_error_format(client):  # QA W4
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    r = client.get("/api/validate")
    assert r.status_code == 405 and r.json()["error"] == "method_not_allowed"


@pytest.mark.parametrize("field,val", [("mass", "nan"), ("mass", "inf"), ("density", "nan"), ("mass", "-1")])
def test_upload_rejects_non_finite_mass(client, field, val):  # QA W5
    r = client.post("/api/upload", files=[("files", ("a.stl", b"solid x", "model/stl"))], data={field: val})
    assert r.status_code == 400 and r.json()["error"] == "invalid_mass"


def test_trusted_host(client):  # QA W10
    assert client.get("/api/health", headers={"Host": "evil.example.com"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "127.0.0.1:8000"}).status_code == 200


@pytest.mark.parametrize("method,path,host", [("get", "/api/health", "evil.example.com"),
                                              ("post", "/api/generate", "127.0.0.1.nip.io"),
                                              ("get", "/api/nope", "evil.example.com")])
def test_invalid_host_uses_error_format(client, method, path, host):  # QA N3
    r = getattr(client, method)(path, headers={"Host": host})
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["error"] == "invalid_host" and body["message"]
    # an app-level 400 on an allowed host is untouched
    r = client.post("/api/upload", files=[("files", ("a.stl", b"solid x", "model/stl"))], data={"mass": "nan"},
                    headers={"Host": "localhost"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_mass"
