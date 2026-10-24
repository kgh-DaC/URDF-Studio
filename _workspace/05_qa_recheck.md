# 05 QA 재검증: 04_qa_report.md E1~E4, W1~W12 반영 여부

검증일 2026-10-23 · 검증자 urdf-qa · 코드 수정 없음

## 요약
| 구분 | 결과 |
| --- | --- |
| E1~E4 | **4/4 PASS** |
| W1~W12 | **12/12 PASS** (W2·W7은 참고 사항 있음) |
| pytest (`app/.venv`) | 처음 실행 **72 passed** (3.35 s). 재검증 중 다른 에이전트가 `app/builder.py`와 `app/tests/test_app.py`를 수정(15:24)한 뒤 다시 실행하니 **74 passed** (3.11 s). 03 문서의 "W11 테스트 교체 후 74 passed"와 같음 |
| 실서버 재현 | uvicorn 127.0.0.1:8781, `URDF_APP_DATA`=스크래치 임시 디렉터리, API 키 없음. 서버 로그에 500/Traceback 0건 |
| 앱 ↔ 스킬 스크립트 파리티 | 경계 입력 24종에서 summary가 모두 일치. 예외는 W3(앱 전용 warn)과 mesh_root 유무에 따른 메시 존재 검사로, 둘 다 의도된 차이 |
| 서버 종료 | PID 45492 종료, 8781 포트 리스닝 없음. 임시 데이터 디렉터리 삭제 |
| 새 결함 | **warn 3건, info 1건** (N1~N4). error 없음 |

---

## 항목별 결과

### error
| # | 결과 | 재현 입력 → 실측 (/api/validate, 스크립트 summary 동일) |
| --- | --- | --- |
| E1 | **PASS** | mass `nan`/`inf`/`-inf`/`abc`/`""` → 모두 `FAIL · error 1` `arm_link · 질량 값이 숫자가 아님`. ixx `nan`/`inf` → `관성 값이 숫자가 아님`. 스킬 스크립트도 같은 결과(rc=1). 단 비대각 성분은 검사하지 않음(N1) |
| E2 | **PASS** | `lower="" upper=""` → error 2 (`limit/lower 누락`, `limit/upper 누락`). `effort=-5 velocity=abc` → `limit/velocity 값이 숫자가 아님`, `limit/effort가 음수`. `lower=nan` → 숫자 아님. prismatic `effort=""` → 누락. continuous `velocity=-1` → 음수. `lower>upper` → `lower >= upper` |
| E3 | **PASS** | `type="bogus"`, `type="Revolute"`(대소문자) → `알 수 없는 조인트 type`. type 속성 없음 → `조인트 type 누락`. `floating`(limit 없음) → PASS. robot name 없음 → `robot · robot name 누락`. link name 없음 → `link[1] · 링크 name 누락`. joint name 없음 → `joint[0] · 조인트 name 누락` |
| E4 | **PASS** | `<robot name="x&lt;/description&gt;&lt;evil/&gt;">` → zip 200. package.xml이 정상 파싱되고 description 텍스트는 `URDF description for x</description><evil/> ...`(이스케이프됨), `<evil>` 요소는 없음. 추가로 이름 `1bad name`, `x]]&gt;`, `&#x0D;`도 package.xml 파싱 성공, launch.py `compile()` 성공, zip 항목에 `..`나 절대경로 없음. Content-Disposition은 `[A-Za-z0-9_-]`로 정규화됨 |

