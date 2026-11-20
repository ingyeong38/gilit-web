"""AI 경로 요약 오류.

- SummaryRequestError: 요청 값 문제. 400 + {message, code}로 보낸다 (app/api/errors.py).
- GeminiError와 그 하위: Gemini 호출 실패. API 응답으로 나가지 않는다. 서비스가 잡아 rule 요약으로 바꾸고,
  로그에는 클래스 이름만 남긴다. 메시지는 고정 문구이고 키, 프롬프트, Gemini 응답 본문을 넣지 않는다.
"""


class SummaryRequestError(Exception):
    """요약 요청 값이 올바르지 않다. message는 사용자에게 그대로 보여 줄 수 있는 문장이다."""

    status = 400

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class GeminiError(Exception):
    """Gemini 요약을 받지 못했다."""


class GeminiNotConfiguredError(GeminiError):
    """GEMINI_API_KEY 또는 GEMINI_MODEL이 없다."""


class GeminiAuthError(GeminiError):
    """HTTP 401/403."""


class GeminiQuotaError(GeminiError):
    """HTTP 429."""


class GeminiTimeoutError(GeminiError):
    """제한 시간 안에 응답이 없다."""


class GeminiUnavailableError(GeminiError):
    """HTTP 5xx나 네트워크 오류."""


class GeminiBadRequestError(GeminiError):
    """HTTP 400 등 그 밖의 오류 상태."""


class GeminiResponseError(GeminiError):
    """응답 형식이 올바르지 않다 (JSON 아님, 후보 없음, 스키마 위반)."""
