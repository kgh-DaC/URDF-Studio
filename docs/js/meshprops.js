// 메시 물성 계산 (app/mesh_props.py 의 브라우저용 포트). three.js 에 의존하지 않는 순수 수학.
// 입력: 삼각형 좌표 Float64Array [x0,y0,z0, x1,y1,z1, x2,y2,z2, ...] (메시 원래 단위)
// 출력 필드는 Python 판과 같다: unit_guess, confidence, scale_to_m, bbox_m, bbox_center_m,
//   volume_m3, mass_kg, com_m, inertia{ixx..iyz}, warnings

/** 닫힌 곡면인지: 모든 모서리가 정확히 두 삼각형에 공유되는가 (trimesh 의 is_watertight 와 같은 기준). */
function isWatertight(tris, extent) {
  const q = Math.max(extent, 1e-12) * 1e-6;
  const ids = new Map();
  const id = (x, y, z) => {
    const k = `${Math.round(x / q)},${Math.round(y / q)},${Math.round(z / q)}`;
    let v = ids.get(k);
    if (v === undefined) { v = ids.size; ids.set(k, v); }
    return v;
  };
  const edges = new Map();
  const nTri = tris.length / 9;
  for (let t = 0; t < nTri; t++) {
    const v = [0, 1, 2].map((i) => id(tris[t * 9 + i * 3], tris[t * 9 + i * 3 + 1], tris[t * 9 + i * 3 + 2]));
    for (let i = 0; i < 3; i++) {
      const a = v[i], b = v[(i + 1) % 3];
      if (a === b) continue;                       // 퇴화 삼각형
      const k = a < b ? `${a}_${b}` : `${b}_${a}`;
      edges.set(k, (edges.get(k) || 0) + 1);
    }
  }
  if (edges.size === 0) return false;
  for (const c of edges.values()) if (c !== 2) return false;
  return true;
}

export function analyzeTriangles(tris, { unit = null, mass = null, density = null } = {}) {
  if (!tris || tris.length < 9) throw new Error('메시에 삼각형 면이 없음');
  const warnings = [];
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < tris.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      const v = tris[i + k];
      if (!Number.isFinite(v)) throw new Error('좌표에 NaN/inf 가 있음');
      if (v < lo[k]) lo[k] = v;
      if (v > hi[k]) hi[k] = v;
    }
  }
  const ext0 = [0, 1, 2].map((k) => hi[k] - lo[k]);
  const maxExt = Math.max(...ext0);

  let scale, guess, conf;
  if (unit) { scale = unit === 'mm' ? 0.001 : 1.0; guess = unit; conf = 'user'; }
  else {
    [guess, scale] = maxExt > 5 ? ['mm', 0.001] : ['m', 1.0];
    conf = 'low';
    warnings.push('unit_guess_low_confidence');
  }

  const s = new Float64Array(tris.length);
  for (let i = 0; i < tris.length; i++) s[i] = tris[i] * scale;
  const ext = ext0.map((e) => e * scale);
  const bboxCenter = [0, 1, 2].map((k) => ((lo[k] + hi[k]) / 2) * scale);

  const watertight = isWatertight(tris, maxExt);
  if (!watertight) warnings.push('not_watertight');

  // 부호 있는 사면체(원점 기준) 합산: 부피, 1차 모멘트, 2차 모멘트(∫xxᵀ)
  let vol = 0;
  const m1 = [0, 0, 0];
  const c2 = [0, 0, 0, 0, 0, 0];                    // xx, yy, zz, xy, xz, yz
  for (let t = 0; t < s.length; t += 9) {
    const a = [s[t], s[t + 1], s[t + 2]], b = [s[t + 3], s[t + 4], s[t + 5]], c = [s[t + 6], s[t + 7], s[t + 8]];
    const v = (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6;
    vol += v;
    const S = [a[0] + b[0] + c[0], a[1] + b[1] + c[1], a[2] + b[2] + c[2]];
    for (let k = 0; k < 3; k++) m1[k] += v * S[k] / 4;
    const P = (i, j) => a[i] * a[j] + b[i] * b[j] + c[i] * c[j] + S[i] * S[j];
    c2[0] += v / 20 * P(0, 0); c2[1] += v / 20 * P(1, 1); c2[2] += v / 20 * P(2, 2);
    c2[3] += v / 20 * P(0, 1); c2[4] += v / 20 * P(0, 2); c2[5] += v / 20 * P(1, 2);
  }
  const sign = vol < 0 ? -1 : 1;                    // 면 방향이 뒤집혀 있어도 양수 부피로
  const absVol = Math.abs(vol);

  const volume = watertight ? absVol : ext[0] * ext[1] * ext[2];
  let m = mass;
  if (m === null || m === undefined) {
    m = (density ?? 1000.0) * volume;
    if (density === null || density === undefined) warnings.push('mass_assumed_density_1000');
  }
  if (!(m > 0) || !Number.isFinite(m)) { m = 1e-3; warnings.push('mass_fallback_0.001kg'); }

  let com, I;
  if (watertight && absVol > 0) {
    com = m1.map((x) => (sign * x) / absVol);
    const rho = m / absVol;                         // 균일 밀도
    const C = c2.map((x) => sign * x * rho);        // 원점 기준 ∫ρ xxᵀ
    // COM 기준으로 이동: C' = C - m · com comᵀ
    const Cc = [
      C[0] - m * com[0] * com[0], C[1] - m * com[1] * com[1], C[2] - m * com[2] * com[2],
      C[3] - m * com[0] * com[1], C[4] - m * com[0] * com[2], C[5] - m * com[1] * com[2],
    ];
    const tr = Cc[0] + Cc[1] + Cc[2];
    I = { ixx: tr - Cc[0], iyy: tr - Cc[1], izz: tr - Cc[2], ixy: -Cc[3], ixz: -Cc[4], iyz: -Cc[5] };
  } else {
    com = bboxCenter;
    const [x, y, z] = ext;
    I = { ixx: m / 12 * (y * y + z * z), iyy: m / 12 * (x * x + z * z), izz: m / 12 * (x * x + y * y), ixy: 0, ixz: 0, iyz: 0 };
  }

  return {
    unit_guess: guess, confidence: conf, scale_to_m: scale,
    bbox_m: ext, bbox_center_m: bboxCenter,
    volume_m3: volume, mass_kg: m, com_m: com, inertia: I, warnings,
  };
}
