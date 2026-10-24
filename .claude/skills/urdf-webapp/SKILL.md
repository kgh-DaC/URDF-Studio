---
name: urdf-webapp
description: 자연어·메시 업로드·기존 URDF 입력을 받아 Claude API로 URDF를 생성·수정하고 3D 미리보기와 검증 결과를 보여주는 웹 앱의 아키텍처와 구현 규칙. URDF 웹 앱 개발, UI/API 추가·수정 시 사용한다.
---

# URDF 웹 앱 구현 규칙

## 아키텍처 (기본값; 사용자가 스택을 지정하면 따른다)
- 백엔드: Python FastAPI. 프런트엔드: 정적 HTML/JS + three.js + urdf-loader(CDN, 버전 고정).
- 엔드포인트
  - `POST /api/generate` {prompt, meshes[], baseUrdf?} → {urdf, spec, assumptions[], validation}
  - `POST /api/validate` {urdf} → 검증 결과 (`urdf-validation`의 validate_urdf.py 로직 재사용)
  - `POST /api/upload` 메시 업로드 → mesh_props 결과
  - `GET /api/download/{id}` URDF 또는 ROS 2 패키지 zip
- 생성 흐름: 프롬프트 → Claude(구조 명세 JSON 생성, 시스템 프롬프트에 `urdf-authoring` 규칙 포함) → 템플릿 코드로 URDF 조립 → 검증 → 실패 항목을 Claude에 되먹여 최대 2회 수정.

## 원칙
- LLM이 XML을 직접 자유 생성하게 하지 말고, 구조 명세 JSON(스키마 고정)을 받아 코드가 URDF로 변환한다. 이유: 관성·limit 누락 같은 결함을 코드로 보장할 수 있다.
- 응답 JSON 필드명을 프런트와 백이 공유하는 하나의 스키마 파일(`app/schema.py`)로 관리한다.
- API 키는 환경변수 `ANTHROPIC_API_KEY`; 클라이언트 노출 금지. 모델 호출 코드는 `claude-api` 스킬을 따른다.
- 업로드: 확장자(stl/dae/obj) 화이트리스트, 크기 제한, 파일명 정규화.
- UI: 좌측 입력/채팅, 중앙 3D 뷰어(조인트 슬라이더), 우측 검증 패널(오류 클릭 시 링크 하이라이트), 하단 URDF 코드 편집기.

## 완료 기준
서버가 뜨고, 샘플 프롬프트로 URDF가 생성되어 뷰어에 렌더링되며, 일부러 깨뜨린 URDF가 검증 패널에 오류로 표시된다.
