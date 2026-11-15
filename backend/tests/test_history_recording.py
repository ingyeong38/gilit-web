"""경로 검색 자동 저장 테스트 (F9 4단계). GET /api/routes가 성공했을 때만 search_history에 쌓는다.

history_backend fixture로 메모리와 MySQL(mysql_live)에서 같은 테스트를 돈다. 경로는 가짜 RoadProvider로 계산하고
외부 API는 부르지 않는다. 기록 서비스의 시계만 따로 움직여 5분 규칙을 시험한다 (경로 계산 시계는 NOW 고정).
"""

import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.factory import create_app
from app.auth import AuthService, PasswordHasher
from app.config import Settings
from app.departure import Coordinate, ProviderUnavailableError, RouteNotFoundError
from app.history import HistoryService
from app.history.recording import draft_from_route_search, recommended_depart_at
from tests.conftest import NOW, kst
from tests.test_history import BASE_URL, logged_in
from tests.test_road_routes import RoadProvider


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class FailingOptionProvider(RoadProvider):
    """일부 옵션만 실패한다 (부분 성공 응답)."""

    def __init__(self, failing=("free",)):
        super().__init__()
        self.failing = failing

    def get_route_summary(self, origin, dest, depart_at, option=None):
        from app.departure import DEFAULT_ROUTE_OPTION

        option = option or DEFAULT_ROUTE_OPTION
        if option.key in self.failing:
            raise RouteNotFoundError("이 옵션으로는 경로가 없습니다.")
        return super().get_route_summary(origin, dest, depart_at, option)


class BrokenProvider(RoadProvider):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def get_route_summary(self, *args, **kwargs):
        raise self.error


class Env:
    def __init__(self, backend, provider=None) -> None:
        self.backend = backend
        self.history_clock = Clock(NOW)
        auth = AuthService(backend.users, backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)
        self.history = HistoryService(backend.history, clock=self.history_clock)
        self.app = create_app(
            Settings(route_provider="kakao"), provider or RoadProvider(), clock=lambda: NOW, auth=auth, history=self.history
        )
        self.alice, self.alice_id = logged_in(self.app, "alice@example.com")
        self.bob, self.bob_id = logged_in(self.app, "bob@example.com")

    def anonymous(self) -> TestClient:
        return TestClient(self.app, base_url=BASE_URL)

    def rows(self):
        return self.backend.history_rows()

    def rows_of(self, user_id):
        return [row_id for row_id, owner in self.rows() if owner == user_id]


@pytest.fixture
def env(history_backend) -> Env:
    return Env(history_backend)


def params(**changes):
    return {"from": "출발", "to": "도착", "arrive": kst(5, 9).isoformat(), "buffer": 10, **changes}


def search(client: TestClient, **changes):
    return client.get("/api/routes", params=params(**changes))


def history(client: TestClient):
    response = client.get("/api/history")
    assert response.status_code == 200
    return response.json()


# --- 로그인 사용자 ---


def test_logged_in_search_appears_in_history(env):
    response = search(env.alice)

    assert response.status_code == 200
    recommend = next(card for card in response.json() if "recommend" in card["options"])
    assert history(env.alice) == [
        {
            "id": history(env.alice)[0]["id"],
            "from": "출발",
            "to": "도착",
            "arriveTime": "2026-11-05T09:00:00+09:00",
            "buffer": 10,
            "departTime": recommend["departTime"],  # 추천 카드의 권장 출발 시각
            "fromLat": 35.2,  # 이름으로 확정한 좌표 (RoadProvider.search_places)
            "fromLng": 128.8,
            "toLat": 35.2,
            "toLng": 129.01,
        }
    ]
    assert history(env.bob) == []


def test_coordinates_from_query_are_stored_rounded(env):
    search(env.alice, fromLat=35.123456789, fromLng=128.88941234, toLat=35.1441, toLng=129.0336)

    card = history(env.alice)[0]
    assert (card["fromLat"], card["fromLng"], card["toLat"], card["toLng"]) == (35.1234568, 128.8894123, 35.1441, 129.0336)


def test_same_search_within_five_minutes_is_stored_once(env):
    assert search(env.alice).status_code == 200
    env.history_clock.now = NOW + timedelta(minutes=4, seconds=59)
    assert search(env.alice).status_code == 200

    assert len(env.rows_of(env.alice_id)) == 1


def test_same_search_after_five_minutes_is_stored_again(env):
    search(env.alice)
    env.history_clock.now = NOW + timedelta(minutes=5)
    search(env.alice)

    assert len(env.rows_of(env.alice_id)) == 2
    assert len(history(env.alice)) == 1  # 화면에서는 여전히 카드 한 장


def test_different_search_within_five_minutes_is_stored(env):
    search(env.alice)
    search(env.alice, arrive=kst(5, 9, 30).isoformat())  # 도착 시각이 다르면 다른 검색
    search(env.alice, buffer=15)  # 여유시간만 다르면 같은 검색 (묶기 기준과 같다)

    assert len(env.rows_of(env.alice_id)) == 2


def test_five_minute_rule_is_per_user(env):
    search(env.alice)
    search(env.bob)

    assert len(env.rows_of(env.alice_id)) == 1
    assert len(env.rows_of(env.bob_id)) == 1


def test_search_after_deleting_history_is_stored_again(env):
    """지운 기록은 5분 규칙의 대상이 아니다 (분리됐으므로)."""
    search(env.alice)
    env.alice.delete("/api/history")

    search(env.alice)

    assert len(env.rows_of(env.alice_id)) == 1
    assert len(history(env.alice)) == 1


