# URDF Studio

FreeCAD 등 CAD에서 만든 모델과 STL 메시로 **ROS 2 URDF/xacro를 만들고, 3D로 확인하고, 검증한 뒤, ROS 2 워크스페이스에 넣는** 과정을 쉽게 만들기 위한 도구 모음입니다. 자연어로 로봇 구조를 설명하면 Claude가 URDF를 만들어 주는 기능도 있습니다(선택).

```
FreeCAD 모델 ──▶ STL + parts.json ──▶ 메시 물성 계산 ──▶ URDF/xacro 작성 ──▶ 검증 ──▶ ros2_ws/src 설치
   (매크로)        (freecad-export)     (질량·관성)      (웹 앱 / Claude)   (자동)    (설치 스크립트)
```

## 목차
0. [웹에서 바로 사용 (GitHub Pages)](#0-웹에서-바로-사용-github-pages)
1. [구성 요소](#1-구성-요소)
2. [빠른 시작 (Windows)](#2-빠른-시작-windows)
3. [Linux / macOS 실행](#3-linux--macos-실행)
4. [웹 앱 사용법](#4-웹-앱-사용법)
5. [FreeCAD에서 내보내기](#5-freecad에서-내보내기)
6. [ROS 2 워크스페이스에 설치](#6-ros-2-워크스페이스에-설치)
7. [데모 따라 해 보기](#7-데모-따라-해-보기)
8. [API](#8-api)
9. [설정 (환경변수)](#9-설정-환경변수)
10. [Claude 하네스 (에이전트·스킬)](#10-claude-하네스-에이전트스킬)
11. [저장소 구조](#11-저장소-구조)
12. [테스트](#12-테스트)
13. [보안과 제한](#13-보안과-제한)
14. [검증 상태와 알려진 한계](#14-검증-상태와-알려진-한계)
15. [문제 해결](#15-문제-해결)

---

## 0. 웹에서 바로 사용 (GitHub Pages)

설치 없이 브라우저에서 바로 쓰는 버전이 `docs/`에 있습니다. 서버가 필요 없고 **파일이 내 PC 밖으로 나가지 않습니다**.

- 주소: <https://kgh-dac.github.io/URDF-Studio/> (저장소 `Settings → Pages`에서 Source를 `Deploy from a branch`, Branch를 `main`, 폴더를 `/docs`로 한 번 지정해야 켜집니다)
- 로컬에서 보려면: `python -m http.server 8790 --directory docs` 후 <http://127.0.0.1:8790>. `index.html`을 파일로 직접 열면 브라우저가 모듈 로딩을 막으므로 반드시 서버로 여세요.

| 기능 | Pages 버전 | 로컬 서버판(`app/`) |
| --- | --- | --- |
| 3D 뷰어, 조인트 슬라이더, 오류 링크 하이라이트 | O | O |
| URDF 검증 | O (Python 판과 같은 규칙) | O |
| STL/OBJ/DAE 업로드, 질량·관성·충돌 박스 계산 | O (브라우저 안에서 계산) | O |
| 메시에서 `<link>` 조각 자동 삽입 | O | - |
| URDF 다운로드, ROS 2 패키지 zip | O | O |
| 자연어 생성(Claude API) | **X** | O (`ANTHROPIC_API_KEY` 필요) |
| 기존 URDF를 명세로 가져와 수정 | X | O |

사용 순서: FreeCAD STL을 **단위 mm**로 업로드 → 각 메시의 **편집기에 링크 추가** → 편집기에서 조인트 작성(자동 검증·렌더) → **ROS 2 패키지 (zip)** → `ros2_ws/src`에 풀기.
JS 포트(`docs/js/validator.js`, `meshprops.js`, `package.js`)는 Python 판과 같은 입력에서 같은 결과가 나오는지 확인했습니다(검증기 26개 케이스, 메시 물성 7개 케이스, zip 파일 내용). three.js, urdf-loader, JSZip은 `docs/vendor/`에 포함되어 CDN이 필요 없습니다.

## 1. 구성 요소

| 구성 | 위치 | 역할 |
| --- | --- | --- |
| 웹 앱 | `app/` | FastAPI 서버 + 브라우저 UI. 3D 미리보기, 검증, 메시 업로드, URDF/ZIP 다운로드, 자연어 생성 |
| 웹 버전 | `docs/index.html`, `docs/js/`, `docs/vendor/` | 서버 없이 브라우저에서 동작하는 URDF Studio (GitHub Pages) |
| 로컬 서버 안내 | `docs/local.html` | 로컬 서버가 켜져 있는지 확인하고 실행 방법을 안내하는 정적 페이지 |
| FreeCAD 내보내기 | `.claude/skills/freecad-export/` | FreeCAD 매크로. 부품별 STL과 `parts.json` 생성, 데모 모델 생성 |
| 워크스페이스 설치 | `.claude/skills/ros2-workspace-install/` | 검증 통과 시에만 `<ws>/src/<robot>_description/` 패키지 생성 |
| 검증 스크립트 | `.claude/skills/urdf-validation/` | 웹 앱 검증기와 같은 규칙의 단독 실행 스크립트 |
| 에이전트·스킬 | `.claude/` | Claude Code용 작업 팀(설계·메시 분석·QA·웹 앱·ROS 2 통합) |
| 데모 | `examples/freecad_demo/` | 3부품 로봇팔로 전 과정을 재현하는 스크립트 |

## 2. 빠른 시작 (Windows)

1. **Python 3.11 이상** 설치: <https://www.python.org/downloads/>. 설치 화면에서 `Add python.exe to PATH`와 `py launcher`를 체크합니다.
2. 저장소 받기
   ```powershell
   git clone https://github.com/kgh-DaC/URDF-Studio.git
   cd URDF-Studio
   ```
   Git이 없으면 GitHub 페이지의 **Code → Download ZIP**으로 받아 압축을 풉니다.
3. `app\run.bat` **더블클릭**. 처음에는 가상환경 생성과 패키지 설치로 몇 분 걸립니다. 끝나면 브라우저가 `http://127.0.0.1:8000`으로 열립니다.
4. 종료는 서버 창(검은 창)을 닫거나 `Ctrl+C`.

PowerShell을 쓰는 경우:
```powershell
cd app
.\run.ps1                 # 포트 변경: .\run.ps1 -Port 8080
```
실행 정책 오류가 나면 `powershell -ExecutionPolicy Bypass -File .\run.ps1`.

`docs/local.html`을 웹 서버로 열면 서버 실행 여부를 확인하고 버튼으로 앱을 열 수 있습니다. 다만 이 페이지가 서버를 대신 실행하지는 못합니다(서버는 반드시 내 PC에서 직접 켜야 합니다).

## 3. Linux / macOS 실행

```bash
git clone https://github.com/kgh-DaC/URDF-Studio.git
cd URDF-Studio/app
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8000
```
브라우저에서 <http://127.0.0.1:8000>. 3D 뷰어는 CDN(jsDelivr)에서 three.js를 받으므로 **인터넷 연결이 필요**합니다.

## 4. 웹 앱 사용법

화면은 좌측 입력, 중앙 3D 뷰어와 편집기, 우측 검증 결과로 나뉩니다.

| 영역 | 기능 |
| --- | --- |
| 좌측 · 자연어로 생성 | 로봇을 말로 설명하고 **생성**. "편집기의 URDF를 기반으로 수정"을 체크하면 기존 URDF를 고칩니다. (`ANTHROPIC_API_KEY` 필요) |
| 좌측 · 메시 업로드 | STL/DAE/OBJ(파일당 20 MB, 최대 10개). 단위(mm/m)와 질량 또는 밀도를 지정하면 질량·관성·바운딩 박스를 계산합니다. |
| 좌측 · 샘플/파일 | `diff_drive_robot`, `two_link_arm`, `broken_arm`(일부러 깨진 예제)을 불러오거나 URDF 파일을 엽니다. |
| 중앙 · 3D 뷰어 | 드래그 회전, 휠 확대. 우측 상단 슬라이더로 조인트를 움직입니다. |
| 중앙 아래 · URDF 편집기 | 입력 0.7초 후 자동 검증·렌더. **검증 + 렌더** 버튼으로 즉시 실행. |
| 우측 · 검증 결과 | error/warn 목록. 항목을 클릭하면 해당 링크가 뷰어에서 빨갛게 표시되고 편집기에서 이름이 선택됩니다. |
| 우측 · 가정 | 생성 시 Claude나 코드가 임의로 정한 값(치수, 질량, 한계 등) |
| 상단 | **URDF 다운로드**, **ROS 2 패키지 (zip)** |

### 검증이 확인하는 것
XML 구문, 링크·조인트 트리(고아 링크, 루프, 다중 루트), 조인트 limit(revolute/prismatic의 lower·upper·effort·velocity), 질량과 관성의 물리적 타당성(양수, 삼각부등식), 메시 파일 경로, axis와 이름 중복 등. 결과는 `PASS · error N · warn M` 형식입니다.

### 자연어 생성이 동작하는 방식
1. Claude가 `submit_robot_spec` 도구로 **구조 명세 JSON**만 반환합니다(XML을 직접 쓰지 않음).
2. `builder.py`가 명세를 URDF로 조립합니다. 관성은 박스·원기둥·구 공식 또는 메시 해석값으로 코드가 계산합니다(AI가 임의로 정하지 않음).
3. `validator.py`로 검증하고, 오류는 Claude에게 되돌려 **최대 2회** 수정시킵니다.

## 5. FreeCAD에서 내보내기

### 모델링 규칙
- **링크 1개 = 최상위 Body 또는 Part 1개**로 만듭니다. 이름은 영문 소문자·숫자·밑줄을 권장합니다.
- 보이지 않는 객체(`Visibility` 꺼짐), 스케치·평면 같은 비솔리드 객체는 건너뜁니다.

### 실행
1. FreeCAD에서 모델을 연 채 `매크로 → 매크로…`로 `.claude/skills/freecad-export/scripts/export_parts.py` 실행. 출력 폴더는 기본 `홈/freecad_export/`.
2. 명령줄로 실행하려면 (Windows):
   ```bat
   set FC_FILE=C:\cad\robot.FCStd
   set FC_OUT=C:\cad\export
   FreeCADCmd export_parts.py
   ```
3. 직접 모델링하기 전에 시험해 보려면 `create_demo_model.py`를 먼저 실행하면 박스 3개(base, arm1, arm2)가 생깁니다.

### 결과물
`<폴더>/*.stl`(mm 단위)과 `parts.json`(이름, 부피, bbox, 위치, 질량중심). **STL은 조립된 위치(월드 좌표)** 로 저장되므로, 링크 프레임을 조인트 위치로 옮길 때는 visual origin을 그만큼 반대로 보정해야 합니다. 데모 스크립트가 이 계산의 예시입니다.

### 질량
FreeCAD 모델에는 재질이 없으므로 `부피 × 밀도`로 추정합니다. 알루미늄 2700, 강철 7850, ABS 1050 kg/m³ 정도를 참고하되 실제 값을 입력하세요. 모르면 `assumptions`에 가정으로 남습니다.

## 6. ROS 2 워크스페이스에 설치

```bash
python -I .claude/skills/ros2-workspace-install/scripts/install_to_workspace.py \
  --urdf output/robot.urdf [--xacro output/robot.urdf.xacro] [--meshes meshes] \
  --ws ~/ros2_ws [--dry-run] [--force]
```

| 옵션 | 설명 |
| --- | --- |
| `--urdf` | 설치할 URDF (필수) |
| `--ws` | 워크스페이스 루트(`src/`의 부모). 폴더는 미리 만들어 둡니다. WSL은 `\\wsl$\Ubuntu\home\<user>\ros2_ws` |
| `--meshes` | URDF가 참조하는 메시가 있는 폴더 |
| `--xacro` | 원본 xacro. 패키지 `urdf/`에 함께 복사 |
| `--dry-run` | 파일을 쓰지 않고 패키지명·위치만 출력 |
| `--force` | 같은 패키지가 있으면 `<ws>/backup/`으로 옮겨 보존한 뒤 덮어쓰기 |

동작 순서: 검증 → error가 있으면 **중단** → 메시 참조를 `package://<pkg>/meshes/...`로 재작성 → `package.xml`, `CMakeLists.txt`, `launch/display.launch.py`, `rviz/display.rviz` 생성.

설치 후 ROS 2 터미널에서:
```bash
cd ~/ros2_ws
colcon build --packages-select <robot>_description
source install/setup.bash          # Windows: call install\setup.bat
ros2 launch <robot>_description display.launch.py
```
웹 앱의 **ROS 2 패키지 (zip)** 로 받아 `ros2_ws/src`에 풀어도 같은 구조입니다.

## 7. 데모 따라 해 보기

FreeCAD 없이 전체 흐름을 재현합니다. (FreeCAD 내보내기 단계만 흉내 낸 STL을 사용)

```bash
cd app && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && cd ..
python examples/freecad_demo/run_demo.py --ws ./demo_ws
```
수행 내용: 박스 3개 STL 생성(mm) → 알루미늄 밀도로 질량 계산(0.778 / 0.162 / 0.069 kg) → 어깨·팔꿈치 조인트가 있는 URDF 생성 → 검증 PASS → `demo_ws/src/freecad_demo_arm_description/` 설치. `examples/freecad_demo/preview.png`가 기본 자세와 굽힌 자세의 미리보기입니다.

## 8. API

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | `/api/generate` | `{prompt, meshes[], baseUrdf?}` → `{urdf, spec, assumptions[], validation, artifact_id, attempts[], model}`. 키가 없으면 503 `missing_api_key` |
| POST | `/api/validate` | `{urdf, check_meshes?}` → `{validation, artifact_id, robot_name}` |
| POST | `/api/upload` | multipart `files`, `unit?`(mm/m), `mass?`, `density?` → `{meshes:[MeshProps]}` |
| GET | `/api/download/{id}?format=urdf\|zip` | URDF 또는 ROS 2 패키지 zip |
| GET | `/api/health` `/api/samples` `/api/samples/{name}` `/api/meshes` `/api/schema` | 상태, 샘플, 업로드 목록, 명세 JSON 스키마 |
| GET | `/api/pkg/{pkg}/meshes/{file}` | 뷰어용 `package://` 메시 제공 |

오류 응답은 항상 `{"error": "<code>", "message": "<설명>"}`.

## 9. 설정 (환경변수)

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | (없음) | 자연어 생성에 필요. 없어도 나머지 기능은 동작 |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | 생성에 쓸 모델 |
| `URDF_APP_ALLOWED_HOSTS` | `127.0.0.1,localhost` | 허용할 Host 헤더(DNS rebinding 방지). 다른 호스트명으로 접속할 때 추가 |
| `URDF_APP_DATA` | `app/data` | 업로드 메시·결과 저장 위치 |
| `URDF_APP_ARTIFACT_TTL_S` | `86400` | 결과 보관 시간(초) |
| `URDF_APP_MAX_ARTIFACTS` | `500` | 결과 보관 최대 개수 |

Windows PowerShell 예: `$env:ANTHROPIC_API_KEY = "sk-ant-..."` 후 `.\run.ps1`. API 키는 서버에서만 읽고 브라우저로 보내지 않습니다.

## 10. Claude 하네스 (에이전트·스킬)

Claude Code로 이 저장소를 열면 `CLAUDE.md`에 따라 URDF 관련 요청이 `urdf-builder` 오케스트레이터로 연결됩니다.

| 단계 | 담당 | 산출물 |
| --- | --- | --- |
| 0 | `freecad-export` 스킬 + 사용자 | `_workspace/freecad/*.stl`, `parts.json` |
| 1 | `mesh-analyst` | `_workspace/02_mesh_props.json` |
| 2 | `urdf-architect` | 구조 명세 + `output/*.urdf(.xacro)` |
| 3~4 | `urdf-qa` ↔ `urdf-architect` | QA 보고서, 수정본(최대 2회) |
| 5~6 | `urdf-webapp-dev`, `urdf-qa` | 웹 앱 구현과 API↔UI 경계면 검증 |
| 7~8 | `ros2-integrator` + `ros2-workspace-install` | ROS 2 패키지, 워크스페이스 설치 |

예시 요청: "FreeCAD로 만든 로봇팔 STL 3개로 URDF 만들고 ~/ros2_ws에 넣어줘". 설치 전에는 항상 dry-run으로 확인받습니다.

## 11. 저장소 구조

```
URDF-Studio/
├─ README.md  WINDOWS.md  CLAUDE.md
├─ docs/                        GitHub Pages 웹 버전
│  ├─ index.html  css/  js/     브라우저 전용 앱 (검증·메시 분석·zip 포트)
│  ├─ vendor/                   three.js, urdf-loader, JSZip (고정 버전)
│  ├─ samples/                  샘플 URDF
│  └─ local.html                로컬 서버 안내 페이지
├─ app/
│  ├─ main.py                   FastAPI 엔드포인트
│  ├─ schema.py                 명세 JSON·요청/응답 스키마
│  ├─ builder.py                명세 → URDF, 관성 계산, URDF → 명세
│  ├─ validator.py              URDF 검증
│  ├─ mesh_props.py             메시 물성 (trimesh)
│  ├─ llm.py                    Claude 호출과 수정 루프
│  ├─ ros_package.py            ROS 2 패키지 zip
│  ├─ storage.py                업로드·결과 저장
│  ├─ static/                   index.html, app.js, style.css
│  ├─ samples/                  샘플 URDF와 명세
│  ├─ tests/                    pytest
│  ├─ run.bat  run.ps1          Windows 실행기
│  └─ requirements.txt
├─ examples/freecad_demo/       FreeCAD→워크스페이스 데모
├─ output/                      예제 결과물
├─ _workspace/                  에이전트 작업 기록(QA 보고서 등)
└─ .claude/                     agents/, skills/ (하네스)
```

## 12. 테스트

```bash
cd app
python -m pytest -q          # 91 passed
```
Windows는 `.\.venv\Scripts\python -m pytest -q`.

## 13. 보안과 제한

- 업로드: 확장자 화이트리스트(stl/dae/obj), 파일당 20 MB, 파일명 정규화와 무작위 접두사, 해석 실패 파일 삭제.
- 경로 이탈 차단(정규식 + 디렉터리 내부 확인). JSON 본문 5 MB, URDF 2 MB, 업로드 총 200 MB 제한(초과 시 413).
- 서버는 `127.0.0.1`에만 바인딩되며 Host 헤더 허용 목록을 사용합니다. 외부에 노출하지 마세요.
- CDN 모듈 11개는 import map의 SRI(sha384)로 검증합니다. 버전을 올리면 `app/static/index.html`의 해시를 다시 계산해야 합니다.

## 14. 검증 상태와 알려진 한계

**실행해 확인한 것**: 앱 테스트 91개 통과, 샘플 검증, 메시 업로드, URDF/ZIP 다운로드, 설치 스크립트(설치·중복 방지·`--force` 백업·검증 차단·메시 경로 재작성), 데모 전 과정.

**아직 확인하지 못한 것**
- `export_parts.py`, `create_demo_model.py`: 실제 FreeCAD에서 실행해 보지 않았습니다(문법 컴파일만 확인). 처음 실행 때 수정이 필요할 수 있습니다.
- 실제 Anthropic API 키로 한 생성 실행(가짜 클라이언트와 잘못된 키 응답까지만 확인).
- `colcon build`와 RViz 표시(ROS 2가 없는 환경에서 개발). `check_urdf`도 실행하지 않았습니다.
- Windows에서 `run.bat`을 직접 실행한 확인.

**한계**
- 기존 URDF를 "기반으로 수정"하면 명세로 가져오기 때문에 `<gazebo>`, `<transmission>`, `<ros2_control>`, mimic과 원래 관성값이 빠집니다(가정 목록에 표시). 보존하려면 편집기에서 직접 수정하세요.
- xacro 입력은 지원하지 않습니다. xacro를 먼저 URDF로 변환해 붙여넣으세요. 데모가 만드는 xacro는 네임스페이스와 속성만 얹은 최소 형태입니다.
- 뷰어는 깨진 parent/child 참조가 있으면 해당 조인트를 뺀 채 부분 렌더링합니다.
- 조인트 축·범위·밀도처럼 CAD에 없는 정보는 가정값이므로 반드시 확인하세요.

## 15. 문제 해결

| 증상 | 확인할 것 |
| --- | --- |
| `py`를 찾을 수 없음 | Python 설치 시 `py launcher` 체크 여부, 터미널 재시작 |
| 패키지 설치 실패 | 인터넷 연결, Python 3.11 이상인지. `app\.venv` 폴더를 지우고 다시 실행 |
| 3D 화면이 비어 있음 | 인터넷과 사내망의 jsDelivr 차단 여부. 브라우저 개발자도구 콘솔 확인 |
| 포트 사용 중 | `run.bat 8080` 또는 `.\run.ps1 -Port 8080`. 실행 페이지의 포트 칸도 같은 값으로 |
| 400 `invalid_host` | `URDF_APP_ALLOWED_HOSTS`에 접속 호스트명 추가 |
| 생성 버튼이 503 | `ANTHROPIC_API_KEY` 미설정. 설정 후 서버 재시작 |
| 메시가 너무 크거나 작게 보임 | 업로드 시 단위를 `자동` 대신 `mm`/`m`으로 명시 |
| 설치 스크립트가 중단 | 출력된 검증 error를 먼저 수정. 같은 패키지가 있으면 `--force` |
