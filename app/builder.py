"""RobotSpec (structure-spec JSON) <-> URDF conversion.

- build_urdf(spec): code assembles the URDF. Inertia comes from shape formulas
  (urdf-authoring section 3) and joint axes are normalized.
- check_spec(spec): finds structural defects before assembly (fed back to Claude).
- urdf_to_spec(xml): imports an existing URDF into the spec (used for modification requests).
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from typing import Callable, Optional

from schema import (BoxGeometry, CylinderGeometry, JointSpec, Limit, LinkSpec, MeshGeometry,
                    MeshProps, Origin, RobotSpec, SphereGeometry, MESH_FILE_RE)

MeshLookup = Callable[[str], Optional[MeshProps]]

PALETTE = [
    [0.80, 0.80, 0.82, 1.0], [0.20, 0.45, 0.80, 1.0], [0.90, 0.55, 0.15, 1.0],
    [0.25, 0.65, 0.35, 1.0], [0.60, 0.30, 0.70, 1.0], [0.85, 0.25, 0.25, 1.0],
]
VIRTUAL_INERTIA = 1e-6
DEFAULT_CONT_EFFORT = 10.0
DEFAULT_CONT_VELOCITY = 10.0


def package_name(robot_name: str) -> str:
    n = re.sub(r"[^a-z0-9_]", "_", robot_name.lower())
    if not re.match(r"^[a-z]", n):
        n = "robot_" + n
    return n + "_description"


# ---------------------------------------------------------------------------
# math helpers
# ---------------------------------------------------------------------------
def rpy_matrix(rpy):
    r, p, y = rpy
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]


def transform_point(origin: Origin, p):
    R = rpy_matrix(origin.rpy)
    return [origin.xyz[i] + sum(R[i][k] * p[k] for k in range(3)) for i in range(3)]


def box_inertia(m, x, y, z):
    return dict(ixx=m / 12 * (y * y + z * z), iyy=m / 12 * (x * x + z * z), izz=m / 12 * (x * x + y * y),
                ixy=0.0, ixz=0.0, iyz=0.0)


def cylinder_inertia(m, r, h):
    i = m / 12 * (3 * r * r + h * h)
    return dict(ixx=i, iyy=i, izz=m * r * r / 2, ixy=0.0, ixz=0.0, iyz=0.0)


def sphere_inertia(m, r):
    i = 2 / 5 * m * r * r
    return dict(ixx=i, iyy=i, izz=i, ixy=0.0, ixz=0.0, iyz=0.0)


def _f(v: float) -> str:
    if abs(v) < 1e-12:
        return "0"
    return f"{v:.9g}"


def _vec(v) -> str:
    return " ".join(_f(x) for x in v)


# ---------------------------------------------------------------------------
# spec checks
# ---------------------------------------------------------------------------
def check_spec(spec: RobotSpec, mesh_lookup: Optional[MeshLookup] = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) as plain strings to feed back to the LLM."""
    errors, warns = [], []
    lnames = [l.name for l in spec.links]
    jnames = [j.name for j in spec.joints]
    for n in sorted(set(lnames)):
        if lnames.count(n) > 1:
            errors.append(f"link '{n}': duplicate link name")
    for n in sorted(set(jnames)):
        if jnames.count(n) > 1:
            errors.append(f"joint '{n}': duplicate joint name")
    both = set(lnames) & set(jnames)
    for n in sorted(both):
        warns.append(f"'{n}' is used as both a link and a joint name")

    children = {}
    for j in spec.joints:
        for role, l in (("parent", j.parent), ("child", j.child)):
            if l not in lnames:
                errors.append(f"joint '{j.name}': {role} link '{l}' does not exist")
        if j.parent == j.child:
            errors.append(f"joint '{j.name}': parent and child are the same link")
        if j.child in children:
            errors.append(f"joint '{j.name}': link '{j.child}' already has parent joint '{children[j.child]}' "
                          f"(URDF must be a tree; closed loops are not allowed)")
        children[j.child] = j.name
        if j.type != "fixed":
            if j.axis is None or math.sqrt(sum(a * a for a in j.axis)) < 1e-9:
                errors.append(f"joint '{j.name}': {j.type} joint needs a non-zero axis")
        if j.type in ("revolute", "prismatic"):
            if j.limit is None or j.limit.lower is None or j.limit.upper is None:
                errors.append(f"joint '{j.name}': {j.type} joint requires limit.lower, limit.upper, "
                              f"limit.effort, limit.velocity")
            elif j.limit.lower >= j.limit.upper:
                errors.append(f"joint '{j.name}': limit.lower ({j.limit.lower}) must be < limit.upper "
                              f"({j.limit.upper})")

    roots = [n for n in lnames if n not in children]
    if len(roots) != 1:
        errors.append(f"tree: expected exactly one root link, found {len(roots)}: {roots}. "
                      f"Connect every link to base_link with a joint.")
    elif roots[0] != "base_link":
        warns.append(f"tree: root link is '{roots[0]}', convention is 'base_link'")
    parent_of = {j.child: j.parent for j in spec.joints}
    for n in lnames:
        seen, cur = set(), n
        while cur in parent_of:
            if cur in seen:
                errors.append(f"link '{n}': joint cycle detected")
                break
            seen.add(cur)
            cur = parent_of[cur]

    for l in spec.links:
        for g in (l.geometry, l.collision):
            if isinstance(g, MeshGeometry):
                if mesh_lookup is None or mesh_lookup(g.mesh_file) is None:
                    errors.append(f"link '{l.name}': mesh_file '{g.mesh_file}' is not an uploaded mesh. "
                                  f"Use one of the provided stored_name values or a primitive.")
    return errors, warns


