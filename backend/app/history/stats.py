"""내 이용 통계 (GET /api/stats/me?range=week, docs/api-spec.md "내 이용 통계"). 검색 기록 표(search_history)로만 센다.

규칙
- 기간: 오늘을 포함한 최근 7일 (오늘 -6일 0시 ~ 지금), 한국 시간(KST) 날짜 기준
- 기준 시각: created_at (검색한 시각). 도착 희망 시각(arrive_at)이 아니다. 지금보다 뒤의 created_at은 세지 않는다
- 대상: 그 사용자의 행만. 같은 검색 묶기(기록 화면의 카드)와 상관없이 행 하나가 검색 1회다
- 가장 많이 간 곳: 목적지 이름(dest_name) 기준 최다. 이름은 그대로 비교한다(대소문자·공백 구분, 기록 묶기와 같다).
  동률이면 그중 가장 최근에 검색한 곳. 목적지 이름이 없는 행은 이 계산에서 뺀다. 셀 것이 없으면 null
- 기록을 지우면 통계도 함께 줄어든다 (따로 보관하지 않는다)
날짜 묶기는 DB 시간대 함수가 아니라 여기(파이썬)에서 한다. 메모리·MySQL 저장소가 같은 결과를 낸다.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.departure import KST
from app.history.models import HistoryEntry

WEEK_DAYS = 7
RANGES = ("week",)


@dataclass(frozen=True)
class DailyCount:
    date: date
    count: int


@dataclass(frozen=True)
class WeeklyStats:
    daily: list[DailyCount]  # 오래된 날 → 오늘, 항상 7개
    total: int  # daily 합계
    top_place: str | None

    @property
    def start_date(self) -> date:
        return self.daily[0].date

    @property
    def end_date(self) -> date:
        return self.daily[-1].date


def week_window(now: datetime) -> tuple[datetime, datetime]:
    """세는 범위 [오늘 -6일 0시(KST), 지금]. 둘 다 KST 시간대가 있는 datetime."""
    now = now.astimezone(KST)
    start = datetime.combine(now.date() - timedelta(days=WEEK_DAYS - 1), time.min, tzinfo=KST)
    return start, now


def weekly_stats(entries: Iterable[HistoryEntry], now: datetime) -> WeeklyStats:
    """entries는 한 사용자의 행 (범위 밖 행이 섞여 있어도 된다. 여기서 다시 거른다)."""
    start, end = week_window(now)
    days = [start.date() + timedelta(days=offset) for offset in range(WEEK_DAYS)]
    counts = dict.fromkeys(days, 0)
    places: dict[str, tuple[int, tuple[datetime, int]]] = {}  # 이름 → (횟수, 가장 최근 (created_at, id))
    for entry in entries:
        if not start <= entry.created_at <= end:
            continue
        counts[entry.created_at.astimezone(KST).date()] += 1
        if entry.dest_name:
            count, latest = places.get(entry.dest_name, (0, (entry.created_at, entry.id)))
            places[entry.dest_name] = (count + 1, max(latest, (entry.created_at, entry.id)))
    top_place = max(places, key=lambda name: places[name]) if places else None
    daily = [DailyCount(day, counts[day]) for day in days]
    return WeeklyStats(daily=daily, total=sum(item.count for item in daily), top_place=top_place)
