// ROS 2 description 패키지 zip 생성 (app/ros_package.py 의 브라우저용 포트).
// <pkg>/{package.xml, CMakeLists.txt, urdf/<robot>.urdf, meshes/, launch/display.launch.py, rviz/display.rviz, README.md}
import { TEMPLATES as T } from './templates.js';

const MESH_REF = /package:\/\/[^/"']+\/meshes\/([A-Za-z0-9_][A-Za-z0-9_.\-]*\.(?:stl|dae|obj))/gi;

export function packageName(robotName) {
  let n = String(robotName).toLowerCase().replace(/[^a-z0-9_]/g, '_');
  if (!/^[a-z]/.test(n)) n = 'robot_' + n;
  return n + '_description';
}
const xmlEscape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const fill = (tpl, o) => tpl.replace(/@@(PKG|ROBOT|FILE_ROBOT)@@/g, (_, k) => o[k]);

/**
 * @param {string} urdf
 * @param {string} robot  robot 이름
 * @param {Map<string, Blob>} meshes  업로드된 메시(저장 이름 → Blob)
 * @param {object} JSZip  전역 JSZip
 * @returns {Promise<{blob: Blob, pkg: string, fileName: string}>}
 */
export async function buildPackageZip(urdf, robot, meshes, JSZip) {
  const fileRobot = robot.replace(/[^A-Za-z0-9_-]/g, '_');
  const pkg = packageName(robot);
  const used = [...new Set([...urdf.matchAll(MESH_REF)].map((m) => m[1]))].sort();
  const present = used.filter((f) => meshes.has(f));
  const outUrdf = urdf.replace(MESH_REF, (all, f) => (present.includes(f) ? `package://${pkg}/meshes/${f}` : all));
  const o = { PKG: pkg, ROBOT: xmlEscape(robot), FILE_ROBOT: fileRobot };

  const z = new JSZip();
  z.file(`${pkg}/package.xml`, fill(T.packageXml, o));
  z.file(`${pkg}/CMakeLists.txt`, fill(T.cmake, o));
  z.file(`${pkg}/urdf/${fileRobot}.urdf`, outUrdf);
  z.file(`${pkg}/launch/display.launch.py`, fill(T.launch, o));
  z.file(`${pkg}/rviz/display.rviz`, T.rviz);
  z.file(`${pkg}/README.md`, fill(T.readme, o));
  z.file(`${pkg}/meshes/.keep`, '');
  for (const f of present) z.file(`${pkg}/meshes/${f}`, meshes.get(f));
  const blob = await z.generateAsync({ type: 'blob', compression: 'DEFLATE' });
  return { blob, pkg, fileName: `${pkg}.zip` };
}
