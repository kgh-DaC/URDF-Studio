---
name: urdf-validation
description: URDF/xacro의 구문, 트리 구조, 조인트 limit, 관성의 물리적 타당성, 메시 경로, ROS 2 호환성을 검증하고 결함 보고서를 만든다. URDF 검증·오류 진단·리뷰·'URDF가 RViz에서 안 떠' 같은 요청 시 사용한다.
---

# URDF 검증

## 절차
1. `python -I scripts/validate_urdf.py <file.urdf> [--mesh-root dir]` 실행. xacro 파일은 먼저 `xacro`로 변환한다.
2. 환경에 ROS 2가 있으면 추가로 `check_urdf <file>`, `urdf_to_graphviz`를 실행한다. 없으면 건너뛴 사실을 보고서에 적는다.
3. 아래 항목을 수동 확인한다: 좌표계 방향(축·origin 부호), collision이 visual을 대체 가능한지.

## 검사 항목 (이유 포함)
| 항목 | 이유 |
| --- | --- |
| 링크/조인트 이름 유일 | 중복이면 파서가 임의로 덮어씀 |
| 모든 조인트의 parent/child 링크가 존재 | 깨진 참조는 로드 실패 |
| 루트가 하나, 사이클 없음 | URDF는 트리만 지원 |
| revolute/prismatic에 limit, lower<upper | 누락 시 시뮬레이터 거부 |
| 질량>0, 관성 대각>0, 삼각부등식(ixx+iyy≥izz 등) | 비물리 관성은 물리엔진 폭주 원인 |
| 메시 파일 존재 | RViz에서 빈 화면의 가장 흔한 원인 |

## 보고 형식
`error|warn · 위치 · 원인 · 제안 수정`. 통과/실패 요약을 맨 위에 둔다.
