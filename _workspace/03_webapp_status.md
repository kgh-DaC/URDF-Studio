# 03 웹 앱 상태 (2026-10-21)

## 요약
`app/` 구현 완료. 서버 기동, `/api/validate` 정상/깨진 URDF, 메시 업로드(stl/obj/dae), URDF/zip 다운로드, 키 없을 때 generate 오류, 브라우저 UI(뷰어·슬라이더·검증 패널 하이라이트·편집기)를 실제로 실행해 확인. pytest는 최초 구현 시 18개, QA 수정 후 72개, 2026-10-23 W11 테스트 교체 후 **74개 모두 통과**(아래 "QA 수정 내역").
**미검증: 실제 유효한 API 키로 Claude 생성 1회 실행** (이 환경에 ANTHROPIC_API_KEY 없음). 생성 루프는 가짜 클라이언트 테스트와 잘못된 키로 실제 API 호출(401 → `invalid_api_key` 매핑)까지 확인.

## 모듈별 실행 확인
| 모듈 | 확인 방법 | 결과 |
| --- | --- | --- |
| schema.py | JSON Schema 생성, `$ref` 인라인 | OK (6.4 KB, $ref 없음) |
| validator.py | 샘플 3종을 원본 `validate_urdf.py`(python -I)와 비교 | 요약·이슈 완전 일치 (pytest로 고정) |
| builder.py | 샘플 명세 → URDF → 검증, 관성 공식, axis 정규화, continuous 기본 limit, URDF→명세 왕복 | PASS · error 0 · warn 0 |
| mesh_props.py | trimesh로 만든 box(mm).stl / cyl.obj / sphere.dae | 단위 추정(mm→0.001), 박스 ixx 공식과 일치 |
| storage/upload | `.exe` 거부, 손상 stl 거부·삭제, `../../etc/bad.stl` 파일명 정규화, 경로 이탈 3종 404 | OK |
| llm.py | FakeClient: 1차 limit 누락 → tool_result(is_error) 되먹임 → 2차 성공 / 계속 실패 시 3회 호출 후 중단 / 키 없음 503 / 잘못된 키 실제 호출 → 502 invalid_api_key / 깨진 baseUrdf 422 | OK |
| ros_package.py | zip 구조 (package.xml, CMakeLists.txt, urdf/, meshes/, launch/display.launch.py, rviz/), 업로드 메시 포함 및 package:// 이름 재작성 | OK |
| main.py (curl) | health, samples, validate(정상: PASS / broken_arm: FAIL error 6 warn 1 / 구문오류 / 루트 비robot / 필드 누락 422), generate 503, download urdf·zip·잘못된 format 400·없는 id 404 | OK |
| 프런트 (headless Edge + puppeteer-core) | 샘플 자동 로드·렌더(링크5·조인트4), 슬라이더 3개 동작, broken_arm FAIL 7개 이슈, 이슈 클릭 → arm_link 하이라이트 + 편집기 선택, 편집 후 자동 재검증(error 6→5), STL/OBJ/DAE 메시 렌더, generate 버튼 → missing_api_key 메시지 | OK (콘솔 오류는 의도된 503 하나뿐) |
| run.ps1 | `powershell -ExecutionPolicy Bypass -File run.ps1 -Port 8770` 후 curl 정상/깨진 URDF | OK |

## 01_architect_spec.json 호환성
(2026-10-23 갱신) 현재 `01_architect_spec.json`은 이미 **RobotSpec 형식**(`robot_name`, 링크별 `visual_origin`)이다. 초기에는 구형 형식(`robot` 키, 실린더 `geometry.axis`, 미리 계산된 `inertia`/`inertial_origin`)이었고 이를 위해 `builder.architect_to_spec()` 변환기를 두었다.
이전 테스트는 RobotSpec 형식이 된 파일을 계속 `architect_to_spec()`에 넣고 있었다. 이 경우 `visual_origin`(바퀴 rpy 1.5708 등)이 조용히 버려지고, 구형 `inertia`가 없어 관성 비교 루프가 0회 돌면서도 통과했다. 따라서 "9개 링크 관성 일치"라는 이전 서술은 실제로 검증되지 않은 상태였다.
수정 내용:
- `test_architect_spec_builds_and_matches_reference_urdf`: `RobotSpec.model_validate` → `build_urdf` → 검증 PASS를 확인한다. 그다음 `output/sample_robot.urdf`와 링크별 mass, inertial xyz, `builder.inertia_in_parent`(R·I·Rᵀ)로 링크 좌표계에 맞춘 전체 텐서 6성분을 비교한다(허용오차 rel 1e-5 × 최대 성분. 기준 파일 값이 유효숫자 약 6자리이고 rpy가 1.5708 ≠ π/2이기 때문). **비교한 링크 수 == 9**를 assert한다. 바퀴의 visual_origin rpy를 0으로 바꾸면 이 테스트가 실패하는 것도 확인했다.
- `architect_to_spec()`은 RobotSpec 입력(`robot_name` 키 또는 어떤 링크든 `visual_origin`)이 들어오면 `ValueError("input is already RobotSpec format ...")`를 낸다. 회귀 테스트는 `test_architect_to_spec_rejects_robotspec_input`이다.
- 구형 형식 변환은 테스트 안의 구형 픽스처(`_legacy_fixture`: box, y축·z축 실린더, inertial_origin이 있는 box)로 계속 검증한다. 대상 테스트는 `test_architect_legacy_format_converts_builds_and_inertia_agrees`이며, 변환 → 조립 → 검증 PASS(warn 0)를 확인하고 4개 링크 전부 전체 텐서를 비교한다(비교 개수 assert 포함).
- 현재 pytest: **74 passed**.

