@echo off
rem 더블클릭으로 URDF Studio 실행 (Windows). 처음 실행 시 가상환경 생성 + 패키지 설치(수 분 소요).
rem 포트를 바꾸려면: run.bat 8080
chcp 65001 >nul
cd /d "%~dp0"
set PORT=%1
if "%PORT%"=="" set PORT=8000
where py >nul 2>nul
if errorlevel 1 (
  echo [오류] Python 런처^(py^)를 찾을 수 없습니다. https://www.python.org/downloads/ 에서 Python 3.11 이상을 설치하세요.
  echo        설치 화면에서 "Add python.exe to PATH"와 "py launcher"를 체크해야 합니다.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || (echo [오류] 가상환경 생성 실패 & pause & exit /b 1)
  ".venv\Scripts\python" -m pip install --upgrade pip
  ".venv\Scripts\python" -m pip install -r requirements.txt || (echo [오류] 패키지 설치 실패 & pause & exit /b 1)
)
if "%ANTHROPIC_API_KEY%"=="" echo [안내] ANTHROPIC_API_KEY 미설정: 자연어 생성은 꺼져 있고 검증/3D 뷰어/샘플은 동작합니다.
set PYTHONIOENCODING=utf-8
start "" http://127.0.0.1:%PORT%
".venv\Scripts\python" -m uvicorn main:app --host 127.0.0.1 --port %PORT%
pause
