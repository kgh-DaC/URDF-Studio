"""URDF static validation.

A function-form port of `.claude/skills/urdf-validation/scripts/validate_urdf.py`.
Its checks and messages match the script exactly. In tests/test_app.py,
`test_validator_matches_skill_script` covers the samples and
`test_validator_parity_edge_cases` covers edge inputs such as NaN, empty limits,
and bad types. Additions beyond the script:
- the input is a string, and the result is structured (schema.ValidationResult)
- a suggested fix (suggestion) and a link to highlight in the viewer (link)
- a check that the root element is <robot>
- a warning for mesh paths that are not package:// (W3)
When you change the checks, update the skill script the same way.
"""
from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from typing import Optional

from schema import Issue, ValidationResult

JOINT_TYPES = ("revolute", "continuous", "prismatic", "fixed", "floating", "planar")
LIMIT_KEYS = ("lower", "upper", "effort", "velocity")

# The first matching key wins, so more specific keys come first.
SUGGEST = [
    ("XML 구문 오류", "태그 짝·따옴표·특수문자(&, <)를 확인하세요."),
    ("루트 요소", "최상위 요소를 <robot name=\"...\">로 감싸세요."),
    ("robot name 누락", "<robot name=\"my_robot\">처럼 이름을 지정하세요."),
    ("링크 name 누락", "<link name=\"...\">에 유일한 이름을 지정하세요."),
    ("조인트 name 누락", "<joint name=\"...\">에 유일한 이름을 지정하세요."),
    ("조인트 type 누락", "type을 revolute/continuous/prismatic/fixed/floating/planar 중 하나로 지정하세요."),
    ("알 수 없는 조인트 type", "type을 revolute/continuous/prismatic/fixed/floating/planar 중 하나로 지정하세요."),
    ("중복된 링크 이름", "링크 이름을 전체에서 유일하게 바꾸세요."),
    ("중복된 조인트 이름", "조인트 이름을 <부모>_to_<자식>_joint 형식 등으로 유일하게 바꾸세요."),
    ("요소 누락", "조인트에 <parent link=\"...\"/>와 <child link=\"...\"/>를 모두 넣으세요."),
    ("link 속성 누락", "<parent>/<child>의 link 속성에 실제 <link name>을 지정하세요."),
    ("가 존재하지 않음", "조인트의 parent/child를 실제 <link name>과 일치시키거나 링크를 추가하세요."),
    ("부모를 둘 이상", "링크당 부모 조인트는 하나만 허용됩니다. 폐루프는 URDF에서 지원하지 않습니다."),
    ("관성 값이 숫자가 아님", "inertia 속성에 유한한 숫자를 넣으세요(nan/inf 불가)."),
    ("질량 값이 숫자가 아님", "mass value에 유한한 양수를 넣으세요(nan/inf 불가)."),
    ("값이 숫자가 아님", "limit 속성에 유한한 숫자를 넣으세요(nan/inf 불가)."),
    ("가 음수", "effort와 velocity는 0 이상이어야 합니다."),
    ("limit 누락", "<limit lower=\"..\" upper=\"..\" effort=\"..\" velocity=\"..\"/>를 추가하세요."),
    ("limit/", "누락된 limit 속성(lower/upper/effort/velocity)을 채우세요."),
    ("lower >= upper", "lower < upper가 되도록 범위를 고치세요."),
    ("continuous 조인트", "<limit effort=\"..\" velocity=\"..\"/>를 추가하세요."),
    ("단위벡터", "axis xyz를 길이 1로 정규화하세요(예: 0 0 1)."),
    ("루트 링크가", "base_link 하나만 루트가 되도록 고립된 링크를 조인트로 연결하세요."),
    ("조인트 사이클", "사이클을 이루는 조인트 하나를 제거하세요."),
    ("inertial 없음", "형상 공식으로 계산한 <inertial>을 추가하세요."),
    ("질량이 0 이하", "양의 질량을 주세요(가상 링크는 1e-3 kg 정도)."),
    ("관성 대각 성분", "형상 공식(박스/원기둥/구)으로 ixx, iyy, izz를 다시 계산하세요."),
    ("삼각부등식", "ixx+iyy>=izz 등을 만족하도록 형상 공식으로 다시 계산하세요."),
    ("메시 파일 없음", "메시를 /api/upload로 올리거나 filename을 업로드된 이름과 맞추세요."),
    ("package://가 아닌 메시 경로", "package://<pkg>/meshes/<file> 형식을 쓰세요(ROS 2에서 file://·상대경로는 환경마다 깨짐)."),
]


