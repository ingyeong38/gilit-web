"""Gemini REST API(generateContent) 클라이언트. 새 의존성 없이 requests를 쓴다.

POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
- 인증: x-goog-api-key 헤더. URL 쿼리(?key=)에는 키를 넣지 않는다 (접근 로그·프록시 로그에 남지 않게).
- generationConfig.responseMimeType=application/json + responseSchema로 구조화 JSON을 받는다.
- 응답 본문은 읽어서 돌려주기만 한다. 로그·예외 메시지에 넣지 않는다.
"""

import json
import re

import requests

from app.ai_summary.errors import (
    GeminiAuthError,
    GeminiBadRequestError,
    GeminiQuotaError,
    GeminiResponseError,
    GeminiTimeoutError,
    GeminiUnavailableError,
)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
# 모델 이름은 URL 경로에 들어가므로 글자를 제한한다 (예: gemini-x.y-flash).
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class GeminiClient:
    """generateContent를 한 번 불러 구조화 JSON(dict)을 돌려준다.

    API 키는 _api_key에만 두고 repr, 예외 메시지, 예외 체인 어디에도 드러내지 않는다.
    세션은 테스트에서 Mock(spec=requests.Session)으로 바꿔 넣는다.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 6.0,
        base_url: str = GEMINI_API_BASE,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("GEMINI_API_KEY가 비어 있습니다.")
        model = (model or "").strip()
        if not MODEL_PATTERN.fullmatch(model):
            raise ValueError("GEMINI_MODEL은 영문·숫자·점·밑줄·하이픈으로 된 모델 이름이어야 합니다.")
        self._api_key = api_key.strip()
        self.model = model
        self._session = session or requests.Session()
        self.timeout = timeout
        self.url = f"{base_url.rstrip('/')}/models/{model}:generateContent"

    def __repr__(self) -> str:
        return f"GeminiClient(model={self.model!r}, timeout={self.timeout})"

    def generate_json(self, system: str, prompt: str, schema: dict) -> dict:
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0.2,
            },
        }
        # requests 예외는 종류만 남기고 except 밖에서 새로 던진다. 원래 예외(요청 정보 포함)가 __context__로
        # 따라붙지 않아 traceback에 프롬프트나 헤더가 실리지 않는다 (providers_kakao.py와 같은 패턴).
        failure: type[requests.RequestException] | None = None
        try:
            response = self._session.post(
                self.url,
                json=payload,
                headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            failure = type(error)
        if failure is not None:
            if issubclass(failure, requests.Timeout):
                raise GeminiTimeoutError("Gemini 응답 시간 초과")
            raise GeminiUnavailableError("Gemini 연결 실패")

        # 오류 응답 본문은 읽지 않는다 (요청 내용이 되돌아올 수 있다).
        status = response.status_code
        if status in (401, 403):
            raise GeminiAuthError("Gemini 인증 실패")
        if status == 429:
            raise GeminiQuotaError("Gemini 호출 한도 초과")
        if status >= 500:
            raise GeminiUnavailableError("Gemini 서버 오류")
        if status != 200:
            raise GeminiBadRequestError("Gemini 요청 거부")

        text = _candidate_text(response)
        parsed = _parse_json(text)
        if not isinstance(parsed, dict):
            raise GeminiResponseError("Gemini 응답이 JSON 객체가 아님")
        return parsed


def _candidate_text(response: requests.Response) -> str:
    body = _parse_body(response)
    try:
        parts = body["candidates"][0]["content"]["parts"]
        # 생각(thought) 부분은 빼고 답 부분만 잇는다.
        text = "".join(part["text"] for part in parts if isinstance(part, dict) and not part.get("thought") and "text" in part)
    except (KeyError, IndexError, TypeError):
        text = None
    if not isinstance(text, str) or not text.strip():
        raise GeminiResponseError("Gemini 응답에 후보가 없음")
    return text


def _parse_body(response: requests.Response) -> dict:
    failed = False
    try:
        body = response.json()
    except ValueError:
        failed = True
    if failed or not isinstance(body, dict):
        raise GeminiResponseError("Gemini 응답 형식 오류")
    return body


def _parse_json(text: str) -> object:
    failed = False
    try:
        value = json.loads(text)
    except ValueError:
        failed = True
    if failed:
        raise GeminiResponseError("Gemini 응답이 JSON이 아님")
    return value
