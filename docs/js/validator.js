// URDF 정적 검증 (app/validator.py 의 브라우저용 포트).
// 검사 항목과 메시지는 Python 판과 같다. 바꿀 때는 app/validator.py, 스킬 스크립트도 함께 바꾼다.
// 결과 형식: { ok, summary, errors, warnings, issues: [{severity, where, message, suggestion, link}] }

const JOINT_TYPES = ['revolute', 'continuous', 'prismatic', 'fixed', 'floating', 'planar'];
const LIMIT_KEYS = ['lower', 'upper', 'effort', 'velocity'];

// 먼저 일치한 항목이 이긴다(구체적인 키가 앞).
const SUGGEST = [
  ['XML 구문 오류', '태그 짝·따옴표·특수문자(&, <)를 확인하세요.'],
  ['루트 요소', '최상위 요소를 <robot name="...">로 감싸세요.'],
  ['robot name 누락', '<robot name="my_robot">처럼 이름을 지정하세요.'],
  ['링크 name 누락', '<link name="...">에 유일한 이름을 지정하세요.'],
  ['조인트 name 누락', '<joint name="...">에 유일한 이름을 지정하세요.'],
  ['조인트 type 누락', 'type을 revolute/continuous/prismatic/fixed/floating/planar 중 하나로 지정하세요.'],
  ['알 수 없는 조인트 type', 'type을 revolute/continuous/prismatic/fixed/floating/planar 중 하나로 지정하세요.'],
  ['중복된 링크 이름', '링크 이름을 전체에서 유일하게 바꾸세요.'],
  ['중복된 조인트 이름', '조인트 이름을 <부모>_to_<자식>_joint 형식 등으로 유일하게 바꾸세요.'],
  ['요소 누락', '조인트에 <parent link="..."/>와 <child link="..."/>를 모두 넣으세요.'],
  ['link 속성 누락', '<parent>/<child>의 link 속성에 실제 <link name>을 지정하세요.'],
  ['가 존재하지 않음', '조인트의 parent/child를 실제 <link name>과 일치시키거나 링크를 추가하세요.'],
  ['부모를 둘 이상', '링크당 부모 조인트는 하나만 허용됩니다. 폐루프는 URDF에서 지원하지 않습니다.'],
  ['관성 값이 숫자가 아님', 'inertia 속성에 유한한 숫자를 넣으세요(nan/inf 불가).'],
  ['질량 값이 숫자가 아님', 'mass value에 유한한 양수를 넣으세요(nan/inf 불가).'],
  ['값이 숫자가 아님', 'limit 속성에 유한한 숫자를 넣으세요(nan/inf 불가).'],
  ['가 음수', 'effort와 velocity는 0 이상이어야 합니다.'],
  ['limit 누락', '<limit lower=".." upper=".." effort=".." velocity=".."/>를 추가하세요.'],
  ['limit/', '누락된 limit 속성(lower/upper/effort/velocity)을 채우세요.'],
  ['lower >= upper', 'lower < upper가 되도록 범위를 고치세요.'],
  ['continuous 조인트', '<limit effort=".." velocity=".."/>를 추가하세요.'],
  ['단위벡터', 'axis xyz를 길이 1로 정규화하세요(예: 0 0 1).'],
  ['루트 링크가', 'base_link 하나만 루트가 되도록 고립된 링크를 조인트로 연결하세요.'],
  ['조인트 사이클', '사이클을 이루는 조인트 하나를 제거하세요.'],
  ['inertial 없음', '형상 공식으로 계산한 <inertial>을 추가하세요.'],
  ['질량이 0 이하', '양의 질량을 주세요(가상 링크는 1e-3 kg 정도).'],
  ['관성 대각 성분', '형상 공식(박스/원기둥/구)으로 ixx, iyy, izz를 다시 계산하세요.'],
  ['삼각부등식', 'ixx+iyy>=izz 등을 만족하도록 형상 공식으로 다시 계산하세요.'],
  ['메시 파일 없음', '왼쪽에서 메시를 업로드하거나 filename을 업로드한 이름과 맞추세요.'],
  ['package://가 아닌 메시 경로', 'package://<pkg>/meshes/<file> 형식을 쓰세요(ROS 2에서 file://·상대경로는 환경마다 깨짐).'],
];