# --- 캐시 적중 ---


def test_cache_hit_is_recorded_with_resolved_coordinates_and_same_rule(env):
    first = search(env.alice)
    env.history_clock.now = NOW + timedelta(minutes=2)
    second = search(env.alice)  # 5분 안 → 저장 안 함
    env.history_clock.now = NOW + timedelta(minutes=6)
    third = search(env.alice)  # 캐시 적중이지만 5분이 지남 → 저장

    assert [r.headers["X-Gilit-Route-Cache"] for r in (first, second, third)] == ["MISS", "HIT", "HIT"]
    attached = env.rows_of(env.alice_id)
    assert len(attached) == 2
    card = history(env.alice)[0]
    assert (card["fromLat"], card["toLng"]) == (35.2, 129.01)  # 캐시 적중이어도 처음 확정한 좌표를 쓴다


def test_cache_hit_of_anonymous_search_is_recorded(env):
    anonymous = env.anonymous()
    search(anonymous)
    response = search(anonymous)

    assert response.headers["X-Gilit-Route-Cache"] == "HIT"
    assert [owner for _, owner in env.rows()] == [None, None]


# --- 비로그인 ---


def test_anonymous_search_is_stored_without_user_and_never_listed(env):
    response = search(env.anonymous())

    assert response.status_code == 200
    assert env.rows() and all(owner is None for _, owner in env.rows())
    assert history(env.alice) == [] and history(env.bob) == []


def test_anonymous_repeats_are_all_stored(env):
    """비로그인은 같은 사람인지 알 수 없으므로 5분 규칙을 적용하지 않는다."""
    for _ in range(3):
        search(env.anonymous())

    assert [owner for _, owner in env.rows()] == [None, None, None]


def test_expired_session_counts_as_anonymous(env):
    env.alice.post("/api/auth/logout")

    search(env.alice)

    assert [owner for _, owner in env.rows()] == [None]


# --- 성공 응답만 저장 ---


def test_partial_success_is_stored(history_backend):
    env = Env(history_backend, FailingOptionProvider(failing=("free",)))

    response = search(env.alice)

    assert response.status_code == 200
    assert "free" not in [card["id"] for card in response.json()]
    assert len(history(env.alice)) == 1


def test_missing_recommend_card_stores_null_depart_time(history_backend):
    env = Env(history_backend, FailingOptionProvider(failing=("recommend",)))

    response = search(env.alice)

    assert response.status_code == 200
    assert history(env.alice)[0]["departTime"] is None


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"arrive": kst(3, 9).isoformat()}, 400),  # 이미 지난 시각
        ({"buffer": 7}, 400),  # 여유시간 값 오류
        ({"arrive": "not-a-time"}, 400),
    ],
)
def test_client_errors_are_not_stored(env, changes, status):
    response = search(env.alice, **changes)

    assert response.status_code == status
    assert env.rows() == []


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ProviderUnavailableError("연결 실패"), 502),
        (RouteNotFoundError("경로 없음"), 422),
    ],
)
def test_failed_searches_are_not_stored(history_backend, error, status):
    env = Env(history_backend, BrokenProvider(error))

    response = search(env.alice)

    assert response.status_code == status
    assert env.rows() == []


# --- 저장 실패는 응답에 영향 없음 ---


def test_store_failure_does_not_affect_route_response(env, monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("DB 연결 끊김")

    monkeypatch.setattr(env.history.store, "add", broken)

    with caplog.at_level(logging.ERROR, logger="app.api"):
        response = search(env.alice)

    assert response.status_code == 200
    assert len(response.json()) == 4
    assert "검색 기록 저장 실패" in caplog.text
    assert "출발" not in "\n".join(r.getMessage() for r in caplog.records)  # 검색 내용은 로그에 넣지 않는다


def test_session_lookup_failure_does_not_affect_route_response(env, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("회원 DB 장애")

    monkeypatch.setattr(env.app.state.auth, "authenticate", broken)

    assert search(env.alice).status_code == 200
    assert env.rows() == []


def test_routes_work_without_history_store(env):
    env.app.state.history = None

    assert search(env.alice).status_code == 200


# --- 저장 값 ---


def test_draft_trims_names_rounds_coordinates_and_picks_recommend():
    cards = [
        {"id": "time", "options": ["time"], "departTime": "2026-11-05T08:30:00+09:00"},
        {"id": "recommend", "options": ["recommend", "distance"], "departTime": "2026-11-05T08:20:00+09:00"},
    ]

    draft = draft_from_route_search(
        "  김해   시청 " + "가" * 120, "동의대학교", kst(5, 9), 10, Coordinate(35.123456789, 128.1), None, cards
    )

    assert draft.origin_name == ("김해 시청 " + "가" * 120)[:100]
    assert len(draft.origin_name) == 100
    assert (draft.origin_lat, draft.origin_lng) == (35.1234568, 128.1)
    assert (draft.dest_lat, draft.dest_lng) == (None, None)
    assert draft.recommended_depart_at == kst(5, 8, 20)
    assert (draft.travel_mode, draft.ai_summary, draft.buffer_min) == ("car", None, 10)


@pytest.mark.parametrize(
    "cards",
    [[], [{"options": ["time"], "departTime": "2026-11-05T08:30:00+09:00"}], [{"options": ["recommend"], "departTime": "x"}]],
)
def test_recommended_depart_at_is_none_without_valid_recommend_card(cards):
    assert recommended_depart_at(cards) is None
