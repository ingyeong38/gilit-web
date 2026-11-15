"""검색 기록 값과 "같은 검색" 묶기 규칙. 메모리·MySQL 저장소가 같은 함수로 묶어 결과가 같다.

search_history는 통계(검색 수, 인기 출발지·목적지)를 겸하는 기록이라 행을 고치거나 지우지 않는다.
- 같은 검색 반복: 조회할 때 묶는다. 기준은 (출발지 이름, 목적지 이름, 도착 희망 시각의 시:분, KST)이다.
  프론트의 "다시 검색"이 날짜를 버리고 시:분만 쓰기 때문이다. 묶음마다 가장 최근 행 하나를 보여 준다.
- 삭제: user_id를 NULL로 바꿔 사용자에게서 분리한다. 통계 행은 그대로 남는다 (탈퇴의 ON DELETE SET NULL과 같다).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.departure import KST

MAX_ATTACHED_ROWS = 200  # 사용자에게 연결된 행 상한. 넘으면 오래된 것부터 분리한다 (조회 비용을 일정하게)
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


@dataclass(frozen=True)
class HistoryDraft:
    """저장할 검색 하나 (search_history 컬럼 그대로). 시각은 시간대가 있는 datetime."""

    origin_name: str | None
    dest_name: str | None
    arrive_at: datetime
    origin_lat: float | None = None
    origin_lng: float | None = None
    dest_lat: float | None = None
    dest_lng: float | None = None
    buffer_min: int = 0
    recommended_depart_at: datetime | None = None
    travel_mode: str = "car"
    ai_summary: str | None = None


@dataclass(frozen=True)
class HistoryEntry:
    id: int
    user_id: int | None  # None: 비로그인 검색이거나 사용자가 지운(분리한) 기록
    origin_name: str | None
    dest_name: str | None
    arrive_at: datetime
    origin_lat: float | None
    origin_lng: float | None
    dest_lat: float | None
    dest_lng: float | None
    buffer_min: int
    recommended_depart_at: datetime | None
    travel_mode: str
    ai_summary: str | None
    created_at: datetime

    @classmethod
    def from_draft(cls, entry_id: int, user_id: int | None, draft: HistoryDraft, created_at: datetime) -> "HistoryEntry":
        return cls(
            id=entry_id,
            user_id=user_id,
            origin_name=draft.origin_name,
            dest_name=draft.dest_name,
            arrive_at=draft.arrive_at,
            origin_lat=draft.origin_lat,
            origin_lng=draft.origin_lng,
            dest_lat=draft.dest_lat,
            dest_lng=draft.dest_lng,
            buffer_min=draft.buffer_min,
            recommended_depart_at=draft.recommended_depart_at,
            travel_mode=draft.travel_mode,
            ai_summary=draft.ai_summary,
            created_at=created_at,
        )


def search_key(origin_name: str | None, dest_name: str | None, arrive_at: datetime) -> tuple:
    """같은 검색인지 판단하는 값. 이름은 그대로(대소문자 구분), 시각은 KST 시:분."""
    local = arrive_at.astimezone(KST)
    return (origin_name, dest_name, local.hour, local.minute)


def entry_key(entry: HistoryEntry) -> tuple:
    return search_key(entry.origin_name, entry.dest_name, entry.arrive_at)


def newest_first(entries: Iterable[HistoryEntry]) -> list[HistoryEntry]:
    return sorted(entries, key=lambda e: (e.created_at, e.id), reverse=True)


def group_latest(entries: Iterable[HistoryEntry], limit: int) -> list[HistoryEntry]:
    """최신순으로 보면서 묶음마다 처음(가장 최근) 행만 남긴다. limit은 묶은 뒤의 개수다."""
    seen: set[tuple] = set()
    result: list[HistoryEntry] = []
    for entry in newest_first(entries):
        key = entry_key(entry)
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
        if len(result) >= limit:
            break
    return result
