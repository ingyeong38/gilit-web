"""AI 경로 요약 (POST /api/routes/summary).

역할 나누기:
- Gemini는 recommendedRouteId(입력 카드 id 중 하나), headline, keywords만 만든다.
- 숫자(slackMin, comparison, recommendedDepartTime, bufferMin)와 label은 서버가 요청 카드 값으로 계산해 덮어쓴다.
  Gemini가 숫자를 틀려도 화면의 게이지·막대는 틀리지 않는다.
- Gemini를 쓸 수 없거나 출력이 규칙에 맞지 않으면 항상 rule 요약으로 대신한다 (source="rule").

저장 정책: 요약·입력 값을 DB, 검색 기록, 캐시 어디에도 저장하지 않는다. Gemini에 보내는 값은 도착 희망 시각,
여유시간, 카드의 옵션 이름·시각·소요시간·거리·통행료뿐이다 (장소 이름, 좌표, 사용자 정보는 보내지 않는다).
로그에는 결과 종류(오류 클래스 이름)와 소요시간만 남긴다. 프롬프트, Gemini 응답, 입력 값은 남기지 않는다.
"""

import logging
import math
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.ai_summary.client import GeminiClient
from app.ai_summary.errors import GeminiNotConfiguredError, GeminiResponseError, SummaryRequestError
from app.departure import KST, ROUTE_OPTIONS

logger = logging.getLogger("app.ai_summary")

ROUTE_LIMIT = 4  # GET /api/routes 카드 수 상한과 같다
ROUTE_WINDOW = timedelta(hours=24)
HEADLINE_MAX = 40
KEYWORD_MAX_COUNT = 3
KEYWORD_MAX_LENGTH = 12
DEFAULT_RECOMMENDED_ID = "recommend"

COUNT_MESSAGE = f"routes는 1~{ROUTE_LIMIT}개 보내 주세요."
ID_MESSAGE = f"routes의 id는 {', '.join(ROUTE_OPTIONS)} 중 하나여야 합니다."
DUPLICATE_MESSAGE = "같은 id의 경로가 두 번 있습니다."
DEPART_PASSED_MESSAGE = "출발시각이 이미 지난 경로가 있습니다. 경로를 다시 검색해 주세요."
DEPART_RANGE_MESSAGE = "경로의 출발시각은 도착 희망 시각 전 24시간 안이어야 합니다."
ARRIVE_RANGE_MESSAGE = "경로의 도착시각은 출발시각 이후, 도착 희망 시각 뒤 24시간 안이어야 합니다."

SYSTEM_INSTRUCTION = (
    "너는 자동차 길찾기 서비스의 경로 추천 도우미다. 주어진 경로 후보 중 하나를 골라 짧은 한국어 요약을 만든다. "
    "반드시 지정된 JSON 스키마로만 답한다. "
    "recommendedRouteId는 후보 id 중 하나만 쓴다. "
    f"headline은 {HEADLINE_MAX}자 이내 한 문장, keywords는 {KEYWORD_MAX_COUNT}개 이하이고 각 {KEYWORD_MAX_LENGTH}자 이내다. "
    "숫자, 시각, 시간 표현(몇 분, 몇 시 등), 금액은 쓰지 않는다 (화면이 따로 보여 준다). 줄바꿈과 이모지는 쓰지 않는다."
)


@dataclass(frozen=True)
class SummaryRoute:
    id: str
    depart_at: datetime
    arrive_at: datetime
    duration_min: int
    distance_km: float
    toll: int | None


@dataclass(frozen=True)
class SummaryInput:
    arrive: datetime
    buffer_min: int
    routes: tuple[SummaryRoute, ...]


@dataclass(frozen=True)
class AiOutput:
    route_id: str
    headline: str
    keywords: tuple[str, ...]


def validate_input(data: SummaryInput, now: datetime) -> None:
    """형식(타입·범위)은 API 모델이 본다. 여기서는 여러 값을 함께 보는 규칙과 현재 시각 기준 규칙을 본다."""
    if not 1 <= len(data.routes) <= ROUTE_LIMIT:
        raise SummaryRequestError(COUNT_MESSAGE, "routes_count")
    ids = [route.id for route in data.routes]
    if any(route_id not in ROUTE_OPTIONS for route_id in ids):
        raise SummaryRequestError(ID_MESSAGE, "route_id")
    if len(set(ids)) != len(ids):
        raise SummaryRequestError(DUPLICATE_MESSAGE, "route_duplicate")
    for route in data.routes:
        if not data.arrive - ROUTE_WINDOW <= route.depart_at < data.arrive:
            raise SummaryRequestError(DEPART_RANGE_MESSAGE, "depart_range")
        if not route.depart_at <= route.arrive_at <= data.arrive + ROUTE_WINDOW:
            raise SummaryRequestError(ARRIVE_RANGE_MESSAGE, "arrive_range")
    # 지난 출발시각은 맨 나중에 본다 (범위가 틀린 요청은 범위 문장을 먼저 보여 준다).
    for route in data.routes:
        if route.depart_at < now:
            raise SummaryRequestError(DEPART_PASSED_MESSAGE, "depart_passed")


