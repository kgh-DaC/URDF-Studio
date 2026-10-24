// 업로드한 메시 파일(STL/OBJ/DAE)에서 삼각형 좌표를 뽑는다. three.js 로더 사용.
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import { ColladaLoader } from 'three/examples/jsm/loaders/ColladaLoader.js';

export const ALLOWED_EXT = ['.stl', '.dae', '.obj'];
export const MAX_FILE_BYTES = 20 * 1024 * 1024;

/** 파일명을 [A-Za-z0-9_.-] 로 정규화하고 확장자는 소문자로. 허용되지 않은 확장자는 예외. */
export function safeMeshName(original) {
  const base = String(original || '').split(/[\\/]/).pop();
  const dot = base.lastIndexOf('.');
  const ext = dot >= 0 ? base.slice(dot).toLowerCase() : '';
  if (!ALLOWED_EXT.includes(ext)) throw new Error(`허용되지 않은 확장자: '${base}' (stl/dae/obj만 허용)`);
  let stem = base.slice(0, dot).replace(/[^A-Za-z0-9_-]/g, '_');
  if (!stem || !/^[A-Za-z0-9_]/.test(stem)) stem = 'mesh' + stem;
  return stem + ext;
}

function trianglesOf(root) {
  root.updateMatrixWorld(true);
  const out = [];
  const v = new THREE.Vector3();
  root.traverse((o) => {
    if (!o.isMesh || !o.geometry) return;
    const g = o.geometry, pos = g.attributes.position;
    if (!pos) return;
    const idx = g.index;
    const n = idx ? idx.count : pos.count;
    for (let i = 0; i < n; i++) {
      v.fromBufferAttribute(pos, idx ? idx.getX(i) : i).applyMatrix4(o.matrixWorld);
      out.push(v.x, v.y, v.z);
    }
  });
  return Float64Array.from(out);
}

/** File → { tris: Float64Array, ... } */
export async function loadTriangles(file, storedName) {
  const ext = storedName.slice(storedName.lastIndexOf('.')).toLowerCase();
  if (ext === '.stl') {
    const geo = new STLLoader().parse(await file.arrayBuffer());
    return trianglesOf(new THREE.Mesh(geo));
  }
  if (ext === '.obj') return trianglesOf(new OBJLoader().parse(await file.text()));
  const dae = new ColladaLoader().parse(await file.text(), '');
  return trianglesOf(dae.scene);
}