const suggest = (msg) => (SUGGEST.find(([k]) => msg.includes(k)) || [, ''])[1];

const NUM_RE = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;
// 유한한 숫자면 number, 아니면 null (빈 문자열·nan·inf 포함)
function num(s) {
  if (s === null || s === undefined) return null;
  const t = String(s).trim();
  if (!NUM_RE.test(t)) return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
}
function floats(s, n) {
  const parts = String(s).trim().split(/\s+/).filter(Boolean);
  const v = parts.map(num);
  return parts.length === n && v.every((x) => x !== null) ? v : null;
}

const kids = (el, tag) => [...el.children].filter((c) => c.localName === tag);
const kid = (el, tag) => kids(el, tag)[0] || null;
const attr = (el, k) => (el.hasAttribute(k) ? el.getAttribute(k) : null);

/**
 * @param {string} text URDF 문자열
 * @param {Set<string>|null} meshNames 업로드된 메시 파일명 집합. null 이면 메시 존재 검사를 건너뛴다.
 */
export function validateUrdf(text, meshNames = null) {
  const issues = [];
  const linkNames = new Set();
  const jointChild = new Map();

  const add = (severity, where, message) => {
    where = where == null ? '' : String(where);
    const link = linkNames.has(where) ? where : (jointChild.get(where) ?? null);
    issues.push({ severity, where, message, suggestion: suggest(message), link });
  };

  const doc = new DOMParser().parseFromString(text, 'text/xml');
  const perr = doc.querySelector('parsererror');
  if (perr) {
    add('error', 'xml', `XML 구문 오류: ${perr.textContent.trim().split('\n')[0]}`);
    return result(issues);
  }
  const root = doc.documentElement;
  if (root.localName !== 'robot') {
    add('error', 'xml', `루트 요소가 <robot>이 아님: <${root.localName}>`);
    return result(issues);
  }
  if (!attr(root, 'name')) add('error', 'robot', 'robot name 누락');

  const links = kids(root, 'link');
  const joints = kids(root, 'joint');
  const names = links.map((l) => attr(l, 'name'));
  const named = names.filter((n) => n);
  named.forEach((n) => linkNames.add(n));
  const jdisp = joints.map((j, i) => attr(j, 'name') || `joint[${i}]`);
  joints.forEach((j, i) => {
    const c = kid(j, 'child');
    if (c) jointChild.set(jdisp[i], attr(c, 'link'));
  });

  names.forEach((n, i) => { if (!n) add('error', `link[${i}]`, '링크 name 누락'); });
  [...new Set(named)].sort().forEach((n) => {
    if (names.filter((x) => x === n).length > 1) add('error', n, '중복된 링크 이름');
  });
  const jnames = joints.map((j) => attr(j, 'name'));
  [...new Set(jnames.filter((n) => n))].sort().forEach((n) => {
    if (jnames.filter((x) => x === n).length > 1) add('error', n, '중복된 조인트 이름');
  });

  const children = new Set();
  const parentOf = new Map();
  joints.forEach((j, idx) => {
    const jn = jdisp[idx];
    const jt = attr(j, 'type');
    if (!attr(j, 'name')) add('error', jn, '조인트 name 누락');
    if (!jt) add('error', jn, '조인트 type 누락');
    else if (!JOINT_TYPES.includes(jt)) add('error', jn, `알 수 없는 조인트 type '${jt}'`);
    const ends = {};
    for (const role of ['parent', 'child']) {
      const el = kid(j, role);
      ends[role] = el ? attr(el, 'link') : null;
      if (!el) add('error', jn, `${role} 요소 누락`);
      else if (!ends[role]) add('error', jn, `${role} link 속성 누락`);
      else if (!named.includes(ends[role])) add('error', jn, `${role} 링크 '${ends[role]}'가 존재하지 않음`);
    }
    const p = ends.parent, c = ends.child;
    if (c) {
      if (children.has(c)) add('error', jn, `링크 '${c}'가 부모를 둘 이상 가짐`);
      children.add(c);
      if (p) parentOf.set(c, p);
    }
    const lim = kid(j, 'limit');
    if (jt === 'revolute' || jt === 'prismatic') {
      if (!lim) add('error', jn, 'limit 누락');
      else for (const k of LIMIT_KEYS) {
        const v = attr(lim, k);
        if (v === null || v === '') add('error', jn, `limit/${k} 누락`);
      }
    }
    if (lim) {
      const vals = {};
      for (const k of LIMIT_KEYS) {
        const s = attr(lim, k);
        if (s === null || s === '') continue;
        const v = num(s);
        if (v === null) add('error', jn, `limit/${k} 값이 숫자가 아님`);
        else vals[k] = v;
      }
      for (const k of ['effort', 'velocity']) {
        if (k in vals && vals[k] < 0) add('error', jn, `limit/${k}가 음수`);
      }
      if ('lower' in vals && 'upper' in vals && vals.lower >= vals.upper) add('error', jn, 'lower >= upper');
    }
    if (jt === 'continuous' && !lim) add('warn', jn, 'continuous 조인트에 effort/velocity limit 없음');
    const ax = kid(j, 'axis');
    if (jt !== 'fixed' && ax) {
      const v = floats(attr(ax, 'xyz') ?? '', 3);
      if (!v || Math.abs(v.reduce((a, x) => a + x * x, 0) - 1) > 1e-3) add('warn', jn, 'axis가 단위벡터가 아님');
    }
  });

  const roots = named.filter((n) => !children.has(n));
  if (roots.length !== 1) add('error', 'tree', `루트 링크가 ${roots.length}개: [${roots.map((r) => `'${r}'`).join(', ')}]`);
  for (const n of named) {
    const seen = new Set();
    let cur = n;
    while (parentOf.has(cur)) {
      if (seen.has(cur)) { add('error', n, '조인트 사이클'); break; }
      seen.add(cur);
      cur = parentOf.get(cur);
    }
  }

  links.forEach((l, i) => {
    const ln = attr(l, 'name') || `link[${i}]`;
    const inertial = kid(l, 'inertial');
    if (!inertial) {
      if (roots.length === 1 && ln !== 'world') add('warn', ln, 'inertial 없음 (시뮬레이션에서 문제 가능)');
    } else {
      const m = kid(inertial, 'mass');
      const mv = !m || attr(m, 'value') === null ? 0 : num(attr(m, 'value'));
      if (mv === null) add('error', ln, '질량 값이 숫자가 아님');
      else if (mv <= 0) add('error', ln, '질량이 0 이하');
      const ie = kid(inertial, 'inertia');
      if (ie) {
        const diag = ['ixx', 'iyy', 'izz'].map((k) => num(attr(ie, k) ?? '0'));
        const off = ['ixy', 'ixz', 'iyz'].map((k) => num(attr(ie, k) ?? '0'));
        if ([...diag, ...off].some((v) => v === null)) add('error', ln, '관성 값이 숫자가 아님');
        else {
          const [ixx, iyy, izz] = diag;
          if (Math.min(ixx, iyy, izz) <= 0) add('error', ln, '관성 대각 성분이 0 이하');
          else if (ixx + iyy < izz || ixx + izz < iyy || iyy + izz < ixx) add('error', ln, '관성 삼각부등식 위반');
        }
      }
    }
    for (const mesh of l.getElementsByTagName('mesh')) {
      const fn = attr(mesh, 'filename') ?? '';
      if (!fn.startsWith('package://')) {
        add('warn', ln, `package://가 아닌 메시 경로: ${fn || '(빈 값)'}`);
      } else if (meshNames) {
        const parts = fn.split('/');
        const rel = parts.length >= 4 ? parts.slice(3).join('/') : fn;   // package://pkg/<rel>
        const m = /^meshes\/([^/]+)$/.exec(rel);
        if (!m || !meshNames.has(m[1])) add('error', ln, `메시 파일 없음: ${fn}`);
      }
    }
  });

  return result(issues);
}

function result(issues) {
  const errors = issues.filter((i) => i.severity === 'error').length;
  const warnings = issues.length - errors;
  return {
    ok: errors === 0,
    summary: `${errors ? 'FAIL' : 'PASS'} · error ${errors} · warn ${warnings}`,
    errors, warnings, issues,
  };
}

export function robotNameOf(text) {
  const doc = new DOMParser().parseFromString(text, 'text/xml');
  if (doc.querySelector('parsererror')) return 'robot';
  return doc.documentElement.getAttribute('name') || 'robot';
}
