# 04 QA 보고서: 웹 앱 (app/) + output/sample_robot.urdf

검증일 2026-10-21 · 검증자 urdf-qa · 코드 수정 없음 (결함은 담당 에이전트에게 넘김)

## 요약
| 구분 | 결과 |
| --- | --- |
| output/sample_robot.urdf (스킬 스크립트 `validate_urdf.py`) | **PASS** · error 0 · warn 0 |
| /api/validate: sample_robot.urdf | PASS (스크립트와 같은 결과) |
| /api/validate: broken_arm 및 깨진 URDF 15종 | 대부분 정상 검출. **검출 누락 4종** (E1~E3) |
| 백엔드 응답 ↔ app.js 필드 대조 | **일치** (불일치 0건, 아래 표) |
| index.html DOM id ↔ app.js `$()` 참조 | 일치 (누락 0) |
| pytest (`app/.venv`) | **18 passed** (2.02 s) |
| upload/download 경로 탐색·확장자·크기 제한 | 차단 정상. 보완 권장 사항 있음 (W1, W2, W5, W8) |
| API 키가 프런트에 노출되는지 | 노출 없음 (`/api/health`는 bool과 모델명만 반환하고, index.html·app.js에 키 없음) |
| 01_architect_spec.json ↔ RobotSpec | 그대로 넣으면 **실패(오류 39개)**. `builder.architect_to_spec()`로 변환하면 PASS이고 output URDF와 물리적으로 같음 |
| 서버 프로세스 | 검증 후 종료함 (포트 8771 해제, 남은 uvicorn 없음, 서버 로그에 500/Traceback 없음) |

**결론: error 4건, warn 12건. 핵심 기능은 동작한다. error 4건은 검증기가 비물리 값이나 잘못된 조인트를 PASS시키는 문제(E1~E3)와 zip의 package.xml이 깨지는 문제(E4)다.**

---

## 결함 목록

### error
| # | 담당 | 위치 | 원인 | 제안 수정 |
| --- | --- | --- | --- | --- |
| E1 | urdf-webapp-dev (스킬 스크립트도 같은 결함이므로 skill 담당에게도 공유) | `app/validator.py:155-168`, `.claude/skills/urdf-validation/scripts/validate_urdf.py:93-103` | `mass value='nan'`, `ixx/iyy/izz='nan'`이 **PASS** 판정됨(실측: `nan_inertia` → `PASS · error 0`). NaN 비교가 항상 False라서 `<=0` 검사와 삼각부등식 검사를 모두 통과한다. `inf`도 질량 검사를 통과한다. 물리엔진이 폭주하는 원인이 된다. | `math.isfinite()`가 False면 `질량이 0 이하` / `관성 값이 숫자가 아님` error로 처리. 원본 스크립트에도 같이 반영해 파리티를 유지 |
| E2 | urdf-webapp-dev (스크립트 공유) | `app/validator.py:119-127` | (a) revolute에 `lower='' upper=''`가 PASS: `is None` 검사는 빈 문자열을 통과시키고, `if lim.get("lower") and ...`는 빈 문자열이면 비교를 건너뛴다. (b) `effort='-5' velocity='abc'`가 PASS: effort/velocity는 존재 여부만 본다. | 빈 문자열도 누락으로 처리. lower/upper/effort/velocity를 모두 `_num()`으로 파싱해 숫자가 아니면 error, effort<0·velocity<0이면 error |
| E3 | urdf-webapp-dev | `app/validator.py:103-134` | 조인트 `type` 값을 검사하지 않는다. `type='bogus'`와 `type` 누락이 PASS로 나온다(실측). `<robot>` name 누락, `<link>` name 누락도 PASS. urdfdom/check_urdf는 이를 거부한다. | `type ∉ {revolute, continuous, prismatic, fixed, floating, planar}`이면 error. robot/link/joint `name` 누락은 error |
| E4 | urdf-webapp-dev | `app/ros_package.py:136` (`PACKAGE_XML.format(robot=robot)`) | robot 이름을 XML 이스케이프 없이 package.xml에 넣는다. `<robot name="x&lt;/description&gt;&lt;evil/&gt;">`로 받은 zip의 package.xml이 **파싱 불가**(실측: `mismatched tag: line 5`). colcon build가 실패한다. | `xml.sax.saxutils.escape(robot)`를 쓰거나 정규화된 `file_robot`을 사용 |

