"""웹 서버 진입점. backend/에서 실행한다 (Windows PowerShell은 venv\\Scripts\\python):

    venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

API 문서(Swagger)는 http://127.0.0.1:8000/docs 에 있다. 테스트는 이 모듈 대신 app.api.factory.create_app을 쓴다
(이 모듈을 import하면 .env를 읽는다).
"""

from app.api.factory import create_app
from app.api.oauth import install_access_log_redaction

app = create_app()
# 소셜 로그인 콜백의 인가 코드·state가 접근 로그에 남지 않게 한다.
install_access_log_redaction()

# 로컬 프론트와 API를 같은 출처에서 제공한다. 공개 범위는 frontend/로 한정한다.
from pathlib import Path
from fastapi.staticfiles import StaticFiles

app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "frontend", html=True), name="frontend")
