# Windows에서 현재 작업 확인하기

## 1. 준비 (한 번만)
1. Python 3.11 이상 설치: https://www.python.org/downloads/ ("Add python.exe to PATH", "py launcher" 체크)
2. 이 저장소를 내려받는다.
   - Git: `git clone https://github.com/kgh-DaC/URDF-Studio.git` 후 (병합 전이라면 `git checkout claude/zealous-volta-acwqkd`)
   - 또는 GitHub 페이지에서 해당 브랜치를 **Code → Download ZIP**으로 받아 압축을 푼다.

## 2. 실행
`app\run.bat`을 **더블클릭**한다. 처음에는 가상환경 생성과 패키지 설치로 몇 분 걸린다.
브라우저가 `http://127.0.0.1:8000`으로 열린다. (three.js를 CDN에서 받으므로 인터넷 필요)
PowerShell을 쓰려면 `cd app` 후 `.\run.ps1` (정책 오류 시 `powershell -ExecutionPolicy Bypass -File .\run.ps1`).

## 3. 화면에서 확인할 것
| 확인 | 방법 |
| --- | --- |
| 3D 뷰어·조인트 슬라이더 | 좌측 샘플 목록에서 선택 후 "불러오기" → `diff_drive_robot` 또는 `two_link_arm` |
| 검증 오류 표시 | 샘플 `broken_arm` 열기 → 우측 오류 클릭 시 해당 링크가 빨갛게 표시 |
| 메시 업로드 | FreeCAD에서 내보낸 STL(단위 mm 선택) 업로드 |
| ROS 2 패키지 zip | 상단 "ROS 2 패키지 (zip)" 버튼 |
| 자연어 생성(선택) | 실행 전 PowerShell에서 `$env:ANTHROPIC_API_KEY="sk-ant-..."` |

## 4. 테스트(선택)
```
cd app
.\.venv\Scripts\python -m pytest -q      # 91 passed 예상
```

## 5. 산출물 위치
- `output/sample_robot.urdf`, `output/sample_robot.urdf.xacro`: 예제 결과물
- `_workspace/`: 에이전트 작업 기록(QA 보고서 등)

## 6. FreeCAD → ROS 2 워크스페이스 (하네스 흐름)
`.claude/skills/freecad-export/SKILL.md`, `.claude/skills/ros2-workspace-install/SKILL.md` 참고.
