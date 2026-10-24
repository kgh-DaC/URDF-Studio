// URDF Studio frontend. API field names follow app/schema.py.
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import URDFLoader from 'urdf-loader';

const $ = (id) => document.getElementById(id);
const state = {
  artifactId: null,      // id of the last validated/generated URDF (for /api/download)
  artifactText: null,    // editor text that artifactId corresponds to
  robot: null,
  highlighted: [],       // [{mesh, material}]
  meshes: [],            // uploaded MeshProps
  apiKey: false,
};

// ---------------------------------------------------------------- API helpers
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
    const msg = body && body.message ? body.message : `HTTP ${res.status}`;
    const e = new Error(msg); e.code = body && body.error; e.status = res.status; throw e;
  }
  return body;
}
const postJSON = (path, data) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
});

// ---------------------------------------------------------------- Viewer
const viewerEl = $('viewer');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setClearColor(0x0f1216);
viewerEl.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 500);
camera.position.set(1.2, 0.9, 1.2);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.2, 0);
scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 1.6));
const dir = new THREE.DirectionalLight(0xffffff, 1.6);
dir.position.set(2, 4, 3);
scene.add(dir);
const grid = new THREE.GridHelper(4, 40, 0x3a4250, 0x232932);
scene.add(grid);
const axes = new THREE.AxesHelper(0.2); // red=X, green=Y(three) — robot frame is rotated so ROS Z is up
scene.add(axes);

function resize() {
  const w = viewerEl.clientWidth, h = viewerEl.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(viewerEl);
resize();
(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

function viewerMsg(text, isErr = false) {
  const el = $('viewerMsg'); el.textContent = text; el.classList.toggle('err', isErr);
}

function fitCamera() {
  if (!state.robot) return;
  const box = new THREE.Box3().setFromObject(state.robot);
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3()).length() || 1;
  const center = box.getCenter(new THREE.Vector3());
  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(size, size * 0.7, size));
  camera.near = size / 100; camera.far = size * 100; camera.updateProjectionMatrix();
}

function loadMesh(path, manager, material, done) {
  if (/\.obj$/i.test(path)) {
    new OBJLoader(manager).load(path, (obj) => {
      if (material) obj.traverse((c) => { if (c.isMesh) c.material = material; });
      done(obj);
    }, null, (err) => done(null, err));
  } else {
    URDFLoader.prototype.defaultMeshLoader.call(this, path, manager, material, done);
  }
}

function renderURDF(text) {
  clearHighlight();
  if (state.robot) { scene.remove(state.robot); state.robot = null; }
  $('jointSliders').innerHTML = '';
  if (!text.trim()) { viewerMsg('URDF 없음'); return; }
  const manager = new THREE.LoadingManager();
  let meshErrors = 0;
  manager.onError = () => { meshErrors += 1; };
  manager.onLoad = () => {
    fitCamera();
    if (meshErrors) viewerMsg(`${state.viewerInfo || ''} · 메시 ${meshErrors}개 로드 실패 (업로드했는지 확인)`, true);
  };
  const loader = new URDFLoader(manager);
  loader.packages = (pkg) => `/api/pkg/${encodeURIComponent(pkg)}`;
  loader.loadMeshCb = loadMesh.bind(loader);
  let robot, partial = '';
  try {
    const doc = new DOMParser().parseFromString(text, 'text/xml');
    if (doc.querySelector('parsererror')) throw new Error('XML 구문 오류');
    if (doc.documentElement.tagName !== 'robot') throw new Error('<robot> 요소를 찾을 수 없음');
    try {
      robot = loader.parse(text);
    } catch (e) {
      // urdf-loader throws on dangling references; render what we can so error links stay visible.
      const dropped = sanitizeForViewer(doc);
      if (!dropped) throw e;
      robot = loader.parse(new XMLSerializer().serializeToString(doc));
      partial = ` · 부분 렌더(깨진 조인트 ${dropped}개 제외)`;
    }
    if (!robot || !robot.isURDFRobot) throw new Error('<robot> 요소를 찾을 수 없음');
  } catch (e) {
    viewerMsg(`렌더링 실패: ${e.message}`, true);
    return;
  }
  robot.rotation.x = -Math.PI / 2; // ROS Z-up -> three Y-up
  scene.add(robot);
  state.robot = robot;
  buildSliders(robot);
  fitCamera();
  state.viewerInfo = `${robot.robotName || ''} · 링크 ${Object.keys(robot.links).length} · 조인트 ${Object.keys(robot.joints).length}${partial}`;
  viewerMsg(state.viewerInfo, !!partial);
}

