"""AI 경로 요약 (POST /api/routes/summary). Gemini는 추천 경로 id와 짧은 문구만 만들고 숫자는 서버가 계산한다."""

from app.ai_summary.client import GeminiClient
from app.ai_summary.errors import GeminiError, SummaryRequestError
from app.ai_summary.service import SummaryInput, SummaryRoute, summarize

__all__ = ["GeminiClient", "GeminiError", "SummaryInput", "SummaryRequestError", "SummaryRoute", "summarize"]