# ---------------------------------------------------------------------------
# inertia
# ---------------------------------------------------------------------------
def _mesh_scale(g: MeshGeometry, props: MeshProps) -> list[float]:
    if g.scale:
        return list(g.scale)
    s = props.scale_to_m or 1.0
    return [s, s, s]


def link_inertial(link: LinkSpec, mesh_lookup: Optional[MeshLookup], notes: list[str]):
    """Return (origin: Origin, inertia dict). Uses visual geometry; mass from spec."""
    g, m, vo = link.geometry, link.mass, link.visual_origin
    if g is None:
        i = VIRTUAL_INERTIA
        return Origin(), dict(ixx=i, iyy=i, izz=i, ixy=0.0, ixz=0.0, iyz=0.0)
    if isinstance(g, BoxGeometry):
        return vo, box_inertia(m, *g.size)
    if isinstance(g, CylinderGeometry):
        return vo, cylinder_inertia(m, g.radius, g.length)
    if isinstance(g, SphereGeometry):
        return vo, sphere_inertia(m, g.radius)
    # mesh
    props = mesh_lookup(g.mesh_file) if mesh_lookup else None
    if props is None or props.status != "ok":
        notes.append(f"{link.name}: mesh props unavailable, used 0.1 m box inertia")
        return vo, box_inertia(m, 0.1, 0.1, 0.1)
    s = _mesh_scale(g, props)
    s0 = props.scale_to_m or 1.0
    k = [si / s0 for si in s]
    com = [c * ki for c, ki in zip(props.com_m or [0, 0, 0], k)]
    origin = Origin(xyz=transform_point(vo, com), rpy=list(vo.rpy))
    if max(k) - min(k) < 1e-9 and props.inertia and props.mass_kg:
        ratio = m / props.mass_kg * k[0] ** 2
        return origin, {key: val * ratio for key, val in props.inertia.items()}
    bx = [b * ki for b, ki in zip(props.bbox_m or [0.1, 0.1, 0.1], k)]
    notes.append(f"{link.name}: non-uniform mesh scale, inertia approximated by bounding box")
    return origin, box_inertia(m, *bx)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def _geom_xml(parent: ET.Element, g, pkg: str, mesh_lookup: Optional[MeshLookup]):
    ge = ET.SubElement(parent, "geometry")
    if isinstance(g, BoxGeometry):
        ET.SubElement(ge, "box", size=_vec(g.size))
    elif isinstance(g, CylinderGeometry):
        ET.SubElement(ge, "cylinder", radius=_f(g.radius), length=_f(g.length))
    elif isinstance(g, SphereGeometry):
        ET.SubElement(ge, "sphere", radius=_f(g.radius))
    elif isinstance(g, MeshGeometry):
        props = mesh_lookup(g.mesh_file) if mesh_lookup else None
        scale = _mesh_scale(g, props) if props else (g.scale or [1, 1, 1])
        attrs = {"filename": f"package://{pkg}/meshes/{g.mesh_file}"}
        if any(abs(s - 1) > 1e-12 for s in scale):
            attrs["scale"] = _vec(scale)
        ET.SubElement(ge, "mesh", **attrs)


def _origin_xml(parent: ET.Element, o: Origin):
    ET.SubElement(parent, "origin", xyz=_vec(o.xyz), rpy=_vec(o.rpy))


