// URDF Studio (GitHub Pages 판). 서버 없이 브라우저에서만 동작한다.
// 검증(validator.js), 메시 분석(meshprops.js), 패키지 zip(package.js)은 app/ 의 Python 판과 같은 규칙의 JS 포트다.
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import URDFLoader from 'urdf-loader';
import { validateUrdf, robotNameOf } from './validator.js';
import { analyzeTriangles } from './meshprops.js';
import { loadTriangles, safeMeshName, MAX_FILE_BYTES } from './meshload.js';
import { buildPackageZip, packageName } from './package.js';

const $ = (id) => document.getElementById(id);
const state = {
  robot: null,
  highlighted: [],       // [{mesh, material}]
  meshes: [],            // 업로드 결과 [{stored_name, original_name, status, error, ...props}]
  meshBlobs: new Map(),  // stored_name -> Blob
  viewerInfo: '',
};
const blobUrls = new WeakMap();
function blobUrlFor(blob) {
  if (!blobUrls.has(blob)) blobUrls.set(blob, URL.createObjectURL(blob));
  return blobUrls.get(blob);
}

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
  // package://<pkg>/meshes/<file> 은 업로드해 메모리에 둔 Blob 으로 연결한다.
  manager.setURLModifier((url) => {
    const m = /^urdf-mesh:\/\/[^/]+\/meshes\/(.+)$/.exec(url);
    const blob = m && state.meshBlobs.get(decodeURIComponent(m[1]));
    return blob ? blobUrlFor(blob) : url;
  });
  const loader = new URDFLoader(manager);
  loader.packages = (pkg) => `urdf-mesh://${encodeURIComponent(pkg)}`;
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
  $('editorState').textContent = '변경됨';
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

function applyEditor() {
  const text = editor.value;
  renderURDF(text);
  validateText(text);
}
$('btnApply').onclick = applyEditor;

// ---------------------------------------------------------------- Validation panel
function validateText(text) {
  if (!text.trim()) { showValidation(null); return null; }
  const res = validateUrdf(text, new Set(state.meshBlobs.keys()));
  showValidation(res);
  $('editorState').textContent = editor.value === text ? '' : '변경됨';
  return res;
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


// ---------------------------------------------------------------- Mesh upload (브라우저 안에서 분석)
function uniqueName(name) {
  if (!state.meshBlobs.has(name)) return name;
  const dot = name.lastIndexOf('.');
  for (let i = 2; ; i++) {
    const cand = `${name.slice(0, dot)}_${i}${name.slice(dot)}`;
    if (!state.meshBlobs.has(cand)) return cand;
  }
}

function insertMeshLink(m) {
  const robot = robotNameOf(editor.value);
  const pkg = packageName(robot === 'robot' && !editor.value.trim() ? 'my_robot' : robot);
  const f = (v) => (+v.toFixed(6)).toString();
  const v3 = (a) => a.map(f).join(' ');
  const s = m.scale_to_m;
  const name = m.stored_name.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_]/g, '_') + '_link';
  const I = m.inertia;
  const snippet = `
  <link name="${name}">
    <visual>
      <origin xyz="0 0 0" rpy="0 0 0"/>
      <geometry><mesh filename="package://${pkg}/meshes/${m.stored_name}"${s !== 1 ? ` scale="${s} ${s} ${s}"` : ''}/></geometry>
    </visual>
    <collision>
      <origin xyz="${v3(m.bbox_center_m)}" rpy="0 0 0"/>
      <geometry><box size="${v3(m.bbox_m.map((x) => Math.max(x, 1e-4)))}"/></geometry>
    </collision>
    <inertial>
      <origin xyz="${v3(m.com_m)}" rpy="0 0 0"/>
      <mass value="${f(m.mass_kg)}"/>
      <inertia ixx="${I.ixx.toExponential(6)}" ixy="${I.ixy.toExponential(6)}" ixz="${I.ixz.toExponential(6)}" iyy="${I.iyy.toExponential(6)}" iyz="${I.iyz.toExponential(6)}" izz="${I.izz.toExponential(6)}"/>
    </inertial>
  </link>
`;
  const text = editor.value;
  if (!text.trim()) {
    setEditor(`<?xml version="1.0"?>\n<robot name="my_robot">${snippet}</robot>\n`);
  } else {
    const i = text.lastIndexOf('</robot>');
    setEditor(i >= 0 ? text.slice(0, i) + snippet.replace(/^\n/, '') + text.slice(i) : text + snippet);
  }
  applyEditor();
  $('editorState').textContent = `링크 '${name}' 추가됨`;
}