// Remove joints whose parent/child link is missing or whose child already has a parent.
function sanitizeForViewer(doc) {
  const root = doc.documentElement;
  const links = new Set([...root.children].filter((c) => c.tagName === 'link').map((l) => l.getAttribute('name')));
  const seenChild = new Set();
  let dropped = 0;
  for (const j of [...root.children].filter((c) => c.tagName === 'joint')) {
    const p = j.querySelector('parent')?.getAttribute('link');
    const c = j.querySelector('child')?.getAttribute('link');
    if (!links.has(p) || !links.has(c) || seenChild.has(c) || p === c) { j.remove(); dropped += 1; continue; }
    seenChild.add(c);
  }
  return dropped;
}

function buildSliders(robot) {
  const wrap = $('jointSliders');
  const movable = Object.values(robot.joints).filter((j) => j.jointType !== 'fixed');
  $('jointsPanel').style.display = movable.length ? '' : 'none';
  for (const j of movable) {
    let lo = Number(j.limit.lower), hi = Number(j.limit.upper);
    if (j.jointType === 'continuous' || !(hi > lo)) { lo = -Math.PI; hi = Math.PI; }
    const isLin = j.jointType === 'prismatic';
    const div = document.createElement('div'); div.className = 'joint';
    const label = document.createElement('div'); label.className = 'jl';
    const nm = document.createElement('span'); nm.textContent = `${j.name} (${j.jointType})`;
    const val = document.createElement('span');
    label.append(nm, val);
    const input = document.createElement('input');
    input.type = 'range'; input.min = lo; input.max = hi; input.step = (hi - lo) / 400;
    const init = Math.min(Math.max(0, lo), hi);
    input.value = init;
    const show = (v) => { val.textContent = isLin ? `${(+v).toFixed(3)} m` : `${(+v * 180 / Math.PI).toFixed(1)}°`; };
    input.addEventListener('input', () => { j.setJointValue(+input.value); show(input.value); });
    j.setJointValue(init); show(init);
    input.dataset.init = init;
    div.append(label, input);
    wrap.append(div);
  }
}
$('btnResetJoints').onclick = () => {
  for (const input of $('jointSliders').querySelectorAll('input[type=range]')) {
    input.value = input.dataset.init; input.dispatchEvent(new Event('input'));
  }
};

function clearHighlight() {
  for (const { mesh, material } of state.highlighted) mesh.material = material;
  state.highlighted = [];
}
function highlightLink(name) {
  clearHighlight();
  if (!state.robot || !name || !state.robot.links[name]) return false;
  const link = state.robot.links[name];
  for (const child of link.children) {
    if (!child.isURDFVisual) continue;
    child.traverse((o) => {
      if (!o.isMesh) return;
      state.highlighted.push({ mesh: o, material: o.material });
      o.material = new THREE.MeshPhongMaterial({ color: 0xff4d4d, emissive: 0x661111 });
    });
  }
  return true;
}

// ---------------------------------------------------------------- Editor
const editor = $('editor'), gutter = $('gutter');
function updateGutter() {
  const n = editor.value.split('\n').length;
  let s = ''; for (let i = 1; i <= n; i++) s += i + '\n';
  gutter.textContent = s;
  gutter.scrollTop = editor.scrollTop;
}
editor.addEventListener('scroll', () => { gutter.scrollTop = editor.scrollTop; });
let debounce = null;
editor.addEventListener('input', () => {
  updateGutter();
  $('editorState').textContent = state.artifactText === editor.value ? '' : '변경됨';
  if (!$('autoApply').checked) return;
  clearTimeout(debounce);
  debounce = setTimeout(applyEditor, 700);
});
editor.addEventListener('keydown', (e) => {
  if (e.key === 'Tab') {
    e.preventDefault();
    const s = editor.selectionStart;
    editor.setRangeText('  ', s, editor.selectionEnd, 'end');
    editor.dispatchEvent(new Event('input'));
  }
});
function setEditor(text) {
  editor.value = text; updateGutter(); editor.scrollTop = 0;
}
function selectInEditor(name) {
  if (!name) return;
  const needle = `name="${name}"`;
  const i = editor.value.indexOf(needle);
  if (i < 0) return;
  editor.focus();
  editor.setSelectionRange(i, i + needle.length);
  const line = editor.value.slice(0, i).split('\n').length;
  editor.scrollTop = Math.max(0, (line - 4) * 18);
}