def _collision_for(link: LinkSpec, mesh_lookup: Optional[MeshLookup], notes: list[str]):
    """Return (geometry, origin) for collision. Mesh visuals get a bounding-box collision."""
    if link.collision is not None:
        return link.collision, link.collision_origin or link.visual_origin
    g = link.geometry
    if isinstance(g, MeshGeometry):
        props = mesh_lookup(g.mesh_file) if mesh_lookup else None
        if props and props.status == "ok" and props.bbox_m:
            s = _mesh_scale(g, props)
            k = [si / (props.scale_to_m or 1.0) for si in s]
            size = [max(b * ki, 1e-4) for b, ki in zip(props.bbox_m, k)]
            ctr = [c * ki for c, ki in zip(props.bbox_center_m or [0, 0, 0], k)]
            notes.append(f"{link.name}: collision = bounding box {_vec(size)} m of {g.mesh_file}")
            return BoxGeometry(type="box", size=size), Origin(xyz=transform_point(link.visual_origin, ctr),
                                                              rpy=list(link.visual_origin.rpy))
        return None, None
    return g, link.visual_origin


def build_urdf(spec: RobotSpec, mesh_lookup: Optional[MeshLookup] = None) -> tuple[str, list[str]]:
    """Assemble URDF from spec. Returns (urdf_xml, notes). notes are code-made assumptions."""
    notes: list[str] = []
    pkg = package_name(spec.robot_name)
    robot = ET.Element("robot", name=spec.robot_name)

    for idx, link in enumerate(spec.links):
        le = ET.SubElement(robot, "link", name=link.name)
        if link.geometry is not None:
            ve = ET.SubElement(le, "visual")
            _origin_xml(ve, link.visual_origin)
            _geom_xml(ve, link.geometry, pkg, mesh_lookup)
            rgba = link.color or PALETTE[idx % len(PALETTE)]
            me = ET.SubElement(ve, "material", name=f"{link.name}_material")
            ET.SubElement(me, "color", rgba=_vec(rgba))
            cg, co = _collision_for(link, mesh_lookup, notes)
            if cg is not None:
                ce = ET.SubElement(le, "collision")
                _origin_xml(ce, co)
                _geom_xml(ce, cg, pkg, mesh_lookup)
        io, inertia = link_inertial(link, mesh_lookup, notes)
        ie = ET.SubElement(le, "inertial")
        _origin_xml(ie, io)
        ET.SubElement(ie, "mass", value=_f(link.mass))
        ET.SubElement(ie, "inertia", **{k: _f(inertia[k]) for k in ("ixx", "ixy", "ixz", "iyy", "iyz", "izz")})

    for j in spec.joints:
        je = ET.SubElement(robot, "joint", name=j.name, type=j.type)
        ET.SubElement(je, "parent", link=j.parent)
        ET.SubElement(je, "child", link=j.child)
        _origin_xml(je, j.origin)
        if j.type == "fixed":
            continue
        ax = j.axis or [0, 0, 1]
        n = math.sqrt(sum(a * a for a in ax)) or 1.0
        ET.SubElement(je, "axis", xyz=_vec([a / n for a in ax]))
        lim = j.limit
        if j.type == "continuous":
            if lim is None:
                lim = Limit(effort=DEFAULT_CONT_EFFORT, velocity=DEFAULT_CONT_VELOCITY)
                notes.append(f"{j.name}: continuous limit defaulted to effort={DEFAULT_CONT_EFFORT}, "
                             f"velocity={DEFAULT_CONT_VELOCITY}")
            ET.SubElement(je, "limit", effort=_f(lim.effort), velocity=_f(lim.velocity))
        elif lim is not None:
            attrs = {"effort": _f(lim.effort), "velocity": _f(lim.velocity)}
            if lim.lower is not None:
                attrs["lower"] = _f(lim.lower)
            if lim.upper is not None:
                attrs["upper"] = _f(lim.upper)
            ET.SubElement(je, "limit", **attrs)

    ET.indent(robot, space="  ")
    xml = '<?xml version="1.0"?>\n' + ET.tostring(robot, encoding="unicode") + "\n"
    return xml, notes


# ---------------------------------------------------------------------------
# architect spec (_workspace/01_architect_spec.json) -> RobotSpec
# ---------------------------------------------------------------------------
_AXIS_RPY = {"z": [0.0, 0.0, 0.0], "y": [math.pi / 2, 0.0, 0.0], "x": [0.0, math.pi / 2, 0.0]}