def _suggest(msg: str) -> str:
    for key, s in SUGGEST:
        if key in msg:
            return s
    return ""


def _floats(s, n):
    try:
        v = [float(x) for x in s.split()]
        return v if len(v) == n and all(math.isfinite(x) for x in v) else None
    except ValueError:
        return None


def _num(s) -> Optional[float]:
    """Finite float, or None (not a number / nan / inf)."""
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def validate_urdf(urdf_text: str, mesh_root: Optional[str] = None) -> ValidationResult:
    """Validate a URDF string. With mesh_root, package://pkg/<rel> resolves to mesh_root/<rel>."""
    issues: list[Issue] = []
    link_names: set[str] = set()
    joint_child: dict[str, str] = {}

    def add(sev, where, msg):
        where = "" if where is None else str(where)
        link = where if where in link_names else joint_child.get(where)
        issues.append(Issue(severity=sev, where=where, message=msg, suggestion=_suggest(msg), link=link))

    try:
        root = ET.fromstring(urdf_text)
    except ET.ParseError as e:
        add("error", "xml", f"XML 구문 오류: {e}")
        return _result(issues)
    if root.tag != "robot":
        add("error", "xml", f"루트 요소가 <robot>이 아님: <{root.tag}>")
        return _result(issues)
    if not root.get("name"):
        add("error", "robot", "robot name 누락")

    links = root.findall("link")
    joints = root.findall("joint")
    names = [l.get("name") for l in links]
    named = [n for n in names if n]  # QA N2: unnamed links never enter existence/root/cycle checks
    link_names.update(named)
    jdisp = [j.get("name") or f"joint[{i}]" for i, j in enumerate(joints)]
    for jn, j in zip(jdisp, joints):
        c = j.find("child")
        if c is not None:
            joint_child[jn] = c.get("link")

    for i, n in enumerate(names):
        if not n:
            add("error", f"link[{i}]", "링크 name 누락")
    for n in sorted({n for n in names if n}):
        if names.count(n) > 1:
            add("error", n, "중복된 링크 이름")
    jnames = [j.get("name") for j in joints]
    for n in sorted({n for n in jnames if n}):
        if jnames.count(n) > 1:
            add("error", n, "중복된 조인트 이름")

    children, parent_of = set(), {}
    for jn, j in zip(jdisp, joints):
        jt = j.get("type")
        if not j.get("name"):
            add("error", jn, "조인트 name 누락")
        if not jt:
            add("error", jn, "조인트 type 누락")
        elif jt not in JOINT_TYPES:
            add("error", jn, f"알 수 없는 조인트 type '{jt}'")
        ends = {}
        for role in ("parent", "child"):  # QA N2: missing element/attribute reported separately
            el = j.find(role)
            ends[role] = el.get("link") if el is not None else None
            if el is None:
                add("error", jn, f"{role} 요소 누락")
            elif not ends[role]:
                add("error", jn, f"{role} link 속성 누락")
            elif ends[role] not in named:
                add("error", jn, f"{role} 링크 '{ends[role]}'가 존재하지 않음")
        p, c = ends["parent"], ends["child"]
        if c:
            if c in children:
                add("error", jn, f"링크 '{c}'가 부모를 둘 이상 가짐")
            children.add(c)
            if p:
                parent_of[c] = p
        lim = j.find("limit")
        if jt in ("revolute", "prismatic"):
            if lim is None:
                add("error", jn, "limit 누락")
            else:
                for k in LIMIT_KEYS:
                    if lim.get(k) in (None, ""):
                        add("error", jn, f"limit/{k} 누락")
        if lim is not None:
            vals = {}
            for k in LIMIT_KEYS:
                s = lim.get(k)
                if s in (None, ""):
                    continue
                v = _num(s)
                if v is None:
                    add("error", jn, f"limit/{k} 값이 숫자가 아님")
                else:
                    vals[k] = v
            for k in ("effort", "velocity"):
                if k in vals and vals[k] < 0:
                    add("error", jn, f"limit/{k}가 음수")
            if "lower" in vals and "upper" in vals and vals["lower"] >= vals["upper"]:
                add("error", jn, "lower >= upper")
        if jt == "continuous" and lim is None:
            add("warn", jn, "continuous 조인트에 effort/velocity limit 없음")
        ax = j.find("axis")
        if jt != "fixed" and ax is not None:
            v = _floats(ax.get("xyz", ""), 3)
            if not v or abs(sum(x * x for x in v) - 1) > 1e-3:
                add("warn", jn, "axis가 단위벡터가 아님")

    roots = [n for n in named if n not in children]
    if len(roots) != 1:
        add("error", "tree", f"루트 링크가 {len(roots)}개: {roots}")
    for n in named:  # cycle check
        seen, cur = set(), n
        while cur in parent_of:
            if cur in seen:
                add("error", n, "조인트 사이클")
                break
            seen.add(cur)
            cur = parent_of[cur]

    for i, l in enumerate(links):
        ln = l.get("name") or f"link[{i}]"
        inertial = l.find("inertial")
        if inertial is None:
            if len(roots) == 1 and ln != "world":
                add("warn", ln, "inertial 없음 (시뮬레이션에서 문제 가능)")
        else:
            m = inertial.find("mass")
            mv = 0.0 if m is None or m.get("value") is None else _num(m.get("value"))
            if mv is None:
                add("error", ln, "질량 값이 숫자가 아님")
            elif mv <= 0:
                add("error", ln, "질량이 0 이하")
            ie = inertial.find("inertia")
            if ie is not None:
                diag = [_num(ie.get(k, "0")) for k in ("ixx", "iyy", "izz")]
                off = [_num(ie.get(k, "0")) for k in ("ixy", "ixz", "iyz")]  # QA N1
                if any(v is None for v in diag + off):
                    add("error", ln, "관성 값이 숫자가 아님")
                else:
                    ixx, iyy, izz = diag
                    if min(ixx, iyy, izz) <= 0:
                        add("error", ln, "관성 대각 성분이 0 이하")
                    elif ixx + iyy < izz or ixx + izz < iyy or iyy + izz < ixx:
                        add("error", ln, "관성 삼각부등식 위반")
        for mesh in l.iter("mesh"):
            fn = mesh.get("filename", "")
            if not fn.startswith("package://"):
                add("warn", ln, f"package://가 아닌 메시 경로: {fn or '(빈 값)'}")
            elif mesh_root:
                rel = fn.split("/", 3)[-1] if fn.count("/") >= 3 else fn
                full = os.path.realpath(os.path.join(mesh_root, rel))
                inside = full.startswith(os.path.realpath(mesh_root) + os.sep)
                if not inside or not os.path.exists(full):
                    add("error", ln, f"메시 파일 없음: {fn}")

    return _result(issues)


def _result(issues: list[Issue]) -> ValidationResult:
    errs = sum(1 for i in issues if i.severity == "error")
    warns = len(issues) - errs
    return ValidationResult(
        ok=errs == 0,
        summary=f"{'FAIL' if errs else 'PASS'} · error {errs} · warn {warns}",
        errors=errs, warnings=warns, issues=issues,
    )


def format_report(r: ValidationResult) -> str:
    """Same text format as the original script: summary first, then `sev · where · msg`."""
    lines = [r.summary] + [f"{i.severity} · {i.where} · {i.message}" for i in r.issues]
    return "\n".join(lines)