### warn
| # | 결과 | 실측 / 확인 |
| --- | --- | --- |
| W1 | **PASS** | 같은 URDF로 validate 20회 → artifact_id 1종, 파일 수 33 → 33(증가 없음). dedup id로 다운로드 200. 인프로세스(`URDF_APP_MAX_ARTIFACTS=3`, `TTL_S=1`): 서로 다른 6개 저장 → 3개 남고 최신 것 유지. 1.5 s 뒤 저장 → 만료분 삭제되어 1개만 남음 |
| W2 | **PASS** (참고) | curl chunked 7 MB `/api/validate` → **413** `payload_too_large (최대 5 MB)`. curl chunked 220 MB multipart `/api/upload` → **413** (최대 200 MB, 0.49 s). 작은 chunked 요청은 200으로 정상 처리. 업로드 디렉터리에 잔여 파일 없음. 참고: httpx 클라이언트로 같은 요청을 보내면 서버 로그에는 413이 찍히지만 클라이언트는 `WinError 10054`(연결 리셋)를 받는다. 서버가 본문을 다 읽기 전에 `connection: close`로 응답하고 끊어서 생기는 TCP 동작이다. 차단 자체는 정상이고 결함으로 보지 않는다 |
| W3 | **PASS** | `file:///nonexist/x.stl`, `meshes/x.stl`, `filename=""` → 각각 `warn · package://가 아닌 메시 경로` (빈 값은 `(빈 값)`으로 표시). `package://p/meshes/nope.stl` → error `메시 파일 없음`. 스크립트에는 넣지 않았음(문서와 같음) |
| W4 | **PASS** | `GET /api/nope` 404, `GET /static/nope.js` 404 → `{"error":"not_found",...}`. `GET /api/validate`, `DELETE /api/health` 405 → `{"error":"method_not_allowed",...}`. 단 TrustedHost 400은 형식이 다름(N3) |
| W5 | **PASS** | upload mass `nan`/`NaN`/`inf`/`-inf`/`0`/`-1`, density `nan` → 모두 400 `invalid_mass`. `abc` → 422 `invalid_request` |
| W6 | **PASS** (정적 확인) | `app.js:378-407`: fetch → `res.ok` → Blob + `createObjectURL` → `revokeObjectURL`. 첫 시도가 404면 `artifactId=null`로 두고 재검증 후 1회 재시도, 그 밖의 실패는 서버 `message`를 alert로 표시. 브라우저 E2E는 재현하지 않음 |
| W7 | **PASS** (참고) | importmap `integrity` 11개를 jsDelivr에서 실제로 받아 sha384를 계산해 보니 **11/11 일치**. 모듈들의 전이 import(three.core, TGALoader, collada/ColladaParser·ColladaComposer, URDFClasses)도 모두 목록에 있음. 한계(importmap integrity 미지원 브라우저)는 03 문서에 명시됨 |
| W8 | **PASS** | `/api/download/<id>%0A`(format 있음/없음), `/api/pkg/x/meshes/a.stl%0A`, `/api/samples/two_link_arm%0A` → 모두 404. generate `meshes:["abcd_x.stl\n"]` → 422(pydantic 패턴 거부). 코드에 `re.match` + `$` 형태로 남은 검사 없음(`builder.py:31`의 `^[a-z]` 접두 검사는 영향 없음) |
| W9 | **PASS** | `RobotSpec.model_validate_json`에서 box size `NaN`/`Infinity` → validation error. `_Strict.model_config`에 `allow_inf_nan=False` |
| W10 | **PASS** | Host `evil.example.com`, `127.0.0.1.nip.io` → 400. `POST /api/generate`에 Host evil → 400(라우트 도달 전 차단). `127.0.0.1:8781`, `localhost:8781`, `LOCALHOST` → 200 |
| W11 | **PASS** | `architect_to_spec`에 axis `-y`, `[0,1,0]`, `None`, `w` → 모두 `ValueError: ... geometry.axis must be 'x', 'y' or 'z'`. 현재 `_workspace/01_architect_spec.json`과 `01_architect_spec.robotspec.json`은 `RobotSpec.model_validate` → build → validate 모두 `PASS · error 0 · warn 0`. 재검증 중 `architect_to_spec`에 RobotSpec 형식 입력을 거부하는 검사가 추가됨(`builder.py:302`) |
| W12 | **PASS** | (a) `test_architect_spec_converts_builds_and_inertia_agrees`가 `inertia_in_parent`(R·I·Rᵀ)로 계산한 링크 좌표계 텐서의 대각을 비교하고 비대각≈0도 확인함 (b) 03 문서의 pytest 개수가 실측(72 → 74)과 일치 (c) `validator.py` docstring이 실재하는 `test_validator_matches_skill_script`, `test_validator_parity_edge_cases`를 가리킴 |