async function applyEditor() {
  const text = editor.value;
  renderURDF(text);
  await validateText(text);
}
$('btnApply').onclick = applyEditor;

// ---------------------------------------------------------------- Validation panel
async function validateText(text) {
  if (!text.trim()) { showValidation(null); return null; }
  try {
    const res = await postJSON('/api/validate', { urdf: text, check_meshes: true });
    state.artifactId = res.artifact_id; state.artifactText = text;
    $('editorState').textContent = editor.value === text ? '' : '변경됨';
    showValidation(res.validation);
    return res;
  } catch (e) {
    showValidation({ ok: false, summary: `검증 요청 실패: ${e.message}`, issues: [] });
    return null;
  }
}

function showValidation(v) {
  const sum = $('valSummary'), list = $('issues');
  list.innerHTML = '';
  if (!v) { sum.textContent = '-'; sum.className = 'summary'; return; }
  sum.textContent = v.summary;
  sum.className = 'summary ' + (v.ok ? 'pass' : 'fail');
  if (v.ok && !v.issues.length) {
    const li = document.createElement('li'); li.textContent = '문제 없음'; li.className = 'ok'; list.append(li);
  }
  for (const iss of v.issues) {
    const li = document.createElement('li'); li.className = iss.severity;
    const head = document.createElement('div');
    const sev = document.createElement('span'); sev.className = 'sev'; sev.textContent = iss.severity;
    const where = document.createElement('span'); where.className = 'where'; where.textContent = iss.where;
    head.append(sev, where);
    const msg = document.createElement('div'); msg.textContent = iss.message;
    li.append(head, msg);
    if (iss.suggestion) {
      const sug = document.createElement('div'); sug.className = 'sug'; sug.textContent = '제안: ' + iss.suggestion; li.append(sug);
    }
    li.onclick = () => {
      for (const x of list.children) x.classList.remove('active');
      li.classList.add('active');
      const ok = highlightLink(iss.link);
      const info = state.viewerInfo || '';
      viewerMsg(ok ? `${info} · 하이라이트: ${iss.link}` : (iss.link ? `${info} · 뷰어에 '${iss.link}' 링크 없음` : info), false);
      selectInEditor(iss.where);
    };
    list.append(li);
  }
}

function showAssumptions(items) {
  const ul = $('assumptions'); ul.innerHTML = '';
  for (const a of items || []) { const li = document.createElement('li'); li.textContent = a; ul.append(li); }
}