## 실행 중 발견·수정한 문제
1. `packaging.py` 모듈명이 PyPI `packaging`을 가림 → `ros_package.py`로 변경.
2. urdf-loader 0.13.1이 존재하지 않는 parent 링크 참조에서 예외(`processJoint ... reading 'add'`) → 깨진 URDF가 렌더되지 않아 하이라이트 불가. 깨진 조인트만 제외하고 부분 렌더하도록 수정(뷰어에 "부분 렌더" 표시).
3. 뷰어 상태 메시지가 메시 로드 완료 시 지워짐 → 정보 유지.
4. 파리티 테스트: `python -I`는 PYTHONIOENCODING을 무시해 cp949 출력 → `-X utf8` 추가.
5. Claude 응답 블록을 되돌려 보낼 때 응답 전용 필드가 섞이지 않도록 최소 블록(tool_use/text)으로 재구성.

## 알려진 제한 / 후속 확인 필요
- 실제 키로 생성 E2E 미실행 → 키 있는 환경에서 샘플 프롬프트("바퀴 2개와 캐스터, 라이다가 있는 차동구동 로봇") 1회 확인 필요. 특히 모델 ID `claude-sonnet-5-5`가 계정에서 유효한지(`model_not_found`로 명확히 보고됨).
- "기반으로 수정"은 URDF→명세 변환이므로 gazebo/transmission/ros2_control/mimic/원래 관성값이 빠진다(assumptions에 `[import]`로 표시). 보존이 필요하면 편집기 직접 수정.
- trimesh가 내보낸 테스트 DAE는 재질이 없어 뷰어에서 검게 보임(로더 동작은 정상).
- ROS 2 미설치로 `check_urdf`, `colcon build`, `ros2 launch`로 zip 패키지 실검증은 못 함.
- 검증의 tree 오류(루트 2개)는 특정 링크 하이라이트가 없음(`link: null`).

## 쓸 수 있었던 도구
| 도구 | 상태 |
| --- | --- |
| Python 3.12.10 (+ venv `app/.venv`) | 사용 |
| pip 패키지: fastapi 0.153.0, uvicorn 0.54.0, python-multipart 0.0.32, pydantic 2.14.1, anthropic 1.15.0, trimesh 5.1.1, numpy 2.5.4, pycollada, pytest 9.1.1, httpx 0.28.1 | venv에 설치해 사용 (scipy 없음 → trimesh 내보내기 시 경고만) |
| Node.js v24 / npm, puppeteer-core 24 (scratchpad에 설치) | 브라우저 E2E에 사용 |
| Microsoft Edge (headless, SwiftShader WebGL) | UI 확인·스크린샷 |
| curl, PowerShell, Git Bash | 사용 |
| jsDelivr CDN (three@0.186.1, urdf-loader@0.13.1, 모든 모듈 URL 200 확인) | 사용 |
| ANTHROPIC_API_KEY | **없음** |
| claude-api 스킬 | **찾지 못함** (프로젝트·사용자·플러그인 스킬 디렉터리 모두 없음). 설치된 anthropic SDK의 `messages.create` 시그니처를 직접 확인하고 강제 tool_choice 방식으로 작성 |
| ROS 2 (ros2, check_urdf, xacro), Chrome | 없음 |

---

## QA 수정 내역 (04_qa_report.md 대응, 2026-10-21)
담당 범위: E1~E4, W1~W10, W12 + W11 결정 반영. 각 항목에 회귀 테스트를 추가했다. 최종 결과는 `pytest -q` **72 passed**(2026-10-23 W11 테스트 교체 후 74 passed).