def summarize(data: SummaryInput, now: datetime, client: GeminiClient | None) -> dict:
    """요약 응답(dict, camelCase). 요청 검증 실패만 SummaryRequestError로 올리고, Gemini 쪽 실패는 rule로 바꾼다."""
    validate_input(data, now)
    started = time.monotonic()
    ai = None
    try:
        if client is None:
            raise GeminiNotConfiguredError("Gemini 설정 없음")
        ai = parse_ai_output(client.generate_json(SYSTEM_INSTRUCTION, build_prompt(data), response_schema(data)), data)
    except Exception as error:  # noqa: BLE001 - 어떤 실패든 rule로 대신한다. 내용은 남기지 않는다.
        failure = type(error).__name__
    else:
        failure = None
    elapsed_ms = (time.monotonic() - started) * 1000
    if failure is None:
        logger.info("AI 요약 생성: %.0fms", elapsed_ms)
    else:
        logger.warning("AI 요약 대체(rule): %s, %.0fms", failure, elapsed_ms)
    return build_response(data, ai)


def build_prompt(data: SummaryInput) -> str:
    """Gemini에 보내는 값. 옵션 이름은 서버의 ROUTE_OPTIONS label이다 (요청의 자유 문자열은 넣지 않는다)."""
    lines = [
        f"도착 희망 시각: {_hhmm(data.arrive)} (한국 시간)",
        f"요청한 여유시간: {data.buffer_min}분",
        "경로 후보:",
    ]
    for route in data.routes:
        toll = "정보 없음" if route.toll is None else f"{route.toll}원"
        lines.append(
            f"- id={route.id} ({ROUTE_OPTIONS[route.id].label}): 출발 {_hhmm(route.depart_at)}, 도착 {_hhmm(route.arrive_at)}, "
            f"소요 {route.duration_min}분, 거리 {route.distance_km}km, 통행료 {toll}, 도착 여유 {slack_min(data, route)}분"
        )
    lines.append("가장 알맞은 경로 하나를 고르고, 고른 이유를 headline과 keywords로 짧게 써라.")
    return "\n".join(lines)


def response_schema(data: SummaryInput) -> dict:
    """Gemini responseSchema (OpenAPI 부분집합). 길이·개수는 서버가 다시 검사한다."""
    return {
        "type": "OBJECT",
        "properties": {
            "recommendedRouteId": {"type": "STRING", "enum": [route.id for route in data.routes]},
            "headline": {"type": "STRING"},
            "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["recommendedRouteId", "headline", "keywords"],
    }


def parse_ai_output(value: object, data: SummaryInput) -> AiOutput:
    """Gemini 출력 검증. 하나라도 어기면 GeminiResponseError (→ rule)."""
    if not isinstance(value, dict):
        raise GeminiResponseError("출력이 객체가 아님")
    route_id = value.get("recommendedRouteId")
    headline = value.get("headline")
    keywords = value.get("keywords")
    if not isinstance(route_id, str) or route_id not in {route.id for route in data.routes}:
        raise GeminiResponseError("입력에 없는 경로 id")
    headline = _clean_text(headline, HEADLINE_MAX)
    if not isinstance(keywords, list) or len(keywords) > KEYWORD_MAX_COUNT:
        raise GeminiResponseError("keywords 형식 위반")
    cleaned = tuple(_clean_text(keyword, KEYWORD_MAX_LENGTH) for keyword in keywords)
    return AiOutput(route_id, headline, cleaned)


def _clean_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        raise GeminiResponseError("문자열이 아님")
    text = value.strip()
    if not text or len(text) > limit:
        raise GeminiResponseError("길이 위반")
    # 제어·서식 문자(줄바꿈, 탭, 너비 없는 문자, 방향 제어 등)를 거른다.
    if any(unicodedata.category(char).startswith("C") for char in text):
        raise GeminiResponseError("제어 문자 포함")
    # 숫자는 서버 계산값(게이지·막대)과 어긋날 수 있어 받지 않는다. isdigit은 아라비아·전각(０-９)·위첨자·원문자 숫자를 포함한다.
    if any(char.isdigit() for char in text):
        raise GeminiResponseError("숫자 포함")
    return text


def rule_route(data: SummaryInput) -> SummaryRoute:
    """rule 추천: id가 recommend인 카드, 없으면 출발시각이 가장 늦은 카드 (같으면 앞 카드)."""
    for route in data.routes:
        if route.id == DEFAULT_RECOMMENDED_ID:
            return route
    latest = data.routes[0]
    for route in data.routes[1:]:
        if route.depart_at > latest.depart_at:
            latest = route
    return latest


def slack_min(data: SummaryInput, route: SummaryRoute) -> int:
    """도착 희망 시각 - 카드 예상 도착시각(분). 내림이라 여유를 부풀리지 않는다. 늦으면 음수."""
    return math.floor((data.arrive - route.arrive_at).total_seconds() / 60)


def build_response(data: SummaryInput, ai: AiOutput | None) -> dict:
    if ai is None:
        chosen = rule_route(data)
        headline = f"{ROUTE_OPTIONS[chosen.id].label} 경로를 기준으로 안내해요"
        keywords: list[str] = []
        source = "rule"
    else:
        chosen = next(route for route in data.routes if route.id == ai.route_id)
        headline = ai.headline
        keywords = list(ai.keywords)
        source = "gemini"
    return {
        "source": source,
        "recommendedRouteId": chosen.id,
        "recommendedDepartTime": _iso(chosen.depart_at),
        "headline": headline,
        "keywords": keywords,
        "slackMin": slack_min(data, chosen),
        "bufferMin": data.buffer_min,
        "comparison": [
            {
                "routeId": route.id,
                "label": ROUTE_OPTIONS[route.id].label,
                "durationMin": route.duration_min,
                "slackMin": slack_min(data, route),
                "toll": route.toll,
                "departTime": _iso(route.depart_at),
            }
            for route in data.routes
        ],
    }


def _iso(value: datetime) -> str:
    return value.astimezone(KST).isoformat()


def _hhmm(value: datetime) -> str:
    return value.astimezone(KST).strftime("%H:%M")