### warn
| # | 담당 | 위치 | 원인 | 제안 수정 |
| --- | --- | --- | --- | --- |
| W1 | webapp-dev | `app/main.py:85`, `app/storage.py:76` | `/api/validate`를 호출할 때마다 `data/artifacts/*.json`이 영구 저장된다. 프런트가 편집 중 700 ms마다 자동 검증하므로 무제한으로 쌓인다(실측: 호출 23회 → 23개 파일). 삭제/TTL이 없어 디스크 DoS 위험이 있다. | 같은 내용은 해시로 중복 제거, TTL 정리(예: 24 h), 개수 상한. 또는 다운로드 직전에만 저장 |
| W2 | webapp-dev | `app/main.py:38-45` | 본문 크기 제한이 Content-Length 헤더에만 의존한다. chunked 업로드(헤더 없음)는 미들웨어를 우회한다. 파일별 20 MB 초과는 결국 `failed`로 거부되지만(실측 21 MB chunked → failed), 그 전에 Starlette가 multipart 전체를 임시파일로 받아 둔다. 총량 제한이 없다. | 수신 바이트를 세는 ASGI 미들웨어로 200 MB에서 연결을 끊거나, 리버스 프록시 `client_max_body_size` 사용 |
| W3 | webapp-dev | `app/validator.py:169-176` | `package://`가 아닌 메시 경로(`file:///nonexist/x.stl`, 상대경로)는 존재 여부를 확인하지 않아 PASS(실측). RViz에서 빈 화면이 되는 가장 흔한 원인을 놓친다. | package:// 외 URI는 warn(`ROS 2에서 해석 불가 경로`)으로 보고. 상대경로는 mesh_root 기준으로 존재 확인 |
| W4 | webapp-dev | `app/main.py` (전역) | 라우팅 404/405는 FastAPI 기본 `{"detail": ...}`를 반환한다(실측 `/api/nope`, `GET /api/validate`). README의 "오류 응답은 모두 `{error, message}`"와 다르다. app.js는 `HTTP 404`로 대체 표시하므로 동작은 한다. | `StarletteHTTPException` 핸들러를 추가해 `{error, message}`로 통일 |
| W5 | webapp-dev | `app/main.py:99` | 업로드 `mass=nan`이 `<=0` 검사를 통과하고, mesh_props가 조용히 0.001 kg으로 대체한다(실측: status ok, warning `mass_fallback_0.001kg`). 사용자 입력 오류인데 400이 아니다. | `math.isfinite(mass)`가 아니면 400 `invalid_mass` (density도 같음) |
| W6 | webapp-dev | `app/static/app.js:377-386` | 다운로드를 `<a href>` 클릭으로 한다. artifact가 없으면(데이터 디렉터리 정리, URDF_APP_DATA 변경 등) 404 JSON이 파일로 저장되거나 화면이 이동하고, 오류 메시지가 표시되지 않는다. | `fetch` → `res.ok` 확인 → Blob 다운로드. 실패하면 재검증 후 재시도하거나 오류 표시 |
| W7 | webapp-dev | `app/static/index.html:10-18` | jsDelivr CDN 모듈을 SRI(무결성 해시) 없이 불러온다(버전은 고정). 공급망 위험이 있다. | importmap `integrity` 필드 사용 또는 three/urdf-loader를 `static/vendor/`에 포함 |
| W8 | webapp-dev | `app/storage.py:25,46`, `app/schema.py:16` (`re.match` + `$`) | `$`가 끝의 개행 앞에서도 매치되어 `"<id>\n"`과 `"x.stl\n"`이 정규식을 통과한다. 지금은 파일시스템에서 걸러져 404(실측 `%0A` → 404)라 악용은 안 되지만, 방어가 우연에 의존한다. | `re.fullmatch` 또는 `\Z` 사용 |
| W9 | webapp-dev | `app/schema.py` (`Origin`, `BoxGeometry` 등 float) | pydantic 기본값이 NaN/Inf를 허용한다. `visual_origin.xyz=[nan,...]`이면 URDF에 `nan`이 들어가는데 validator는 PASS, `size=[inf,1,1]`도 PASS(실측). Claude 도구 입력은 표준 JSON이라 실제 위험은 낮다. | `model_config = ConfigDict(extra="forbid", allow_inf_nan=False)` |
| W10 | webapp-dev | `app/main.py` (미들웨어 없음) | 인증과 Host 검사가 없다. 127.0.0.1에 바인드되어 있지만 DNS rebinding으로 외부 페이지가 `/api/generate`를 호출해 API 크레딧을 쓸 수 있다. text/plain CSRF는 422로 막히고(실측), CORS는 비활성. | `TrustedHostMiddleware(allowed_hosts=["127.0.0.1","localhost"])` |
| W11 | webapp-dev / architect | `app/builder.py:286-318`, `_workspace/01_architect_spec.json` | 형식이 다르다(아래 섹션). 변환기는 테스트에서만 쓰이고 API로 노출되지 않는다. `_AXIS_RPY[...]`는 `"x"/"y"/"z"` 외 값(`"-y"`, 벡터)에서 KeyError가 난다. | 둘 중 하나로 정한다: (a) architect가 RobotSpec 형식으로 출력, 또는 (b) 변환기를 공식 계약으로 문서화하고 알 수 없는 axis는 ValueError로 명확히 보고 |
| W12 | webapp-dev | `app/tests/test_app.py:110-113`, `_workspace/03_webapp_status.md:4`, `app/validator.py:4` | (a) architect 관성 비교가 **정렬한 대각값**만 비교해 축이 뒤바뀐 오류를 가린다. QA가 수동으로 회전 R·I·Rᵀ를 확인해 보니 실제로는 동일하다. (b) status 문서 요약은 "pytest 17개", 본문은 18개(실측 18). (c) validator docstring이 존재하지 않는 `tests/test_validator.py`를 가리킨다. | (a) inertial rpy로 회전한 전체 텐서를 비교. (b)(c) 문서 수정 |

