"""실제 Gemini API 호출 테스트. 기본 실행에서 빠진다. 사람이 직접 실행한다 (호출 1회, 쿼터 사용):

    venv/Scripts/python -m pytest -m gemini_live

GEMINI_API_KEY와 GEMINI_MODEL(환경변수, backend/.env, 루트 .env 순)이 없으면 건너뛴다.
키, 프롬프트, Gemini 응답 문구는 출력하지 않는다 (실패 메시지에도 넣지 않는다).
"""

import os

import pytest
from dotenv import dotenv_values

from app.ai_summary import GeminiClient
from app.ai_summary.service import SYSTEM_INSTRUCTION, SummaryInput, SummaryRoute, build_prompt, parse_ai_output, response_schema
from app.config import ENV_FILES
from tests.conftest import kst


def _find(name: str) -> str | None:
    # isolated_env fixture가 환경변수를 지우기 전, import 시점에 읽는다. os.environ은 바꾸지 않는다.
    value = os.environ.get(name, "").strip()
    for path in ENV_FILES:
        if not value and path.is_file():
            value = (dotenv_values(path).get(name) or "").strip()
    return value or None


API_KEY = _find("GEMINI_API_KEY")
MODEL = _find("GEMINI_MODEL")
pytestmark = [
    pytest.mark.gemini_live,
    pytest.mark.skipif(API_KEY is None or MODEL is None, reason="GEMINI_API_KEY·GEMINI_MODEL이 없어 실제 API 테스트를 건너뜁니다."),
]


def test_live_structured_summary_passes_server_validation():
    # 예시 값이다 (실제 교통 예측이 아니다). 날짜는 검증에 쓰지 않으므로 고정해도 된다.
    data = SummaryInput(kst(5, 9), 10, (
        SummaryRoute("recommend", kst(5, 8, 12), kst(5, 8, 50), 38, 31.2, 1500),
        SummaryRoute("free", kst(5, 8, 2), kst(5, 8, 49), 47, 29.8, 0),
    ))
    client = GeminiClient(API_KEY, MODEL, timeout=15)

    value = client.generate_json(SYSTEM_INSTRUCTION, build_prompt(data), response_schema(data))
    output = parse_ai_output(value, data)  # 규칙 위반이면 GeminiResponseError (문구는 담지 않는다)

    # 값이 실패 메시지에 펼쳐지지 않게 참·거짓만 비교한다.
    valid = output.route_id in {"recommend", "free"} and 1 <= len(output.headline) <= 40 and len(output.keywords) <= 3
    assert valid is True, "Gemini 출력이 서버 규칙을 통과하지 못했습니다."
