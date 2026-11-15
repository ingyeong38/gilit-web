"""경로 검색 자동 저장 (F9 4단계). GET /api/routes가 성공한 뒤 응답을 보낸 다음(백그라운드) 부른다.

- 저장 값은 search_history 컬럼 그대로. 좌표는 소수 7자리, 이름은 100자로 맞춘다.
- recommended_depart_at은 응답 카드 중 추천(options에 "recommend") 카드의 departTime이다. 추천 카드가 빠졌으면 NULL.
- 로그인 사용자의 같은 검색(조회 때 묶는 키와 같음)은 5분 안에 다시 저장하지 않는다 (새로고침, 뒤로 가기).
- 비로그인 검색은 user_id NULL로 저장하고 5분 규칙을 적용하지 않는다 (같은 사람인지 알 수 있는 값을 저장하지 않으므로).
- 저장 실패는 로그만 남기고 삼킨다. 경로 응답은 이미 나갔다.
"""

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta

from app.departure import Coordinate
from app.history.models import HistoryDraft

logger = logging.getLogger("app.history")

DEDUP_WINDOW = timedelta(minutes=5)
NAME_MAX = 100  # search_history.origin_name·dest_name VARCHAR(100)
COORDINATE_DECIMALS = 7  # DECIMAL(10,7)
RECOMMEND = "recommend"


def _name(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    return text[:NAME_MAX] or None


def _round(value: float | None) -> float | None:
    return round(value, COORDINATE_DECIMALS) if value is not None else None


def recommended_depart_at(cards: Sequence[dict]) -> datetime | None:
    for card in cards:
        if RECOMMEND in card.get("options", ()) and card.get("departTime"):
            try:
                return datetime.fromisoformat(card["departTime"])
            except (TypeError, ValueError):
                return None
    return None


def draft_from_route_search(
    origin_name: str,
    dest_name: str,
    arrive_at: datetime,
    buffer_min: int,
    origin: Coordinate | None,
    destination: Coordinate | None,
    cards: Sequence[dict],
) -> HistoryDraft:
    return HistoryDraft(
        origin_name=_name(origin_name),
        dest_name=_name(dest_name),
        arrive_at=arrive_at,
        origin_lat=_round(origin.lat) if origin else None,
        origin_lng=_round(origin.lng) if origin else None,
        dest_lat=_round(destination.lat) if destination else None,
        dest_lng=_round(destination.lng) if destination else None,
        buffer_min=buffer_min,
        recommended_depart_at=recommended_depart_at(cards),
        travel_mode="car",
        ai_summary=None,  # AI 요약은 아직 없다 (응답의 aiSummary는 고정 안내 문구라 저장하지 않는다)
    )
