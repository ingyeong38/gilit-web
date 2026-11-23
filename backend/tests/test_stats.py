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


# --- 사이트 전체 이용 통계 ---


def overall(client, **params):
    response = client.get("/api/stats", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_site_stats_requires_login(env):
    assert TestClient(env.app, base_url=BASE_URL).get("/api/stats").status_code == 401


def test_site_stats_ranks_saved_rows_across_users_in_kst(env):
    env.add(env.alice_id, datetime(2026, 11, 12, 14, 59, 59, tzinfo=UTC), "제외", "제외")
    edge = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
    env.add(env.alice_id, edge, "B", "부산역")
    env.add(env.alice_id, edge, "B", "부산역")  # 기록 카드가 같아도 저장된 행은 각각 집계
    env.add(env.bob_id, NOW, "A", "부산역")
    env.add(env.bob_id, NOW, " B ", " ")
    for name in ["a", "C", "D", "E"]:
        env.add(env.bob_id, NOW, name, "")
    env.add(env.bob_id, NOW + timedelta(seconds=1), "미래", "미래")

    body = overall(env.alice)
    assert (body["timeZone"], body["from"], body["to"]) == ("Asia/Seoul", WEEK[0], WEEK[-1])
    assert body["days"] == 7
    assert body["totalSearches"] == 8
    assert body["popularOrigins"] == [{"name": "부산역", "count": 3}]
    assert body["popularDestinations"] == [
        {"name": name, "count": count} for name, count in [("B", 3), ("A", 1), ("C", 1), ("D", 1), ("E", 1)]
    ]
    assert body["visitorStatus"] == "unavailable"
    assert all(item["count"] is None for item in body["dailyVisitors"])


def ga_report(*values, zone="Asia/Seoul"):
    rows = []
    for value in values:
        if isinstance(value, tuple):
            day, value = value
            row = {"dimensionValues": [{"value": day}]}
        else:
            row = {}
        rows.append({**row, "metricValues": [{"value": str(value)}]})
    return {"metadata": {"timeZone": zone}, "rowCount": len(rows), "rows": rows}


def ga_stub(env, monkeypatch, reports, first="2026-10-01"):
    ga = env.app.state.ga4_reports
    monkeypatch.setattr(ga, "property_id", "1")
    monkeypatch.setattr(ga, "start_date", first)
    calls = []
    def run(requests):
        calls.extend(requests)
        if isinstance(reports, Exception):
            raise reports
        return reports
    monkeypatch.setattr(ga, "run", run)
    return calls


def test_site_stats_uses_independent_unique_users_and_preserves_db_outage(env, monkeypatch):
    calls = ga_stub(env, monkeypatch, [
        ga_report(("20261119", 16), ("20261118", 8), ("20261113", 11)),
        ga_report(123), ga_report(53), ga_report(24), ga_report(20),
    ])
    def broken(*args):
        raise TimeoutError
    monkeypatch.setattr(env.backend.history, "site_search_stats", broken)
    body = overall(env.alice)

    assert body["searchStatus"] == "unavailable"
    assert body["totalSearches"] is None
    assert body["visitorStatus"] == "ok"
    assert counts({"daily": body["dailyVisitors"]}) == [11, 0, 0, 0, 0, 8, 16]
    assert (body["totalVisitors"], body["monthVisitors"], body["todayVisitors"]) == (123, 53, 16)
    assert (body["weekVisitors"], body["weekChangePct"], body["dayChangePct"]) == (24, 20.0, 100.0)
    assert all(call["metrics"] == [{"name": "totalUsers"}] for call in calls)
    assert [call["dateRanges"][0] for call in calls] == [
        {"startDate": start, "endDate": end} for start, end in
        [(WEEK[0], WEEK[-1]), ("2026-10-01", WEEK[-1]), ("2026-11-01", WEEK[-1]),
         (WEEK[0], WEEK[-1]), ("2026-11-06", "2026-11-12")]
    ]
    assert ["dimensions" in call for call in calls] == [True, False, False, False, False]


@pytest.mark.parametrize("reports,status", [
    (PermissionError(), "unavailable"),
    (TimeoutError(), "unavailable"),
    ([ga_report(zone="America/Los_Angeles")] * 5, "unavailable"),
    ([ga_report()] * 5, "empty"),
])
def test_site_stats_ga_failures_and_no_data_keep_search_response(env, monkeypatch, reports, status):
    ga_stub(env, monkeypatch, reports)
    body = overall(env.alice)
    assert body["visitorStatus"] == status
    assert body["totalVisitors"] is None
    assert body["searchStatus"] == "ok"
    assert body["totalSearches"] == 0
    assert body["popularOrigins"] == body["popularDestinations"] == []


def test_site_stats_before_collection_and_comparison_with_zero(env, monkeypatch):
    calls = ga_stub(env, monkeypatch, [ga_report(("20261119", 1)), ga_report(1), ga_report(1), ga_report(1)], first="2026-11-18")
    body = overall(env.alice)
    assert len(calls) == 4
    assert body["visitorPeriods"]["dailyVisitors"]["startDate"] == "2026-11-18"
    assert [row["count"] for row in body["dailyVisitors"]] == [None, None, None, None, None, 0, 1]
    assert body["dayChangePct"] is body["weekChangePct"] is None
    assert body["periodVisitors"] == body["weekVisitors"] == 1


def test_site_stats_week_comparison_with_zero(env, monkeypatch):
    ga_stub(env, monkeypatch, [ga_report(("20261119", 1)), ga_report(1), ga_report(1), ga_report(1), ga_report(0)])
    assert overall(env.alice)["weekChangePct"] is None


def test_ga4_reports_uses_adc_and_batches_date_ranges(monkeypatch):
    import google.auth
    from google.auth.transport import requests as transport

    from app.site_stats import GA4Reports

    credentials = object()
    report = ga_report(123)
    payload = [{"metrics": [{"name": "totalUsers"}], "dateRanges": [
        {"startDate": "2026-11-13", "endDate": "2026-11-19"}
    ]}]

    def default(*, scopes):
        assert scopes == ["https://www.googleapis.com/auth/analytics.readonly"]
        return credentials, None

    class Session:
        def __init__(self, supplied, *, refresh_timeout):
            assert supplied is credentials
            assert refresh_timeout == 5

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, *, json, timeout, max_allowed_time):
            assert url == "https://analyticsdata.googleapis.com/v1beta/properties/1:batchRunReports"
            assert json == {"requests": payload}
            assert 0 < timeout <= max_allowed_time
            return self

        def raise_for_status(self):
            pass

        def json(self):
            return {"reports": [report]}

    monkeypatch.setattr(google.auth, "default", default)
    monkeypatch.setattr(transport, "AuthorizedSession", Session)
    assert GA4Reports("1", "2026-10-01").run(payload) == [report]