def architect_to_spec(d: dict) -> tuple[RobotSpec, list[dict]]:
    """Convert the earlier urdf-architect output format to RobotSpec. Compatibility only.

    The standard spec is schema.RobotSpec (QA W11 decision); new output should use RobotSpec directly.
    Differences handled: `robot` -> robot_name; cylinder `geometry.axis` ("x"|"y"|"z") ->
    visual_origin rpy; `inertial_origin` -> visual_origin xyz (geometry center);
    precomputed `inertia` is dropped (the builder recomputes it) and is returned
    for comparison as [{link, given, computed}]. `computed` is the full tensor
    (ixx..iyz) in the link frame, after rotation by the inertial rpy.
    An unsupported axis value raises ValueError (instead of KeyError).
    Input that is already RobotSpec (`robot_name` or any link `visual_origin`) raises ValueError:
    this converter would silently drop visual_origin; use RobotSpec.model_validate instead.
    """
    if "robot_name" in d or any(isinstance(l, dict) and "visual_origin" in l for l in d.get("links") or []):
        raise ValueError("input is already RobotSpec format (robot_name/visual_origin); "
                         "use RobotSpec.model_validate instead of architect_to_spec")
    links, given = [], []
    for l in d["links"]:
        g = dict(l.get("geometry") or {}) or None
        rpy = [0.0, 0.0, 0.0]
        if g and g.get("type") == "cylinder":
            ax = g.pop("axis", "z")
            key = ax.strip().lower() if isinstance(ax, str) else None
            if key not in _AXIS_RPY:
                raise ValueError(f"link '{l.get('name')}': cylinder geometry.axis must be 'x', 'y' or 'z' "
                                 f"(got {ax!r}); use RobotSpec visual_origin.rpy for other orientations")
            rpy = list(_AXIS_RPY[key])
        xyz = list(l.get("inertial_origin") or [0.0, 0.0, 0.0])
        links.append(LinkSpec.model_validate({
            "name": l["name"], "geometry": g, "mass": l["mass"],
            "visual_origin": {"xyz": xyz, "rpy": rpy}, **({"color": l["color"]} if l.get("color") else {}),
        }))
        if l.get("inertia"):
            given.append({"link": l["name"], "given": l["inertia"]})
    spec = RobotSpec(robot_name=d.get("robot") or "robot", links=links,
                     joints=[JointSpec.model_validate(j) for j in d.get("joints", [])],
                     assumptions=list(d.get("assumptions", [])))
    for row in given:
        link = next(x for x in spec.links if x.name == row["link"])
        origin, comp = link_inertial(link, None, [])
        row["computed"] = inertia_in_parent(comp, origin.rpy)
    return spec, given


def inertia_in_parent(i: dict, rpy) -> dict:
    """R · I · Rᵀ: express a tensor given in the inertial frame (rotated by rpy) in the link frame."""
    I = [[i["ixx"], i["ixy"], i["ixz"]], [i["ixy"], i["iyy"], i["iyz"]], [i["ixz"], i["iyz"], i["izz"]]]
    R = rpy_matrix(rpy)
    RI = [[sum(R[a][k] * I[k][b] for k in range(3)) for b in range(3)] for a in range(3)]
    M = [[sum(RI[a][k] * R[b][k] for k in range(3)) for b in range(3)] for a in range(3)]
    return dict(ixx=M[0][0], iyy=M[1][1], izz=M[2][2], ixy=M[0][1], ixz=M[0][2], iyz=M[1][2])


# ---------------------------------------------------------------------------
# import existing URDF -> spec (for modification requests)
# ---------------------------------------------------------------------------
def _origin_of(el: Optional[ET.Element]) -> Origin:
    if el is None:
        return Origin()
    o = el.find("origin")
    if o is None:
        return Origin()

    def v(attr):
        try:
            vals = [float(x) for x in (o.get(attr) or "0 0 0").split()]
            return vals if len(vals) == 3 else [0.0, 0.0, 0.0]
        except ValueError:
            return [0.0, 0.0, 0.0]

    return Origin(xyz=v("xyz"), rpy=v("rpy"))


def _geom_of(el: Optional[ET.Element], mesh_lookup: Optional[MeshLookup], dropped: list[str], where: str):
    if el is None or el.find("geometry") is None:
        return None
    g = el.find("geometry")
    try:
        if g.find("box") is not None:
            return BoxGeometry(type="box", size=[float(x) for x in g.find("box").get("size", "").split()])
        if g.find("cylinder") is not None:
            c = g.find("cylinder")
            return CylinderGeometry(type="cylinder", radius=float(c.get("radius")), length=float(c.get("length")))
        if g.find("sphere") is not None:
            return SphereGeometry(type="sphere", radius=float(g.find("sphere").get("radius")))
        if g.find("mesh") is not None:
            m = g.find("mesh")
            fn = (m.get("filename") or "").rsplit("/", 1)[-1]
            scale = [float(x) for x in m.get("scale").split()] if m.get("scale") else None
            if re.fullmatch(MESH_FILE_RE, fn) and mesh_lookup and mesh_lookup(fn) is not None:
                return MeshGeometry(type="mesh", mesh_file=fn, scale=scale)
            dropped.append(f"{where}: mesh '{m.get('filename')}' is not uploaded; geometry dropped")
            return None
    except (TypeError, ValueError) as e:
        dropped.append(f"{where}: unreadable geometry ({e}); dropped")
    return None


