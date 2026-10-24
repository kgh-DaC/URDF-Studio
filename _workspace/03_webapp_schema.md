# 03 웹 앱 구조 명세 스키마 요약

원본(단일 소스): `app/schema.py` (`RobotSpec`). 런타임 JSON Schema: `GET /api/schema`.
`01_architect_spec.json`(urdf-authoring 1장: links[], joints[] with parent/child/type/axis/limit/origin)과 같은 형태이며, 웹 앱에서는 아래 필드로 고정한다.

## RobotSpec
| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| robot_name | str | `^[A-Za-z_][A-Za-z0-9_-]*$` |
| links[] | LinkSpec (1..200) | |
| joints[] | JointSpec (0..200) | |
| assumptions[] | str | 추정한 값마다 한 문장 |

## LinkSpec
| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| name | str | 전체에서 유일 |
| geometry | box{size[3]} \| cylinder{radius,length} \| sphere{radius} \| mesh{mesh_file, scale?[3]} \| null | null이면 가상 링크(관성 1e-6) |
| visual_origin | {xyz[3], rpy[3]} | 링크 좌표계 기준 형상 중심 |
| collision / collision_origin | geometry / origin (선택) | 기본: 같은 원시형상, mesh는 바운딩박스 |
| mass | float > 0 | kg. **관성 텐서는 받지 않음: 코드가 형상 공식으로 계산** |
| color | rgba[4] (선택) | |

## JointSpec
| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| name | str | 유일 |
| type | fixed \| revolute \| continuous \| prismatic | |
| parent, child | 링크 이름 | 존재해야 함, 자식당 부모 1개, 루트는 base_link 1개 |
| origin | {xyz, rpy} | 부모 링크 좌표계 기준 |
| axis | [3] | fixed 외 필수, 코드가 정규화 |
| limit | {lower?, upper?, effort>0, velocity>0} | revolute/prismatic: lower<upper 필수. continuous: 없으면 effort=10, velocity=10 기본값(가정에 기록) |

## 관성 계산 (builder.py)
- 박스: ixx=m/12(y²+z²), iyy=m/12(x²+z²), izz=m/12(x²+y²)
- 원기둥(z축): ixx=iyy=m/12(3r²+h²), izz=mr²/2
- 구: 2/5 m r²
- 메시: 업로드 해석값(질량중심 기준)을 질량비·스케일²로 환산, inertial origin=질량중심. 비균일 스케일이면 바운딩박스 근사.

## 검증·수정 루프
명세 스키마(pydantic) → `check_spec`(이름 중복, 참조, 트리/사이클, limit, 미업로드 메시) → URDF 조립 → `validate_urdf`(스킬 스크립트와 동일 결과). 오류는 `tool_result(is_error=true)`로 되먹여 최대 2회 재시도(총 3회 호출).

## API 응답 공통 필드
- ValidationResult: `{ok, summary, errors, warnings, issues[{severity, where, message, suggestion, link}]}`. `link`는 뷰어 하이라이트 대상(조인트 오류는 child 링크).
- 오류: `{error: code, message}`. code 예: missing_api_key(503), invalid_api_key, model_not_found, rate_limited, api_unreachable, base_urdf_invalid(422), generation_failed(422), invalid_request(422), payload_too_large(413), not_found(404).