---

## (1) 백엔드 응답 ↔ static/app.js 필드 대조
실제 응답 JSON(서버 기동 후 수집)과 app.js가 읽거나 보내는 필드를 하나씩 대조했다.

| 엔드포인트 | 백엔드 필드 (실측) | app.js 사용 (줄) | 결과 |
| --- | --- | --- | --- |
| GET /api/health | `ok, api_key_configured, model` | `h.api_key_configured`, `h.model` (395-399) | 일치 |
| GET /api/samples | `samples[]` | `s.samples` (404, 406) | 일치 |
| GET /api/samples/{n} | `name, urdf` | `res.urdf` (368, 408) | 일치 |
| POST /api/validate 요청 | `ValidateRequest{urdf, check_meshes}` | `{urdf, check_meshes:true}` (246) | 일치 |
| POST /api/validate 응답 | `validation{ok, summary, errors, warnings, issues[]}, artifact_id, robot_name` | `res.artifact_id`, `res.validation` → `v.ok, v.summary, v.issues` (247-263) | 일치 (`errors`/`warnings`/`robot_name`은 미사용, 문제없음) |
| Issue | `severity, where, message, suggestion, link` | `iss.severity, iss.where, iss.message, iss.suggestion, iss.link` (266-283) | 일치. `link`가 null(xml/tree)이어도 안전하게 처리 |
| POST /api/generate 요청 | `{prompt, meshes[], baseUrdf?}` | `{prompt, meshes, baseUrdf}` (299-300) | 일치 (camelCase `baseUrdf`까지 같음) |
| POST /api/generate 응답 | `urdf, spec, assumptions, validation, artifact_id, attempts[{attempt,status,detail}], model` | `res.urdf, artifact_id, validation, assumptions, model, attempts[].status/.detail` (306-317) | 일치 (`spec`은 미사용) |
| POST /api/upload 요청 | multipart `files`, `unit`, `mass`, `density` | `files`, `unit`, `mass` (348-350) | 일치 (`density`는 UI에 없음, 정보) |
| /api/upload, /api/meshes 응답 | `meshes[MeshProps]` 14개 필드 | `status, original_name, error, stored_name, bbox_m, mass_kg, unit_guess, warnings` (331-338) | 일치. status=ok일 때 `mass_kg`/`unit_guess`는 항상 채워짐(mesh_props.analyze 확인) → `toFixed` 안전 |
| 오류 | `{error, message[, detail]}` | `body.message`, `body.error` (23-24) | 일치. 단 프레임워크 404/405는 `{detail}`이다(W4) |
| 메시 서빙 | `/api/pkg/{pkg}/meshes/{file}` | `loader.packages = pkg => /api/pkg/${pkg}` (101) → `package://pkg/meshes/f` | 경로 일치 (업로드 메시 GET 200, 바이트 동일 확인) |
| 다운로드 | `/api/download/{id}?format=urdf|zip` | 같음 (384) | 일치 |

