---
name: freecad-export
description: FreeCAD(.FCStd) 모델에서 부품별 STL과 위치 정보(parts.json)를 내보내 URDF 작성 입력으로 만든다. 'FreeCAD로 모델링했어', 'FCStd에서 URDF', 'CAD 부품을 링크로' 요청 시 사용한다.
---

# FreeCAD 내보내기

## 절차
1. 사용자에게 FreeCAD에서 **링크가 될 단위별로 Body 또는 Part를 하나씩** 만들었는지 확인한다(링크 1개 = 최상위 객체 1개). 이름은 영문 소문자·숫자·밑줄 권장.
2. `scripts/export_parts.py`를 실행한다.
   - GUI: 모델을 연 채 매크로 실행. 출력 기본값은 홈 폴더의 `freecad_export/`.
   - CLI: `FC_FILE=<.FCStd> FC_OUT=<폴더> FreeCADCmd scripts/export_parts.py` (Windows는 `set`으로 환경변수 지정).
3. 결과 `<폴더>/*.stl`과 `parts.json`을 `_workspace/freecad/`로 복사한다.
4. `mesh-processing` 스킬로 메시 물성을 계산한다. `parts.json`의 `unit`이 mm이므로 `--unit mm`을 명시한다(추정에 맡기지 않는다).
5. `urdf-architect`에게 `parts.json`을 넘겨 링크·조인트 트리를 만든다. 조인트 위치는 두 부품이 맞닿는 지점이며, 사용자가 회전축·범위를 말하지 않았으면 가정으로 `assumptions`에 기록하고 사용자에게 확인을 요청한다.

## 주의
- STL은 **월드 좌표계(조립된 위치)** 로 저장된다. 링크 프레임을 조인트 위치로 옮기면 visual origin을 그만큼 반대로 보정해야 한다.
- 질량은 FreeCAD에 재질이 없으므로 `volume_mm3 × 밀도`로 추정한다. 밀도를 사용자에게 묻고, 모르면 가정으로 기록한다.
- 이 스크립트는 FreeCAD가 있는 환경에서만 실행된다. 이 개발 환경에는 FreeCAD가 없어 **실행 검증을 하지 못했다**(문법 컴파일만 확인). 첫 실제 실행 결과를 사용자와 함께 확인한다.
