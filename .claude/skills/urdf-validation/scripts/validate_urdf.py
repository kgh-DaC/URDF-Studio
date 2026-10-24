"""URDF 정적 검증. 사용: python -I validate_urdf.py robot.urdf [--mesh-root DIR]

app/validator.py와 같은 검사·메시지를 유지한다(앱 테스트가 두 출력을 비교함).
검사를 바꾸면 app/validator.py도 같이 바꾼다.
"""
import argparse
import math
import os
import sys
import xml.etree.ElementTree as ET

JOINT_TYPES = ("revolute", "continuous", "prismatic", "fixed", "floating", "planar")
LIMIT_KEYS = ("lower", "upper", "effort", "velocity")


def floats(s, n):
    try:
        v = [float(x) for x in s.split()]
        return v if len(v) == n and all(math.isfinite(x) for x in v) else None
    except ValueError:
        return None


def num(s):
    """유한한 float, 아니면 None (숫자 아님/nan/inf)."""
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urdf")
    ap.add_argument("--mesh-root")
    a = ap.parse_args()
    issues = []

    def add(sev, where, msg):
        issues.append((sev, where, msg))

    try:
        root = ET.parse(a.urdf).getroot()
    except ET.ParseError as e:
        print(f"error · {a.urdf} · XML 구문 오류: {e}")
        return 1
    if not root.get("name"):
        add("error", "robot", "robot name 누락")

    links = root.findall("link")
    joints = root.findall("joint")
    names = [l.get("name") for l in links]
    named = [n for n in names if n]  # 이름 없는 링크는 존재/루트/사이클 검사에서 제외
    jdisp = [j.get("name") or f"joint[{i}]" for i, j in enumerate(joints)]
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
        for role in ("parent", "child"):  # 요소/속성 누락은 따로 보고
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
                v = num(s)
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
            v = floats(ax.get("xyz", ""), 3)
            if not v or abs(sum(x * x for x in v) - 1) > 1e-3:
                add("warn", jn, "axis가 단위벡터가 아님")

    roots = [n for n in named if n not in children]
    if len(roots) != 1:
        add("error", "tree", f"루트 링크가 {len(roots)}개: {roots}")
    for n in named:  # 사이클 검사
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
            mv = 0.0 if m is None or m.get("value") is None else num(m.get("value"))
            if mv is None:
                add("error", ln, "질량 값이 숫자가 아님")
            elif mv <= 0:
                add("error", ln, "질량이 0 이하")
            ie = inertial.find("inertia")
            if ie is not None:
                diag = [num(ie.get(k, "0")) for k in ("ixx", "iyy", "izz")]
                off = [num(ie.get(k, "0")) for k in ("ixy", "ixz", "iyz")]
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
            if a.mesh_root and fn.startswith("package://"):
                rel = fn.split("/", 3)[-1] if fn.count("/") >= 3 else fn
                if not os.path.exists(os.path.join(a.mesh_root, rel)):
                    add("error", ln, f"메시 파일 없음: {fn}")

    errs = sum(1 for i in issues if i[0] == "error")
    print(f"{'FAIL' if errs else 'PASS'} · error {errs} · warn {len(issues) - errs}")
    for sev, where, msg in issues:
        print(f"{sev} · {where} · {msg}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
