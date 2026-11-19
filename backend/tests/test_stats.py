"""내 이용 통계 (GET /api/stats/me?range=week) 테스트. history_backend fixture로 메모리와 MySQL(mysql_live)에서 같은 테스트를 돈다.

기록은 저장소의 add로 직접 넣는다 (created_at을 정할 수 있게). 규칙은 app/history/stats.py.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.factory import create_app
from app.auth import AuthService, PasswordHasher
from app.config import Settings
from app.departure import KST, MockRouteProvider
from app.history import HistoryDraft, HistoryService
from app.history.errors import RANGE_INVALID
from app.history.stats import weekly_stats
from tests.test_history import BASE_URL, logged_in

# 기준 현재 시각: 2026-11-19 (목) 12:00 KST. 최근 7일은 11-13(금) ~ 11-19(목)
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=KST)
WEEK = ["2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"]
UTC = timezone.utc


def kst(day: int, hour: int = 9, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=KST)


class Env:
    def __init__(self, backend) -> None:
        self.backend = backend
        self.now = NOW
        clock = lambda: self.now  # noqa: E731
        auth = AuthService(backend.users, backend.sessions, PasswordHasher(rounds=4), clock=clock)
        self.app = create_app(
            Settings(), MockRouteProvider(), clock=clock, auth=auth, history=HistoryService(backend.history, clock=clock)
        )
        self.alice, self.alice_id = logged_in(self.app, "alice@example.com")
        self.bob, self.bob_id = logged_in(self.app, "bob@example.com")

    def add(self, user_id: int, created_at: datetime, dest: str | None = "동의대학교", origin: str = "김해시청"):
        draft = HistoryDraft(origin_name=origin, dest_name=dest, arrive_at=kst(20, 9))
        return self.backend.history.add(user_id, draft, created_at)


@pytest.fixture
def env(history_backend) -> Env:
    return Env(history_backend)


def stats(client: TestClient, **params) -> dict:
    response = client.get("/api/stats/me", params=params or {"range": "week"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [day["date"] for day in body["daily"]] == WEEK
    assert body["total"] == sum(day["count"] for day in body["daily"]), "합계 = 날짜별 합"
    return body


def counts(body: dict) -> list[int]:
    return [day["count"] for day in body["daily"]]


# --- 요청 ---


def test_requires_login(env):
    response = TestClient(env.app, base_url=BASE_URL).get("/api/stats/me", params={"range": "week"})
    assert response.status_code == 401
    assert response.json() == {"message": "로그인이 필요합니다."}


@pytest.mark.parametrize("value", ["month", "", "WEEK", "week ", "7", "day"])
def test_invalid_range_is_400(env, value):
    response = env.alice.get("/api/stats/me", params={"range": value})
    assert response.status_code == 400
    assert response.json() == {"message": RANGE_INVALID}


def test_range_defaults_to_week(env):
    env.add(env.alice_id, kst(18))
    response = env.alice.get("/api/stats/me")
    assert response.status_code == 200
    assert response.json() == stats(env.alice, range="week")


# --- 집계 ---


def test_user_without_searches_gets_zero_filled_week(env):
    assert stats(env.alice) == {
        "range": "week",
        "from": "2026-11-13",
        "to": "2026-11-19",
        "daily": [{"date": day, "count": 0} for day in WEEK],
        "total": 0,
        "topPlace": None,
    }


def test_counts_per_day_and_sums_same_day(env):
    for created in [kst(13, 8), kst(16, 7), kst(16, 12), kst(16, 23, 59), kst(19, 0, 0), kst(19, 11, 59)]:
        env.add(env.alice_id, created)

    body = stats(env.alice)

    assert counts(body) == [1, 0, 0, 3, 0, 0, 2]
    assert body["total"] == 6


def test_kst_date_boundary(env):
    # UTC 14:59:59 = KST 23:59:59 (그날), UTC 15:00:00 = KST 다음 날 0시
    env.add(env.alice_id, datetime(2026, 11, 16, 14, 59, 59, tzinfo=UTC))
    env.add(env.alice_id, datetime(2026, 11, 16, 15, 0, 0, tzinfo=UTC))

    body = stats(env.alice)

    assert counts(body) == [0, 0, 0, 1, 1, 0, 0]  # 11-16, 11-17


def test_rows_outside_seven_days_are_excluded(env):
    env.add(env.alice_id, datetime(2026, 11, 12, 14, 59, 59, tzinfo=UTC))  # KST 11-12 23:59:59 (7일 밖)
    env.add(env.alice_id, datetime(2026, 11, 12, 15, 0, 0, tzinfo=UTC))  # KST 11-13 0시 (첫날)
    env.add(env.alice_id, kst(1))  # 훨씬 전

    body = stats(env.alice)

    assert counts(body) == [1, 0, 0, 0, 0, 0, 0]
    assert body["total"] == 1


def test_future_rows_are_excluded(env):
    env.add(env.alice_id, NOW)  # 지금 = 포함
    env.add(env.alice_id, NOW + timedelta(seconds=1), dest="미래")  # 지금보다 뒤 (시계 차이 등) = 제외
    env.add(env.alice_id, kst(19, 23, 59, 59), dest="미래")
    env.add(env.alice_id, kst(20, 0), dest="미래")

    body = stats(env.alice)

    assert counts(body) == [0, 0, 0, 0, 0, 0, 1]
    assert body["topPlace"] == "동의대학교"


def test_other_users_rows_are_isolated(env):
    env.add(env.alice_id, kst(15), dest="해운대")
    for hour in range(8, 12):
        env.add(env.bob_id, kst(18, hour), dest="김해공항")

    alice, bob = stats(env.alice), stats(env.bob)

    assert (alice["total"], alice["topPlace"]) == (1, "해운대")
    assert (bob["total"], bob["topPlace"]) == (4, "김해공항")
    assert counts(bob) == [0, 0, 0, 0, 0, 4, 0]


def test_top_place_is_most_frequent_destination(env):
    env.add(env.alice_id, kst(13), dest="동의대학교")
    env.add(env.alice_id, kst(14), dest="동의대학교")
    env.add(env.alice_id, kst(18), dest="해운대")
    env.add(env.alice_id, kst(19, 11), dest="김해공항")
    env.add(env.alice_id, kst(19, 11, 30), dest=None)  # 목적지 이름 없음: 횟수에는 넣고 장소에서는 뺀다

    body = stats(env.alice)

    assert body["topPlace"] == "동의대학교"
    assert body["total"] == 5


def test_top_place_tie_goes_to_most_recent_search(env):
    env.add(env.alice_id, kst(13), dest="동의대학교")
    env.add(env.alice_id, kst(17), dest="해운대")
    env.add(env.alice_id, kst(18), dest="동의대학교")  # 동의대 마지막 검색 11-18
    env.add(env.alice_id, kst(19, 10), dest="해운대")  # 해운대 마지막 검색 11-19 → 동률(2:2)에서 이긴다

    assert stats(env.alice)["topPlace"] == "해운대"

    env.add(env.alice_id, kst(19, 11), dest="동의대학교")  # 3:2
    assert stats(env.alice)["topPlace"] == "동의대학교"


def test_top_place_ignores_destinations_outside_window(env):
    for day in range(1, 6):
        env.add(env.alice_id, kst(day), dest="옛목적지")  # 7일 밖에서 5회
    env.add(env.alice_id, kst(19), dest="해운대")

    assert stats(env.alice)["topPlace"] == "해운대"


def test_only_null_destinations_give_null_top_place(env):
    env.add(env.alice_id, kst(19), dest=None)
    body = stats(env.alice)
    assert (body["total"], body["topPlace"]) == (1, None)


def test_deleting_history_lowers_stats(env):
    env.add(env.alice_id, kst(17, 8), dest="해운대")
    env.add(env.alice_id, kst(18, 8), dest="동의대학교", origin="부산역")
    env.add(env.alice_id, kst(19, 8), dest="동의대학교", origin="부산역")  # 위와 같은 검색 묶음(카드 한 장)
    assert stats(env.alice)["total"] == 3

    card = next(card for card in env.alice.get("/api/history").json() if card["to"] == "동의대학교")
    assert env.alice.delete("/api/history", params={"id": card["id"]}).status_code == 204

    body = stats(env.alice)
    assert (counts(body), body["topPlace"]) == ([0, 0, 0, 0, 1, 0, 0], "해운대")

    assert env.alice.delete("/api/history").status_code == 204
    body = stats(env.alice)
    assert (body["total"], body["topPlace"]) == (0, None)


def test_window_follows_clock_across_kst_midnight(env):
    env.add(env.alice_id, kst(13, 10))
    env.now = datetime(2026, 11, 19, 14, 59, 59, tzinfo=UTC)  # KST 11-19 23:59:59: 11-13이 아직 첫날
    assert stats(env.alice)["total"] == 1

    env.now = datetime(2026, 11, 19, 15, 0, 0, tzinfo=UTC)  # KST 11-20 0시: 11-14 ~ 11-20
    body = env.alice.get("/api/stats/me").json()
    assert (body["from"], body["to"], body["total"]) == ("2026-11-14", "2026-11-20", 0)


# --- 순수 함수 ---


def test_weekly_stats_refilters_rows_outside_window():
    """저장소가 범위를 넓게 돌려줘도 같은 결과 (범위 거르기는 함수에서도 한다)."""
    from app.history.models import HistoryEntry

    def entry(entry_id: int, created_at: datetime, dest: str) -> HistoryEntry:
        draft = HistoryDraft(origin_name="a", dest_name=dest, arrive_at=created_at)
        return HistoryEntry.from_draft(entry_id, 1, draft, created_at)

    result = weekly_stats([entry(1, kst(12, 23), "밖"), entry(2, kst(19, 13), "미래"), entry(3, kst(19, 9), "안")], NOW)

    assert [item.count for item in result.daily] == [0, 0, 0, 0, 0, 0, 1]
    assert (result.total, result.top_place) == (1, "안")
