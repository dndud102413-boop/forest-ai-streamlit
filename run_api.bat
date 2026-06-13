@echo off
REM ============================================================
REM  산림 수종 추천 REST API (FastAPI) - Windows 원클릭 실행
REM  Swagger 문서: http://localhost:8000/docs
REM  정식 모바일 앱(Flutter/React Native)이 이 API를 호출
REM ============================================================
chcp 65001 >NUL
cd /d "%~dp0"

set "PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PYTHONPATH="
if exist ".venv\Lib\site-packages" set "PYTHONPATH=%CD%\.venv\Lib\site-packages"
if not exist "%PY%" set "PY=python"

"%PY%" --version >NUL 2>&1
if errorlevel 1 (
  echo [오류] Python을 찾을 수 없습니다. https://www.python.org 에서 설치 후 다시 실행하세요.
  pause
  exit /b 1
)
echo 사용 파이썬: %PY%

echo [1/2] 의존성 확인...
"%PY%" -c "import fastapi, uvicorn" >NUL 2>&1
if errorlevel 1 (
  "%PY%" -m pip install -r requirements.txt
)

echo [2/2] API 시작: http://localhost:8000  (문서: /docs)
"%PY%" -m uvicorn app.api:app --host 0.0.0.0 --port 8000
pause