// ---------------------------------------------------------------- Generate
$('btnGenerate').onclick = async () => {
  const prompt = $('prompt').value.trim();
  if (!prompt) { $('genStatus').textContent = '프롬프트를 입력하세요.'; return; }
  const meshes = [...document.querySelectorAll('#meshList input[type=checkbox]:checked')].map((c) => c.value);
  const body = { prompt, meshes };
  if ($('useBase').checked && editor.value.trim()) body.baseUrdf = editor.value;
  const btn = $('btnGenerate'); btn.disabled = true;
  $('genStatus').textContent = '생성 중… (Claude 호출 + 검증, 최대 3회)';
  $('attempts').innerHTML = '';
  try {
    const res = await postJSON('/api/generate', body);
    setEditor(res.urdf);
    state.artifactId = res.artifact_id; state.artifactText = res.urdf;
    $('editorState').textContent = '';
    renderURDF(res.urdf);
    showValidation(res.validation);
    showAssumptions(res.assumptions);
    $('genStatus').textContent = `완료 · 모델 ${res.model} · 시도 ${res.attempts.length}회`;
    for (const a of res.attempts) {
      const li = document.createElement('li');
      li.className = a.status === 'ok' ? 'st-ok' : 'st-bad';
      li.textContent = `${a.status}${a.detail.length ? ': ' + a.detail.slice(0, 3).join(' / ') : ''}`;
      $('attempts').append(li);
    }
  } catch (e) {
    $('genStatus').textContent = `생성 실패 [${e.code || e.status}]: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
};

// ---------------------------------------------------------------- Mesh upload
function renderMeshList() {
  const ul = $('meshList'); ul.innerHTML = '';
  for (const m of state.meshes) {
    const li = document.createElement('li');
    if (m.status !== 'ok') {
      li.className = 'failed'; li.textContent = `${m.original_name}: ${m.error}`;
    } else {
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.value = m.stored_name; cb.checked = !!m._fresh;
      const lab = document.createElement('label'); lab.className = 'check';
      const bb = (m.bbox_m || []).map((v) => v.toFixed(3)).join(' x ');
      const txt = document.createElement('span');
      txt.textContent = `${m.stored_name} · ${bb} m · ${m.mass_kg.toFixed(3)} kg · ${m.unit_guess}${m.warnings.length ? ' · ' + m.warnings.join(',') : ''}`;
      lab.append(cb, txt); li.append(lab);
    }
    ul.append(li);
  }
}
$('btnUpload').onclick = async () => {
  const files = $('meshFiles').files;
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  if ($('meshUnit').value) fd.append('unit', $('meshUnit').value);
  if ($('meshMass').value) fd.append('mass', $('meshMass').value);
  $('btnUpload').disabled = true;
  try {
    const res = await api('/api/upload', { method: 'POST', body: fd });
    for (const m of res.meshes) m._fresh = true;
    state.meshes = [...res.meshes, ...state.meshes.filter((x) => x.status === 'ok')];
    renderMeshList();
  } catch (e) {
    alert(`업로드 실패: ${e.message}`);
  } finally {
    $('btnUpload').disabled = false; $('meshFiles').value = '';
  }
};

// ---------------------------------------------------------------- Samples / file
$('btnLoadSample').onclick = async () => {
  const name = $('sampleSelect').value; if (!name) return;
  const res = await api(`/api/samples/${encodeURIComponent(name)}`);
  setEditor(res.urdf); showAssumptions([]); applyEditor();
};
$('urdfFile').onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  if (f.size > 2_000_000) { alert('URDF 파일이 너무 큽니다(최대 2 MB).'); return; }
  setEditor(await f.text()); showAssumptions([]); applyEditor(); e.target.value = '';
};

// ---------------------------------------------------------------- Download
// QA W6: fetch -> check res.ok -> Blob download. If the artifact is gone (404), re-validate once and retry.
async function download(format) {
  const text = editor.value;
  if (!text.trim()) { alert('다운로드할 URDF가 없습니다.'); return; }
  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt > 0 || state.artifactText !== text || !state.artifactId) {
      const r = await validateText(text);
      if (!r || !state.artifactId) { alert('다운로드 준비(검증) 실패'); return; }
    }
    let res;
    try {
      res = await fetch(`/api/download/${encodeURIComponent(state.artifactId)}?format=${format}`);
    } catch (e) { alert(`다운로드 실패: ${e.message}`); return; }
    if (res.ok) {
      const blob = await res.blob();
      const cd = res.headers.get('content-disposition') || '';
      const m = cd.match(/filename="([^"]+)"/);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = m ? m[1] : `robot.${format}`;
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      return;
    }
    if (res.status === 404 && attempt === 0) { state.artifactId = null; continue; }
    let msg = `HTTP ${res.status}`;
    try { msg = (await res.json()).message || msg; } catch { /* non-JSON */ }
    alert(`다운로드 실패: ${msg}`);
    return;
  }
}
$('btnDownloadUrdf').onclick = () => download('urdf');
$('btnDownloadZip').onclick = () => download('zip');

// ---------------------------------------------------------------- Init
(async function init() {
  updateGutter();
  try {
    const h = await api('/api/health');
    state.apiKey = h.api_key_configured;
    const b = $('apiStatus');
    b.textContent = h.api_key_configured ? `Claude 연결됨 · ${h.model}` : 'API 키 없음 · 생성 비활성 (검증·뷰어는 사용 가능)';
    b.className = 'badge ' + (h.api_key_configured ? 'ok' : 'off');
    if (!h.api_key_configured) $('btnGenerate').title = '서버에 ANTHROPIC_API_KEY가 없습니다';
  } catch { $('apiStatus').textContent = '서버 연결 실패'; }
  try {
    const s = await api('/api/samples');
    const sel = $('sampleSelect');
    for (const n of s.samples) { const o = document.createElement('option'); o.value = o.textContent = n; sel.append(o); }
    const m = await api('/api/meshes'); state.meshes = m.meshes; renderMeshList();
    if (s.samples.includes('two_link_arm')) {
      sel.value = 'two_link_arm';
      const r = await api('/api/samples/two_link_arm'); setEditor(r.urdf); applyEditor();
    }
  } catch (e) { viewerMsg(`초기화 실패: ${e.message}`, true); }
})();