function renderMeshList() {
  const ul = $('meshList'); ul.innerHTML = '';
  for (const m of state.meshes) {
    const li = document.createElement('li');
    if (m.status !== 'ok') {
      li.className = 'failed'; li.textContent = `${m.original_name}: ${m.error}`;
    } else {
      const bb = (m.bbox_m || []).map((v) => v.toFixed(3)).join(' x ');
      const txt = document.createElement('div');
      txt.textContent = `${m.stored_name} · ${bb} m · ${m.mass_kg.toFixed(3)} kg · ${m.unit_guess}${m.warnings.length ? ' · ' + m.warnings.join(',') : ''}`;
      const add = document.createElement('button'); add.className = 'btn tiny'; add.textContent = '편집기에 링크 추가';
      add.onclick = () => insertMeshLink(m);
      const del = document.createElement('button'); del.className = 'btn tiny'; del.textContent = '삭제';
      del.onclick = () => {
        state.meshes = state.meshes.filter((x) => x !== m); state.meshBlobs.delete(m.stored_name);
        renderMeshList(); applyEditor();
      };
      li.append(txt, add, ' ', del);
    }
    ul.append(li);
  }
}

$('btnUpload').onclick = async () => {
  const files = [...$('meshFiles').files];
  if (!files.length) return;
  if (files.length > 10) { alert('한 번에 최대 10개까지 올릴 수 있습니다.'); return; }
  const unit = $('meshUnit').value || null;
  const mass = $('meshMass').value ? Number($('meshMass').value) : null;
  const density = $('meshDensity').value ? Number($('meshDensity').value) : null;
  for (const v of [mass, density]) {
    if (v !== null && (!Number.isFinite(v) || v <= 0)) { alert('질량/밀도는 0보다 큰 숫자여야 합니다.'); return; }
  }
  $('btnUpload').disabled = true;
  try {
    const added = [];
    for (const f of files) {
      let name;
      try { name = uniqueName(safeMeshName(f.name)); } catch (e) { added.push({ original_name: f.name, status: 'failed', error: e.message }); continue; }
      if (f.size === 0) { added.push({ original_name: f.name, status: 'failed', error: '빈 파일' }); continue; }
      if (f.size > MAX_FILE_BYTES) { added.push({ original_name: f.name, status: 'failed', error: '파일이 너무 큽니다(최대 20 MB)' }); continue; }
      try {
        const tris = await loadTriangles(f, name);
        const props = analyzeTriangles(tris, { unit, mass, density });
        state.meshBlobs.set(name, f);
        added.push({ stored_name: name, original_name: f.name, status: 'ok', ...props });
      } catch (e) {
        added.push({ original_name: f.name, status: 'failed', error: `메시 해석 실패: ${e.message}` });
      }
    }
    state.meshes = [...added, ...state.meshes.filter((x) => x.status === 'ok')];
    renderMeshList();
    applyEditor();                       // 새로 올린 메시가 있으면 뷰어·검증 갱신
  } finally {
    $('btnUpload').disabled = false; $('meshFiles').value = '';
  }
};

// ---------------------------------------------------------------- Samples / file
$('btnLoadSample').onclick = async () => {
  const name = $('sampleSelect').value; if (!name) return;
  const res = await fetch(`./samples/${encodeURIComponent(name)}.urdf`);
  if (!res.ok) { alert(`샘플을 불러오지 못했습니다 (HTTP ${res.status})`); return; }
  setEditor(await res.text()); applyEditor();
};
$('urdfFile').onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  if (f.size > 2_000_000) { alert('URDF 파일이 너무 큽니다(최대 2 MB).'); return; }
  setEditor(await f.text()); applyEditor(); e.target.value = '';
};

// ---------------------------------------------------------------- Download (모두 브라우저 안에서 생성)
function saveBlob(blob, fileName) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = fileName;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}
async function download(format) {
  const text = editor.value;
  if (!text.trim()) { alert('다운로드할 URDF가 없습니다.'); return; }
  const res = validateText(text);
  const robot = robotNameOf(text);
  if (res && !res.ok && !confirm(`검증 오류가 ${res.errors}개 있습니다. 그래도 내려받을까요?`)) return;
  const fileRobot = robot.replace(/[^A-Za-z0-9_-]/g, '_');
  if (format === 'urdf') { saveBlob(new Blob([text], { type: 'application/xml' }), `${fileRobot}.urdf`); return; }
  try {
    const { blob, fileName } = await buildPackageZip(text, robot, state.meshBlobs, window.JSZip);
    saveBlob(blob, fileName);
  } catch (e) { alert(`패키지 생성 실패: ${e.message}`); }
}
$('btnDownloadUrdf').onclick = () => download('urdf');
$('btnDownloadZip').onclick = () => download('zip');

// ---------------------------------------------------------------- Init
(async function init() {
  updateGutter();
  try {
    const s = await (await fetch('./samples/index.json')).json();
    const sel = $('sampleSelect');
    for (const n of s.samples) { const o = document.createElement('option'); o.value = o.textContent = n; sel.append(o); }
    if (s.samples.includes('two_link_arm')) {
      sel.value = 'two_link_arm';
      setEditor(await (await fetch('./samples/two_link_arm.urdf')).text()); applyEditor();
    }
  } catch (e) { viewerMsg(`초기화 실패: ${e.message}`, true); }
})();
