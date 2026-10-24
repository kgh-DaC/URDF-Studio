---
name: urdf-builder
description: ROS 2 URDF 웹 앱 개발과 URDF 생성·수정·검증 작업 전체를 에이전트 팀으로 조율하는 오케스트레이터. 'URDF 만들어줘', '메시로 URDF', 'URDF 검증/수정', 'URDF 웹 앱 개발/기능 추가', 'ROS 2 패키지로 묶어줘' 요청과, 다시 실행·재실행·수정·보완·이전 결과 기반 개선·특정 단계만 다시 요청 시 사용한다. 단순한 URDF 문법 질문에는 사용하지 않는다.
---

# URDF Builder 오케스트레이터

**실행 모드:** 혼합. 설계·구현은 서브에이전트 위임(결과만 필요), 검증-수정 루프는 지속형 에이전트(`urdf-qa` ↔ 담당자 `SendMessage`).

## 0단계: 맥락 확인
- `_workspace/` 없음 → 처음부터. 있고 부분 수정 요청 → 해당 단계 에이전트만 재호출(이전 파일을 읽고 해당 부분만 수정). 있고 새 입력 → `_workspace_<타임스탬프>/`로 이동 후 새로 시작.
- 요청을 분류한다: (A) URDF 생성/수정 작업, (B) 웹 앱 개발, (C) 둘 다.

## 흐름
| 단계 | 작업 | 담당(subagent_type) | 산출물 |
| --- | --- | --- | --- |
| 1 | 메시가 있으면 물성 계산 | mesh-analyst | `_workspace/02_mesh_props.json` |
| 2 | 구조 명세 + URDF/xacro 작성 (메시 결과 반영) | urdf-architect | `_workspace/01_architect_spec.json`, `output/*.urdf(.xacro)` |
| 3 | 즉시 검증 | urdf-qa | `_workspace/04_qa_report.md` |
| 4 | error가 있으면 architect에게 목록 전달·수정 후 재검증(최대 2회) | urdf-architect ↔ urdf-qa | 수정본 |
| 5 | (B/C) 웹 앱 구현. 스키마가 확정된 뒤 시작하고 1~4와 독립된 모듈은 병렬 호출 | urdf-webapp-dev | `app/` |
| 6 | 웹 앱 모듈별 즉시 검증(API↔UI 경계면 대조) | urdf-qa | QA 보고 |
| 7 | (요청 시) ROS 2 패키지화 | ros2-integrator | `output/<robot>_description/` |

- 단계 1은 메시가 없으면 건너뛴다. 단계 5의 독립 모듈은 한 메시지에서 `Agent`를 병렬 호출한다.
- 에이전트 호출 시 `subagent_type`에 위 이름을 쓰고 프롬프트에 입력 파일 경로와 출력 경로를 명시한다.

## 데이터 전달
파일 기반(`_workspace/{phase}_{agent}_{artifact}`). 최종 산출물만 `output/`, `app/`에 둔다. `_workspace/`는 지우지 않는다.

## 오류 처리
- 에이전트 실패: 1회 재시도, 재실패 시 그 결과 없이 진행하고 최종 보고에 누락을 적는다.
- 인증·한도·권한 실패는 재시도하지 않고 사용자에게 보고한다.
- 단위·치수가 모호하면 가정값을 쓰되 `assumptions`로 최종 보고에 노출한다. 도구(ROS 2, xacro)가 없어 건너뛴 검증도 명시한다.
- 검증이 2회 수정 후에도 실패하면 남은 결함을 그대로 보고한다. 통과한 것처럼 보고하지 않는다.

## 최종 보고
생성 파일 목록, 가정 사항, QA 결과, 건너뛴 검증, 실행 방법.

## 테스트 시나리오
- 정상: "바퀴 4개 달린 베이스에 2자유도 팔을 올린 로봇 URDF 만들어줘" → 단계 2→3 실행, `output/`에 xacro·urdf 생성, QA PASS.
- 정상: STL 3개 + "각각 링크로 연결, 총질량 5kg" → 1→2→3, 단위 추정 신뢰도 낮으면 사용자 확인 요청.
- 오류: 깨진 URDF(조인트가 없는 링크 참조) 수정 요청 → QA가 error 보고, architect가 해당 항목만 수정, 재검증 PASS. 2회 후에도 FAIL이면 FAIL로 보고.
- 후속: "팔 조인트 limit만 다시 조정해줘" → `_workspace/` 유지, architect만 재호출 후 QA.
