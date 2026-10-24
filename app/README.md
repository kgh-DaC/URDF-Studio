# URDF Studio (URDF 웹 앱)

자연어·메시(STL/DAE/OBJ)·기존 URDF 입력으로 ROS 2 URDF를 생성·수정·검증하는 웹 앱.
FastAPI 백엔드 + 정적 프런트(three.js 0.186.1, urdf-loader 0.13.1, jsDelivr CDN 버전 고정).

## 실행

### Windows (PowerShell)
```powershell
cd C:\Users\ghkim\Downloads\PJT2_URDF\app
# 선택: Claude 생성 기능을 쓰려면 키 설정 (없어도 검증·뷰어·샘플은 동작)
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:ANTHROPIC_MODEL   = "claude-sonnet-5-5"   # 선택, 기본값 claude-sonnet-5-5
.\run.ps1                 # 처음 실행 시 .venv 생성 + 의존성 설치, http://127.0.0.1:8000
```
실행 정책 오류가 나면 `powershell -ExecutionPolicy Bypass -File .\run.ps1`.

수동 실행:
```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn main:app --port 8000
```

### Linux / macOS
```bash
cd app
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # 선택
uvicorn main:app --port 8000
```
브라우저에서 http://127.0.0.1:8000 을 연다. (CDN에서 three.js를 받으므로 인터넷 연결 필요)

### 테스트
```bash
.venv/Scripts/python -m pytest -q      # Windows: .\.venv\Scripts\python -m pytest -q
```

## 화면
- 좌측: 자연어 프롬프트(“편집기의 URDF를 기반으로 수정” 체크 시 기존 URDF 수정), 메시 업로드(단위·질량 지정, 체크한 메시는 생성에 포함), 샘플/파일 열기
- 중앙: 3D 뷰어(드래그 회전, 휠 줌), 우측 상단 조인트 슬라이더
- 우측: 검증 결과(오류 클릭 시 해당 링크 빨간색 하이라이트 + 편집기에서 해당 이름 선택), 가정(assumptions)
- 하단: URDF 편집기(입력 0.7초 후 자동 검증·렌더)
- 상단: URDF 다운로드, ROS 2 패키지 zip 다운로드

## API
| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | `/api/generate` | `{prompt, meshes[], baseUrdf?}` → `{urdf, spec, assumptions[], validation, artifact_id, attempts[], model}`. 키가 없으면 503 `{"error":"missing_api_key"}` |
| POST | `/api/validate` | `{urdf, check_meshes?}` → `{validation, artifact_id, robot_name}` |
| POST | `/api/upload` | multipart `files` (stl/dae/obj, 각 20 MB, 최대 10개), `unit?`(mm/m), `mass?`, `density?` → `{meshes:[MeshProps]}` |
| GET | `/api/download/{id}?format=urdf\|zip` | URDF 또는 `<robot>_description` ROS 2 패키지 zip |
| GET | `/api/health`, `/api/samples`, `/api/samples/{name}`, `/api/meshes`, `/api/schema` | 상태, 샘플, 업로드 목록, 명세 JSON 스키마 |
| GET | `/api/pkg/{pkg}/meshes/{file}` | 뷰어용 `package://` 메시 제공 |

오류 응답은 모두 `{"error": "<code>", "message": "<설명>"}` 형식.

## 생성 파이프라인
1. Claude가 `submit_robot_spec` 도구 호출(강제)로 **구조 명세 JSON(`schema.RobotSpec`)** 만 반환한다. XML을 직접 쓰지 않는다.
2. `builder.py`가 명세를 URDF로 조립: 관성은 박스/원기둥/구 공식 또는 메시 해석값으로 계산, axis 정규화, continuous limit 기본값, 메시는 바운딩박스 collision.
3. `validator.py`(스킬의 `validate_urdf.py` 로직 이식, 동일 결과를 테스트로 확인)로 검증.
4. 명세 스키마 오류·구조 오류·검증 오류를 `tool_result(is_error)`로 Claude에 되먹여 **최대 2회** 수정.

## 구성
```
app/
  main.py          FastAPI 엔드포인트
  schema.py        공유 스키마(명세 JSON, 요청/응답, 제한값)
  builder.py       명세 → URDF, 관성 계산, 명세 검사, URDF → 명세 가져오기
  validator.py     URDF 검증 (validate_urdf.py 이식)
  mesh_props.py    메시 물성 (mesh_props.py 이식)
  llm.py           Claude 호출 + 수정 루프
  ros_package.py   ROS 2 패키지 zip
  storage.py       업로드/아티팩트 저장 (data/)
  static/          index.html, app.js, style.css
  samples/         샘플 명세(.spec.json)와 URDF (tools/build_samples.py로 재생성)
  tests/           pytest
```

## 보안·제한
- API 키는 서버 환경변수로만 읽으며 프런트로 보내지 않는다 (`/api/health`는 설정 여부만 반환).
- 업로드: 확장자 화이트리스트(stl/dae/obj), 20 MB 제한, 파일명은 `[A-Za-z0-9_-]`로 정규화하고 무작위 접두사를 붙임, 해석 실패 파일은 삭제.
- 메시/아티팩트/샘플 경로는 정규식(`fullmatch`) + 디렉터리 내부 확인으로 경로 이탈 차단. JSON 본문 5 MB, URDF 2 MB 제한.
- 본문 크기는 실제 수신 바이트로 센다(chunked 포함). JSON 5 MB, 업로드 총 200 MB를 넘으면 413.
- Host 헤더 허용 목록(DNS rebinding 방지): 기본 `127.0.0.1,localhost`. 다른 호스트명으로 접속하려면 `URDF_APP_ALLOWED_HOSTS="myhost,127.0.0.1"`.
- 검증·생성 결과(아티팩트)는 내용 해시로 중복 제거되고 24시간 TTL과 500개 상한으로 정리된다(`URDF_APP_ARTIFACT_TTL_S`, `URDF_APP_MAX_ARTIFACTS`).
- CDN 모듈 11개는 import map `integrity`(SRI sha384)로 검증한다. 이 필드를 지원하지 않는 브라우저는 검증 없이 로드한다. 버전을 바꾸면 index.html의 해시를 다시 계산한다.

## 표준 명세
`schema.RobotSpec`이 표준 구조 명세다. `builder.architect_to_spec()`은 예전 architect 형식(`robot`, 실린더 `geometry.axis`, 미리 계산된 inertia)을 위한 호환 변환기이며, axis가 x/y/z가 아니면 `ValueError`를 낸다.

## 알려진 제한
- 기존 URDF를 “기반으로 수정”할 때는 명세로 가져오므로 `<gazebo>`, `<transmission>`, `<ros2_control>`, mimic 등 명세에 없는 요소와 원래 관성값은 빠진다(가정 목록에 표시). 이 요소를 보존하려면 편집기에서 직접 수정한다.
- xacro 입력은 지원하지 않는다(xacro로 먼저 변환해 붙여넣는다). ROS 2 `check_urdf`는 이 환경에 없어 실행하지 않는다.
- 뷰어는 깨진 parent/child 참조가 있는 URDF를 해당 조인트를 뺀 채 부분 렌더링한다.