@pytest.mark.parametrize("params", [{"days": "0"}, {"days": "30"}, {"days": ""}, {"days": "7.0"}, {"days": ["1", "7"]}])
def test_site_stats_rejects_unsupported_days(env, params):
    response = env.alice.get("/api/stats", params=params)
    assert response.status_code == 400
    assert response.json() == {"message": "기간(days)은 1, 7, 31만 지원합니다."}


@pytest.mark.parametrize("days,first,count", [(1, "2026-11-19", 1), (7, "2026-11-13", 2), (31, "2026-10-20", 3)])
def test_site_stats_filters_same_rows_for_count_and_ranks(env, days, first, count):
    env.now = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)  # 오늘 KST 00:00
    for created, place in [
        (env.now, "오늘"),
        (env.now - timedelta(seconds=1), "어제"),
        (env.now - timedelta(days=30), "첫날"),
        (env.now - timedelta(days=30, seconds=1), "기간 밖"),
        (env.now + timedelta(seconds=1), "미래"),
    ]:
        env.add(env.alice_id, created, place, place)

    body = overall(env.alice, days=days)
    assert (body["days"], body["from"], body["to"]) == (days, first, "2026-11-19")
    assert body["totalSearches"] == count
    assert sum(row["count"] for row in body["popularOrigins"]) == count
    assert sum(row["count"] for row in body["popularDestinations"]) == count
    assert len(body["dailyVisitors"]) == days
    assert all(row["count"] is None for row in body["dailyVisitors"])


@pytest.mark.parametrize("days,first,prior_start,prior_end", [
    (1, "2026-11-19", "2026-11-18", "2026-11-18"),
    (31, "2026-10-20", "2026-09-19", "2026-10-19"),
])
def test_site_stats_uses_selected_ga4_ranges(env, monkeypatch, days, first, prior_start, prior_end):
    calls = ga_stub(env, monkeypatch, [
        ga_report(("20261119", 16)), ga_report(123), ga_report(53), ga_report(24), ga_report(12),
    ], first="2026-09-01")
    body = overall(env.alice, days=days)

    assert body["todayVisitors"] == 16
    assert body["totalVisitors"] == 123
    assert body["periodVisitors"] == 24
    assert body["periodChangePct"] == 100
    assert body["dailyVisitors"][-1]["count"] == 16
    assert [call["dateRanges"][0] for call in calls] == [
        {"startDate": a, "endDate": b} for a, b in
        [(first, WEEK[-1]), ("2026-09-01", WEEK[-1]), ("2026-11-01", WEEK[-1]),
         (first, WEEK[-1]), (prior_start, prior_end)]
    ]
    assert ["dimensions" in call for call in calls] == [True, False, False, False, False]
