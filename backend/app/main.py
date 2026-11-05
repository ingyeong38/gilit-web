"""웹 서버 진입점. backend/에서 실행한다:

    venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

API 문서(Swagger)는 http://127.0.0.1:8000/docs 에 있다. 테스트는 이 모듈 대신 app.api.factory.create_app을 쓴다
(이 모듈을 import하면 .env를 읽는다).
"""

from app.api.factory import create_app

app = create_app()