---

## 새 결함 (담당: urdf-webapp-dev, N1은 스킬 스크립트에도 공유)
| # | 심각도 | 위치 | 원인 | 제안 수정 |
| --- | --- | --- | --- | --- |
| N1 | warn | `app/validator.py:201-211`, `.claude/skills/urdf-validation/scripts/validate_urdf.py` (같은 로직) | 관성 비대각 성분(ixy/ixz/iyz)은 파싱하지 않는다. `ixy="nan"`인 URDF가 **PASS · error 0**(앱과 스크립트 모두 실측). E1과 같은 종류의 NaN 누수로, 물리엔진에 NaN이 들어간다 | `ixy/ixz/iyz`도 `_num()`으로 파싱해 None이면 `관성 값이 숫자가 아님`. 필요하면 양의 정부호 검사(고유값 > 0)까지 추가. 양쪽 모두 반영하고 파리티 케이스에 추가 |
| N2 | warn | `app/validator.py:107,135-139` | 이름 없는 링크가 있으면 `names`에 `None`이 들어간다. 그러면 `<parent>` 요소가 없는 조인트(p=None)가 `None in names`로 통과해 `parent 링크 'None'가 존재하지 않음`이 **빠진다**(실측: 이름 없는 링크 + parent 요소 없음 → 링크 name 누락, child 없음, 루트 2개만 보고). 루트 목록에도 `None`이 그대로 표시된다(`['base_link', None]`). 다른 오류와 함께 나와 FAIL 판정은 유지되므로 영향은 작다 | 존재 검사를 `link_names`(이름 있는 것만)로 하고, parent/child 요소가 없으면 `parent 요소 누락` 같은 별도 메시지를 낸다. roots 계산에서 None은 제외하거나 `link[i]`로 표시. 스크립트도 같이 반영 |
| N3 | warn | `app/main.py:48` (TrustedHostMiddleware) | 잘못된 Host 요청은 Starlette 기본 응답인 `400 text/plain "Invalid host header"`로 나간다. README의 "오류 응답은 모두 `{error, message}`" 규칙(W4에서 통일)과 다르다. 브라우저 정상 사용에서는 발생하지 않으므로 실사용 영향은 낮다 | 작은 ASGI 래퍼 또는 TrustedHostMiddleware 서브클래스로 `{"error":"invalid_host","message":...}` JSON 400을 반환 |
| N4 | info | `_workspace/03_webapp_status.md`, `app/builder.py`, `app/tests/test_app.py` | 재검증 도중(15:24~15:25) 다른 에이전트가 위 파일들을 수정했다(pytest 72 → 74). 이번 결과는 수정 전후 모두 통과했지만, QA가 시작한 뒤 바뀐 코드는 pytest와 W11 인프로세스 확인만 다시 했다. 실서버 재현은 수정 전 코드로 띄운 서버에서 했다(바뀐 부분은 `architect_to_spec`뿐이고 HTTP 경로에서는 쓰이지 않음) | 수정 작업과 QA 실행 시점을 조정자가 순서대로 맞춘다 |

## 건너뛴 검사
| 검사 | 이유 |
| --- | --- |
| `check_urdf`, `xacro`, `colcon build`, `ros2 launch` | ROS 2 미설치 |
| 실제 Claude 생성 E2E | ANTHROPIC_API_KEY 없음 |
| W6·W7 브라우저 실동작(Blob 저장, SRI 변조 시 차단) | 브라우저를 구동하지 않음. 코드 정적 확인과 CDN 해시 재계산으로 대신함 |
| chunked 업로드 중 Starlette 임시파일의 디스크 사용량 | 측정하지 않음(03 문서의 남은 항목과 같음. 총량 200 MB 상한만 실측) |
| Host 헤더가 비어 있거나 없는 HTTP/1.0 요청 | httpx/curl이 Host를 자동으로 붙여 재현하지 않음 |