| # | 수정 | 파일 | 회귀 테스트 / 실측 |
| --- | --- | --- | --- |
| E1 | 질량·관성·axis 값을 `math.isfinite`로 검사. nan/inf/문자 질량 → `질량 값이 숫자가 아님`, nan/inf 관성 → `관성 값이 숫자가 아님`. 원본 스크립트는 문자 질량에서 예외로 죽던 문제도 함께 수정 | `app/validator.py`, `.claude/skills/urdf-validation/scripts/validate_urdf.py` | `test_validator_edge_cases`, `test_validator_parity_edge_cases`(16개 경계 입력에서 스크립트와 앱 출력이 일치) |
| E2 | 빈 문자열 limit 속성은 누락으로 처리. limit 속성은 조인트 type과 관계없이 모두 숫자로 파싱해 `limit/<k> 값이 숫자가 아님`, effort/velocity 음수면 `limit/<k>가 음수` 오류 | 위와 같음 (양쪽 모두) | 같음 |
| E3 | 조인트 type 누락 또는 허용 목록(revolute/continuous/prismatic/fixed/floating/planar) 밖이면 오류. robot/link/joint name 누락 오류(위치 표기 `link[i]`, `joint[i]`) | 위와 같음 (양쪽 모두) | 같음 |
| E4 | package.xml의 robot 이름을 `xml.sax.saxutils.escape` 처리 | `app/ros_package.py` | `test_zip_package_xml_escapes_robot_name` (악성 이름에도 package.xml 파싱 성공) |
| W1 | 아티팩트 id를 내용 해시(sha256 앞 32자)로 바꿔 중복 제거. 저장할 때마다 TTL 24 h와 개수 상한 500 정리(env로 조정 가능) | `app/storage.py` | `test_artifacts_dedup_and_prune` |
| W2 | 실제 수신 바이트를 세는 ASGI 미들웨어 `limits.BodyLimitMiddleware`로 교체(chunked 포함, 초과하면 413) | `app/limits.py`, `app/main.py` | `test_body_limit_chunked`. 실측: curl chunked 7 MB → 413 |
| W3 | `package://`가 아닌 메시 경로(file://, 상대, 빈 값)는 warn. 앱 전용 확장이라 스크립트에는 넣지 않음 | `app/validator.py` | `test_validator_warns_non_package_mesh` |
| W4 | `StarletteHTTPException` 핸들러로 404/405도 `{error, message}` 형식 | `app/main.py` | `test_framework_errors_use_error_format`. 실측: `/api/nope` 404 not_found, `GET /api/validate` 405 method_not_allowed |
| W5 | 업로드 mass/density가 nan/inf/≤0이면 400 `invalid_mass` | `app/main.py` | `test_upload_rejects_non_finite_mass`. 실측: mass=nan → 400 |
| W6 | 다운로드를 fetch → res.ok 확인 → Blob 저장으로 변경. 404면 재검증 후 1회 재시도, 그 밖의 실패는 메시지로 표시 | `app/static/app.js` | headless Edge: urdf·zip 다운로드 성공. 아티팩트 파일을 지운 뒤 클릭하면 서버 로그상 `download 404 → validate 200 → download 200` |
| W7 | import map `integrity`로 실제 로드되는 CDN 모듈 11개 전부에 SRI sha384 적용 | `app/static/index.html` | headless Edge: 정상 로드됨. 해시 1개를 변조하면 "Failed to find a valid digest ... blocked"로 차단됨을 확인 |
| W8 | 정규식 검사를 `re.fullmatch`로 바꿈(storage, schema validator, builder, main) | 여러 파일 | `test_regex_no_trailing_newline` |
| W9 | `_Strict`에 `allow_inf_nan=False` 지정 | `app/schema.py` | `test_schema_rejects_nan_inf` |
| W10 | `TrustedHostMiddleware`, 기본 `127.0.0.1,localhost`(env `URDF_APP_ALLOWED_HOSTS`로 변경) | `app/main.py` | `test_trusted_host`. 실측: Host evil.example.com → 400 |
| W11 | **RobotSpec을 표준 명세로 확정**. `architect_to_spec()`은 호환용으로 유지. x/y/z가 아닌 axis(`"-y"`, 벡터, None 등)는 KeyError 대신 `ValueError("... geometry.axis must be 'x', 'y' or 'z' ...")` | `app/builder.py`, README | `test_architect_bad_axis_is_clear_error`, `test_architect_axis_maps_to_rotation` |
| W12 | (a) architect 관성 비교를 정렬한 대각값 대신 inertial rpy로 회전한 전체 텐서 R·I·Rᵀ로 비교(`builder.inertia_in_parent`), 비대각 성분≈0도 확인 (b) 이 문서의 pytest 개수 수정 (c) validator docstring이 실제 테스트 이름을 가리키도록 수정 | `app/builder.py`, `app/tests/test_app.py`, `app/validator.py` | (2026-10-23 교체) 원래 테스트는 비교가 0회 실행된 채 통과했다. 지금은 `test_architect_spec_builds_and_matches_reference_urdf`(9개 링크 전체 텐서, 개수 assert)와 `test_architect_legacy_format_converts_builds_and_inertia_agrees`가 이 역할을 맡는다 |

### 서버 실측 (uvicorn 127.0.0.1:8772, 임시 데이터 디렉터리, 키 없음)
| 입력 (/api/validate) | 결과 |
| --- | --- |
| 정상 2링크 | PASS · error 0 · warn 0 |
| E1 mass="nan" | FAIL · error 1 (`arm_link: 질량 값이 숫자가 아님`) |
| E1 mass="inf" | FAIL · error 1 (같은 메시지) |
| E2 lower="" upper="" | FAIL · error 2 (`j1: limit/lower 누락`, `j1: limit/upper 누락`) |
| E3 type="bogus" | FAIL · error 1 (`j1: 알 수 없는 조인트 type 'bogus'`) |
검증 후 서버를 종료했다(8765/8766/8770/8771/8772 포트 모두 리스닝 없음). 임시 데이터도 삭제했다.

### 남은 미해결 항목
- W11 후속: `01_architect_spec.json`은 이미 RobotSpec 형식이므로 `RobotSpec.model_validate`로 직접 읽는다. `architect_to_spec()`은 구형 형식 전용이며 RobotSpec 입력을 거부한다. urdf-authoring 스킬 문서를 RobotSpec에 맞추는 일은 urdf-architect 담당이다.
- W7 한계: import map `integrity`를 지원하지 않는 브라우저(구형 Firefox/Safari)는 검증 없이 로드한다. 완전히 막으려면 `static/vendor/`에 모듈을 포함해야 하지만, 요구사항(CDN 버전 고정)에 따라 CDN을 유지했다.
- W2: Starlette multipart가 200 MB까지는 임시파일로 받는다(총량 상한만 있음). 운영 환경에서는 리버스 프록시의 본문 상한을 같이 두는 것을 권장한다.
- QA 범위 밖: 실제 API 키로 생성 E2E, ROS 2(`check_urdf`/`colcon build`) 검증은 여전히 미실행(키·ROS 없음).
- 검증 tree 오류(루트 2개)에는 하이라이트할 링크가 없다(`link: null`). 기존과 같음.

## 05 QA 재검증 새 결함 수정 (2026-10-23)
| # | 수정 | 파일 | 회귀 테스트 |
| --- | --- | --- | --- |
| N1 | 관성 비대각 ixy/ixz/iyz도 `_num()`/`num()`으로 파싱. nan/inf/문자면 `관성 값이 숫자가 아님` error. 양의 정부호 검사는 넣지 않음 | `app/validator.py`, `.claude/skills/urdf-validation/scripts/validate_urdf.py` | `test_offdiag_inertia_not_a_number`, 파리티 케이스 `N1_nan_ixy`, `N1_inf_ixz_text_iyz`, `N1_offdiag_ok` |
| N2 | 존재·루트·사이클 검사를 이름 있는 링크(`named`)로만 수행해 `None`이 섞이지 않음. `<parent>`/`<child>` 요소가 없으면 `parent 요소 누락`/`child 요소 누락`, link 속성이 비면 `parent link 속성 누락`. 끝점이 비면 children/parent_of에 넣지 않음. 제안 문구 2개 추가 | 위 두 파일 | `test_missing_parent_child_reported_separately`, 파리티 케이스 `N2_unnamed_link_no_parent`, `N2_no_child`, `N2_empty_parent_attr` |
| N3 | `JSONTrustedHostMiddleware`(TrustedHostMiddleware 서브클래스): 호스트 판정은 Starlette 그대로 두고, 검사를 통과하지 못한 요청의 400 응답만 JSON `{"error":"invalid_host","message":...}`로 바꿈. 허용된 Host의 앱 400은 그대로 | `app/main.py` | `test_invalid_host_uses_error_format`(3개 케이스, 앱 400 `invalid_mass`가 바뀌지 않는지도 확인) |

pytest (`app/.venv`): **91 passed** (3.61 s). 이전 74개 + 새 테스트 17개(엣지/파리티 케이스 6개 x 2, N1·N2 단위 테스트 2개, N3 파라미터 3개).