XSS: app.js는 서버 값을 모두 `textContent`로 넣는다. `innerHTML`은 비우는 용도(`''`)로만 쓴다. 문제 없음.

## (2) 서버 실기동 결과 (uvicorn 127.0.0.1:8771, URDF_APP_DATA=스크래치 디렉터리)
- validate: sample_robot PASS. broken_arm `FAIL · error 6 · warn 1`(스크립트와 같음). 구문 오류, 루트가 robot이 아닌 경우, 빈 문자열(artifact_id=null), 없는 child(`link: "ghost"`), parent 요소 누락, 메시 경로 탐색(`package://p/../../../../Windows/win.ini` → 메시 없음 error), 미업로드 메시는 모두 정상 검출. billion laughs와 XXE는 expat이 차단(구문 오류 처리, 0.07 s).
- **검출 누락**: NaN 관성/질량, 빈 limit, 음수 effort·숫자 아닌 velocity, 잘못되거나 없는 조인트 type, 이름 누락, file:// 메시 (E1~E3, W3).
- 요청 검증: 필드 누락, 타입 오류, JSON 아님, 2,000,001자 → 422 `invalid_request`. 5 MB 초과 본문 → 413.
- download: urdf(본문이 원본과 같음), zip(7개 항목, 업로드 메시 포함 및 package:// 재작성). `../../main.py`, `..%2F`, `%2e%2e%5c`, 대문자 id, `%0A` 접미 → 404. `format=exe` → 400. 악성 robot name은 Content-Disposition과 zip 경로에서 `[A-Za-z0-9_-]`로 정규화(경로 이탈 없음). 단 package.xml 본문은 깨짐(E4).
- upload: `../../..\evil name.STL` → `b74baf04_evil_name.stl`. `.exe`, `.stl.exe`, 확장자 없음 → failed. 쓰레기 내용의 `.stl` → 해석 실패 후 삭제. 빈 파일 → failed. `.stl`(이름 없음) → `xxxx_mesh.stl`. unit=cm → 400. mass=-1 → 400. 11개 → 400. 20 MB+ (Content-Length 있음/없음 둘 다) → failed. mass=nan → 조용히 대체(W5).
- 메시/샘플/정적 경로 탐색: `/api/pkg/x/meshes/..%2F..`, `..%5C..`, `*.props.json`, `/api/samples/..%2Fmain`, `/static/../main.py` → 모두 404.
- generate: 키 없음 503 `missing_api_key`, 잘못된 메시 이름 422, 미업로드 메시 400 `mesh_not_found`, 빈 prompt 422.

## (3) pytest
`app/.venv/Scripts/python -m pytest -q` → **18 passed in 2.02s**. 파리티 테스트로 스킬 스크립트 결과와 일치함을 확인. 단 파리티 대상이 샘플 3개뿐이라 E1~E3 같은 경계 입력은 다루지 않는다.

## (4) 보안
- API 키: `llm.py`는 `os.environ`에서만 읽는다. `/api/health`는 `api_key_configured`(bool)와 `model`만 반환한다. index.html·app.js·응답 어디에도 키 값이 없다. Anthropic 오류는 고정 메시지로 매핑(`api_error`는 SDK 메시지를 포함하지만 키는 포함하지 않음). **통과**.
- 업로드/다운로드 입력 검증: 통과. 보완 권장은 W1, W2, W5, W8, W10.
- XML 파서: stdlib ElementTree(expat 2.6+ 증폭 제한)로 billion laughs와 XXE가 차단됨을 확인. 더 강한 방어를 원하면 defusedxml(선택).

## (5) 01_architect_spec.json ↔ RobotSpec
`RobotSpec.model_validate(architect)` → **오류 39개**:
- 최상위: `robot_name` 누락(architect는 `robot`). `robot, description, units, root_link, parameters, tree`는 extra_forbidden.
- 링크 9개: `inertial_origin`, `inertia`, `formula`는 extra_forbidden. 실린더 6개의 `geometry.axis`("y"/"z")도 extra_forbidden.
- 조인트: 형식 동일(오류 0).

`builder.architect_to_spec()`로 변환 → build → validate: **PASS · error 0 · warn 0**. 조립 결과를 `output/sample_robot.urdf`와 요소별로 비교했다:
- 링크와 조인트 집합, 조인트 origin/axis/limit, 박스·구 링크는 같다.
- 바퀴 4개: output은 inertial rpy=0에 `iyy=mr²/2`, app은 inertial rpy=(π/2,0,0)에 `izz=mr²/2`. 회전 변환하면 **물리적으로 같다**(QA 수동 확인).
- base_link 관성: output이 6자리 반올림(`0.152083`)이라 rel 2e-6 차이. 무시해도 된다.
- 결론: 데이터는 호환되지만 계약(스키마)은 두 개다(W11).

수동 확인(스킬 절차 3): 바퀴 실린더 visual/collision rpy=1.5708(축 y)과 continuous axis `0 1 0`이 일치한다. 팔 링크 visual이 COM(z+L/2)에 놓이고 조인트 원점이 링크 하단이라 서로 맞는다. 모든 링크에서 collision이 visual과 같은 원시형상이라 대체 가능하다.

## 건너뛴 검사
| 검사 | 이유 |
| --- | --- |
| `check_urdf`, `urdf_to_graphviz` | ROS 2 미설치 (`which` 결과 없음) |
| `xacro` 변환 후 `output/sample_robot.urdf.xacro` 검증 | xacro 미설치. 전개된 `.urdf`만 검증 |
| zip 패키지 `colcon build` / `ros2 launch` | ROS 2 미설치 |
| 실제 Claude 생성 E2E | ANTHROPIC_API_KEY 없음 (503 경로만 확인) |
| 브라우저 UI E2E (뷰어 렌더, 하이라이트, 슬라이더) | QA에서 브라우저를 구동하지 않음. 필드 대조는 정적 분석과 실제 응답 JSON으로 수행. 03_webapp_status의 puppeteer 결과는 재현하지 않음 |
| DAE/OBJ 업로드 실측 | QA는 STL만 실측. OBJ/DAE는 webapp-dev 보고에 의존 |
| chunked 업로드 시 임시파일 디스크 사용량 측정 | 코드 구조로 판단(W2). 수치 측정은 하지 않음 |