def urdf_to_spec(urdf_text: str, mesh_lookup: Optional[MeshLookup] = None) -> tuple[RobotSpec, list[str]]:
    """Best-effort import. Returns (spec, dropped_notes). Raises ValueError on unusable input."""
    try:
        root = ET.fromstring(urdf_text)
    except ET.ParseError as e:
        raise ValueError(f"XML 구문 오류: {e}") from e
    if root.tag != "robot":
        raise ValueError("루트 요소가 <robot>이 아님")
    dropped: list[str] = []
    known = {"link", "joint", "material"}
    for child in root:
        if child.tag not in known:
            dropped.append(f"top-level <{child.tag}> not representable in spec; dropped")
    materials = {}
    for m in root.findall("material"):
        c = m.find("color")
        if c is not None and m.get("name"):
            materials[m.get("name")] = c.get("rgba")

    links = []
    for l in root.findall("link"):
        name = l.get("name") or "unnamed"
        vis, col, ine = l.find("visual"), l.find("collision"), l.find("inertial")
        if len(l.findall("visual")) > 1 or len(l.findall("collision")) > 1:
            dropped.append(f"{name}: only the first visual/collision is kept")
        color = None
        if vis is not None and vis.find("material") is not None:
            me = vis.find("material")
            rgba = me.find("color").get("rgba") if me.find("color") is not None else materials.get(me.get("name"))
            try:
                color = [float(x) for x in rgba.split()] if rgba else None
                if color and len(color) != 4:
                    color = None
            except ValueError:
                color = None
        mass = 1e-3
        if ine is not None and ine.find("mass") is not None:
            try:
                mass = float(ine.find("mass").get("value"))
            except (TypeError, ValueError):
                pass
        if mass <= 0:
            dropped.append(f"{name}: non-positive mass {mass} replaced by 0.001 kg")
            mass = 1e-3
        if ine is None:
            dropped.append(f"{name}: no inertial; mass set to 0.001 kg")
        geom = _geom_of(vis, mesh_lookup, dropped, name)
        cgeom = _geom_of(col, mesh_lookup, dropped, name + " collision")
        links.append(LinkSpec(name=name, geometry=geom, visual_origin=_origin_of(vis),
                              collision=cgeom, collision_origin=_origin_of(col) if cgeom else None,
                              mass=mass, color=color))

    joints = []
    for j in root.findall("joint"):
        name, jt = j.get("name") or "unnamed_joint", j.get("type")
        if jt not in ("fixed", "revolute", "continuous", "prismatic"):
            dropped.append(f"{name}: joint type '{jt}' not supported by spec; converted to fixed")
            jt = "fixed"
        for extra in ("mimic", "dynamics", "safety_controller", "calibration"):
            if j.find(extra) is not None:
                dropped.append(f"{name}: <{extra}> dropped")
        axis = None
        if j.find("axis") is not None:
            try:
                axis = [float(x) for x in j.find("axis").get("xyz", "1 0 0").split()]
                if len(axis) != 3:
                    axis = None
            except ValueError:
                axis = None
        if jt != "fixed" and axis is None:
            axis = [1.0, 0.0, 0.0]  # URDF default axis
        limit = None
        le = j.find("limit")
        if le is not None:
            def num(k, default=None):
                try:
                    return float(le.get(k)) if le.get(k) is not None else default
                except ValueError:
                    return default
            eff, vel = num("effort", 0.0), num("velocity", 0.0)
            limit = Limit(lower=num("lower"), upper=num("upper"),
                          effort=eff if eff > 0 else 1.0, velocity=vel if vel > 0 else 1.0)
        p = j.find("parent").get("link") if j.find("parent") is not None else "missing"
        c = j.find("child").get("link") if j.find("child") is not None else "missing"
        joints.append(JointSpec(name=name, type=jt, parent=p or "missing", child=c or "missing",
                                origin=_origin_of(j), axis=axis, limit=limit))

    if not links:
        raise ValueError("링크가 없음")
    dropped.append("all inertia tensors are recomputed from geometry by the builder (original values discarded)")
    spec = RobotSpec(robot_name=root.get("name") or "robot", links=links, joints=joints)
    return spec, dropped
