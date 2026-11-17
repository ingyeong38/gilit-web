"""GET /api/routes/graph (출발시각별 소요시간 그래프) 테스트. HTTP 없이 가짜 Provider로 확인한다.

카카오 약관상 응답을 캐시하지 않는다. 같은 요청을 두 번 보내면 Provider도 두 번 부른다.
실제 KakaoRouteProvider의 캐시 우회는 tests/test_route_graph_kakao.py에서 확인한다.
"""

import threading
import time
from datetime import timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.factory import create_app
from app.config import Settings
from app.departure import (
    KST,
    ROUTE_OPTIONS,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RouteNotFoundError,
    RouteSummary,
)
from app.route_graph import GRAPH_MAX_SLOTS, DailyCallBudget, GraphCard, GraphConfig, collect_route_graphs
from tests.conftest import DONGEUI_UNIV, GIMHAE_CITY_HALL, NOW, kst
from tests.test_route_compare import FakeCompareProvider, FakeRoute

ARRIVE = kst(5, 9)  # 다음 날 09:00
DEPART = kst(5, 8)  # 카드의 권장 출발시각
COORDS = [("fromLat", "35.2285"), ("fromLng", "128.8894"), ("toLat", "35.1441"), ("toLng", "129.0336")]
SLOT_OFFSETS = (-45, -30, -15, 0, 15, 30, 45)


class GraphProvider(FakeCompareProvider):
    """FakeCompareProvider에 슬롯별 소요시간·실패·대기를 더한다. 작업 스레드에서 불리므로 기록은 잠금 안에서 한다.

    소요시간은 출발 '분'에 따라 다르다(30분 + 분). 응답의 점이 제 슬롯 값인지 확인할 수 있다.
    """

    def __init__(self, failures=None, block=None, **routes) -> None:
        super().__init__(**routes)
        self.failures = failures or {}  # (옵션 키, 출발시각) -> 예외
        self.block = block or {}  # 옵션 키 -> threading.Event. set될 때까지 기다린다
        self.calls: list[tuple[str, object]] = []
        self.lock = threading.Lock()

    def get_route_summary(self, origin, dest, depart_at, option=ROUTE_OPTIONS["recommend"]) -> RouteSummary:
        with self.lock:
            self.calls.append((option.key, depart_at))
            super().get_route_summary(origin, dest, depart_at, option)  # 옵션별 호출 수와 옵션 전체 오류
        event = self.block.get(option.key)
        if event is not None:
            event.wait(5)
        error = self.failures.get((option.key, depart_at))
        if error is not None:
            raise error
        return RouteSummary(duration_sec=(30 + depart_at.minute) * 60, distance_m=20000, toll=1000)


class PlaceGraphProvider(GraphProvider):
    def search_places(self, query):
        places = {"김해시청": (35.2285, 128.8894), "동의대학교": (35.1441, 129.0336)}
        lat, lng = places[query]
        return [{"id": query, "name": query, "address": "", "lat": lat, "lng": lng}]


def make_api(provider, **settings) -> TestClient:
    return TestClient(create_app(Settings(**settings), provider, clock=lambda: NOW))


def card(key: str, depart=DEPART) -> str:
    return f"{key}@{depart.isoformat()}"


def get_graph(api, *cards, coords=True, arrive=ARRIVE, extra=()):
    params = [("from", "김해시청"), ("to", "동의대학교"), ("arrive", arrive.isoformat())]
    params += COORDS if coords else []
    params += [("card", value) for value in cards] + list(extra)
    return api.get("/api/routes/graph", params=params)


def slot(offset_min: int, base=DEPART):
    return base + timedelta(minutes=offset_min)


def by_id(body):
    return {graph["routeId"]: graph["points"] for graph in body}


# --- 정상 응답 ---


def test_returns_unwrapped_array_with_kst_points_per_card():
    provider = GraphProvider()
    response = get_graph(make_api(provider), card("recommend"), card("time"))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert isinstance(body, list)
    assert [graph["routeId"] for graph in body] == ["recommend", "time"]  # card 순서, card id 그대로
    # 15분 간격 -45~+45, 시간순. 카드 2개 x 7 = 14 > 상한 13이라 마지막 카드의 +45분 하나가 빠진다
    expected = {"recommend": SLOT_OFFSETS, "time": SLOT_OFFSETS[:-1]}
    for graph in body:
        assert list(graph) == ["routeId", "points"]
        times = [point["departTime"] for point in graph["points"]]
        assert times == [slot(offset).isoformat() for offset in expected[graph["routeId"]]]
        assert all(value.endswith("+09:00") for value in times)
        for point in graph["points"]:
            assert list(point) == ["departTime", "durationMin"]
            minute = int(point["departTime"][14:16])
            assert point["durationMin"] == 30 + minute  # 제 슬롯의 값
            assert point["durationMin"] >= 0
    assert provider.summary_calls == {"recommend": 7, "time": 6}


def test_utc_card_time_is_answered_in_kst():
    utc = DEPART.astimezone(timezone.utc)
    response = get_graph(make_api(GraphProvider()), f"recommend@{utc.isoformat().replace('+00:00', 'Z')}")

    assert response.status_code == 200
    assert response.json()[0]["points"][3]["departTime"] == "2026-11-05T08:00:00+09:00"


def test_buffer_and_coordinates_together_are_accepted_and_buffer_ignored():
    provider = GraphProvider()
    api = make_api(provider)

    for buffer in ("10", "7", "abc", ""):
        response = get_graph(api, card("recommend"), extra=[("buffer", buffer)])
        assert response.status_code == 200, (buffer, response.json())
        assert len(response.json()[0]["points"]) == 7


def test_request_without_coordinates_resolves_place_names():
    response = get_graph(make_api(PlaceGraphProvider()), card("recommend"), coords=False)

    assert response.status_code == 200
    assert len(response.json()[0]["points"]) == 7


def test_request_without_coordinates_on_provider_without_place_search_is_422():
    provider = GraphProvider()
    response = get_graph(make_api(provider), card("recommend"), coords=False)

    assert response.status_code == 422
    assert "장소를 하나로 확인할 수 없어요" in response.json()["message"]
    assert provider.calls == []


def test_mock_route_provider_mode_works_without_kakao():
    response = get_graph(TestClient(create_app(Settings(), clock=lambda: NOW)), card("recommend"), card("free"))

    assert response.status_code == 200
    assert [len(graph["points"]) for graph in response.json()] == [7, 6]  # 상한 13


# --- 슬롯 ---


def test_slots_before_now_are_left_out():
    depart = NOW + timedelta(minutes=15)  # 05:30 ~ 06:15 슬롯은 지금(06:00) 이전
    provider = GraphProvider()
    response = get_graph(make_api(provider), card("recommend", depart), arrive=kst(4, 9))

    assert response.status_code == 200
    times = [point["departTime"] for point in response.json()[0]["points"]]
    assert times == [slot(offset, depart).isoformat() for offset in (-15, 0, 15, 30, 45)]
    assert all(depart_at >= NOW for _, depart_at in provider.calls)


def test_card_with_past_depart_time_is_accepted():
    depart = NOW - timedelta(minutes=30)
    response = get_graph(make_api(GraphProvider()), card("recommend", depart), arrive=kst(4, 9))

    assert response.status_code == 200
    assert [point["departTime"] for point in response.json()[0]["points"]] == [
        NOW.isoformat(), (NOW + timedelta(minutes=15)).isoformat()]


def test_slots_at_or_after_arrive_are_not_called_or_counted():
    depart = ARRIVE - timedelta(minutes=10)  # 08:50. +15분(09:05)부터는 arrive 이후
    provider = GraphProvider()
    api = make_api(provider, graph_daily_call_budget=100)
    response = get_graph(api, card("recommend", depart))

    assert response.status_code == 200
    times = [point["departTime"] for point in response.json()[0]["points"]]
    assert times == [slot(offset, depart).isoformat() for offset in (-45, -30, -15, 0)]
    assert len(provider.calls) == 4
    assert all(depart_at < ARRIVE for _, depart_at in provider.calls)
    assert api.app.state.graph_budget.remaining(NOW) == 96  # 뺀 슬롯은 예산에 세지 않는다


def test_card_with_every_slot_excluded_is_left_out_and_other_cards_are_unaffected():
    arrive = NOW + timedelta(minutes=10)  # 06:10
    # time: 05:55 출발(지난 시각 허용). 05:10~05:55는 지났고 06:10부터는 arrive 이후 -> 슬롯 없음
    # recommend: 06:05 출발. 06:05 하나만 남는다
    provider = GraphProvider()
    response = get_graph(make_api(provider), card("time", NOW - timedelta(minutes=5)),
                         card("recommend", NOW + timedelta(minutes=5)), arrive=arrive)

    assert response.status_code == 200
    assert response.json() == [{"routeId": "recommend",
                                "points": [{"departTime": (NOW + timedelta(minutes=5)).isoformat(), "durationMin": 35}]}]
    assert provider.summary_calls == {"recommend": 1}


def test_card_with_every_slot_excluded_alone_returns_empty_array():
    provider = GraphProvider()
    response = get_graph(make_api(provider), card("time", NOW - timedelta(minutes=5)), arrive=NOW + timedelta(minutes=10))

    assert response.status_code == 200
    assert response.json() == []
    assert provider.calls == []


def test_excluded_slots_do_not_use_the_slot_cap():
    # recommend는 arrive 직전이라 4개, time은 7개 -> 11개 <= 13. 제외 슬롯이 상한을 먹으면 time이 잘린다
    provider = GraphProvider()
    response = get_graph(make_api(provider), card("recommend", ARRIVE - timedelta(minutes=10)), card("time"))

    graphs = by_id(response.json())
    assert len(graphs["recommend"]) == 4
    assert [point["departTime"] for point in graphs["time"]] == [slot(offset).isoformat() for offset in SLOT_OFFSETS]
    assert len(provider.calls) == 11


def test_card_whose_slots_are_all_past_returns_empty_array_without_calls():
    depart = NOW - timedelta(hours=2)
    provider = GraphProvider()
    response = get_graph(make_api(provider), card("recommend", depart), arrive=kst(4, 9))

    assert response.status_code == 200
    assert response.json() == []
    assert provider.calls == []


def test_total_slots_are_clamped_and_every_card_keeps_its_center():
    provider = GraphProvider()
    response = get_graph(make_api(provider), *(card(key) for key in ROUTE_OPTIONS))

    assert response.status_code == 200
    graphs = by_id(response.json())
    assert sum(len(points) for points in graphs.values()) == GRAPH_MAX_SLOTS == 13
    assert len(provider.calls) == 13
    for points in graphs.values():
        times = [point["departTime"] for point in points]
        # 권장 출발시각과 앞뒤 15분은 모든 카드에 남는다 (가까운 슬롯부터 고른다)
        assert {slot(offset).isoformat() for offset in (-15, 0, 15)} <= set(times)


def test_slot_settings_change_window():
    provider = GraphProvider()
    api = make_api(provider, graph_slots_before=1, graph_slots_after=2, graph_slot_interval_min=10)
    response = get_graph(api, card("recommend"))

    assert [point["departTime"] for point in response.json()[0]["points"]] == [
        slot(offset).isoformat() for offset in (-10, 0, 10, 20)]


# --- 부분 실패와 오류 ---


def test_failed_slot_is_left_out_and_others_are_200():
    provider = GraphProvider(failures={("recommend", slot(15)): ProviderUnavailableError("서버 오류")})
    response = get_graph(make_api(provider), card("recommend"))

    assert response.status_code == 200
    times = [point["departTime"] for point in response.json()[0]["points"]]
    assert slot(15).isoformat() not in times and len(times) == 6


def test_card_whose_slots_all_fail_is_left_out():
    provider = GraphProvider(failures={("time", slot(offset)): RouteNotFoundError("경로 없음") for offset in SLOT_OFFSETS})
    response = get_graph(make_api(provider), card("recommend"), card("time"))

    assert response.status_code == 200
    assert [graph["routeId"] for graph in response.json()] == ["recommend"]


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (ProviderQuotaExceededError("길찾기 API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."), 503, "호출 한도"),
        (ProviderTimeoutError("길찾기 서버 응답이 늦습니다. 잠시 후 다시 시도해 주세요."), 504, "응답이 늦습니다"),
        (ProviderUnavailableError("HTTP 500 내부 정보"), 502, "길찾기 정보를 가져오지 못했습니다"),
        (RouteNotFoundError("해당 조건으로 자동차 경로를 찾을 수 없습니다."), 422, "경로를 찾을 수 없습니다"),
    ],
)
def test_all_slots_failing_uses_existing_error_mapping(error, status, message):
    provider = GraphProvider(recommend=FakeRoute(error=error))
    response = get_graph(make_api(provider), card("recommend"))

    assert response.status_code == status
    assert list(response.json()) == ["message"]
    assert message in response.json()["message"]
    assert "HTTP 500" not in response.json()["message"]


def test_quota_wins_over_timeout_when_nothing_succeeded():
    failures = {("recommend", slot(offset)): ProviderTimeoutError("늦음") for offset in SLOT_OFFSETS}
    failures[("recommend", slot(0))] = ProviderQuotaExceededError("길찾기 API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.")
    response = get_graph(make_api(GraphProvider(failures=failures)), card("recommend"))

    assert response.status_code == 503


def test_time_budget_returns_points_received_so_far():
    release = threading.Event()
    provider = GraphProvider(block={"time": release})
    api = make_api(provider, graph_time_budget_sec=0.3)
    try:
        started = time.monotonic()
        response = get_graph(api, card("recommend"), card("time"))
        elapsed = time.monotonic() - started
    finally:
        release.set()  # 남은 작업 스레드를 풀어 준다

    assert response.status_code == 200
    graphs = by_id(response.json())
    assert list(graphs) == ["recommend"]  # 시간 안에 온 점만
    assert 0 < len(graphs["recommend"]) < 7
    assert elapsed < 3


def test_time_budget_with_no_points_is_504():
    release = threading.Event()
    provider = GraphProvider(block={"recommend": release})
    try:
        response = get_graph(make_api(provider, graph_time_budget_sec=0.2), card("recommend"))
    finally:
        release.set()

    assert response.status_code == 504
    assert response.json()["message"]


# --- 일일 호출 예산 ---


def test_exhausted_daily_budget_is_503_without_any_provider_call():
    provider = PlaceGraphProvider()
    api = make_api(provider, graph_daily_call_budget=0)

    response = get_graph(api, card("recommend"), coords=False)

    assert response.status_code == 503
    assert "그래프" in response.json()["message"]
    assert provider.calls == [] and provider.summary_calls == {}


def test_budget_counts_real_calls_and_runs_out_mid_request():
    provider = GraphProvider()
    api = make_api(provider, graph_daily_call_budget=10)

    first = get_graph(api, card("recommend"))
    second = get_graph(api, card("recommend"))  # 남은 3회만 부른다
    third = get_graph(api, card("recommend"))

    assert first.status_code == 200 and len(first.json()[0]["points"]) == 7
    assert second.status_code == 200 and len(second.json()[0]["points"]) == 3
    assert third.status_code == 503
    assert len(provider.calls) == 10


def test_daily_budget_resets_on_kst_date():
    budget = DailyCallBudget(limit=1)

    assert budget.try_acquire(kst(4, 23, 59))
    assert not budget.try_acquire(kst(4, 23, 59))
    assert budget.remaining(kst(4, 23, 59)) == 0
    # UTC로는 같은 날(11-04 15:00Z)이어도 KST로 다음 날이면 새로 센다
    assert budget.try_acquire(kst(5, 0, 0).astimezone(timezone.utc))


# --- 캐시 없음과 요청 안 합치기 ---


def test_same_request_twice_calls_provider_twice():
    provider = GraphProvider()
    api = make_api(provider)

    assert get_graph(api, card("recommend")).status_code == 200
    assert get_graph(api, card("recommend")).status_code == 200

    assert provider.summary_calls["recommend"] == 14
    assert "x-gilit-route-cache" not in get_graph(api, card("recommend")).headers


def test_same_lookup_inside_one_request_is_called_once():
    # API 입력으로는 카드 id와 옵션이 1:1이라 생기지 않는다. 서비스 함수 수준에서 합치기를 확인한다.
    provider = GraphProvider()
    option = ROUTE_OPTIONS["recommend"]
    cards = [GraphCard("a", option, DEPART), GraphCard("b", option, DEPART + timedelta(minutes=15))]

    # arrive를 늦게 둬서 arrive 이후 제외와 섞이지 않게 한다 (b의 +45분 = 09:00)
    graphs = collect_route_graphs(provider, GIMHAE_CITY_HALL, DONGEUI_UNIV, cards, GraphConfig(), now=NOW,
                                  arrive=kst(5, 10), budget=DailyCallBudget(100), deadline=time.monotonic() + 5)

    assert len(provider.calls) == 8  # 07:15 ~ 09:00, 겹치는 6개는 한 번만
    assert len(set(provider.calls)) == 8
    points = {graph["routeId"]: graph["points"] for graph in graphs}
    assert len(points["a"]) == len(points["b"]) == 7
    assert points["a"][3] == points["b"][2]  # 08:00은 같은 조회 결과


def test_concurrent_lookups_respect_max_workers():
    active, peak, lock = 0, 0, threading.Lock()

    class CountingProvider(GraphProvider):
        def get_route_summary(self, *args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            try:
                return super().get_route_summary(*args, **kwargs)
            finally:
                with lock:
                    active -= 1

    response = get_graph(make_api(CountingProvider(), graph_max_workers=2), card("recommend"), card("time"))

    assert response.status_code == 200
    assert 1 < peak <= 2


# --- card 검증 ---


@pytest.mark.parametrize(
    ("cards", "message"),
    [
        ((), "card"),
        (tuple(card(key) for key in ROUTE_OPTIONS) + (card("recommend", slot(5)),), "1~4개"),
        ((card("recommend"), card("recommend", slot(15))), "두 번"),
        ((card("fastest"),), "recommend, time, distance, free"),
        (("recommend",), "형식"),
        (("@" + DEPART.isoformat(),), "형식"),
        (("recommend@",), "시간대"),
        (("recommend@2026-11-05T08:00:00",), "시간대"),
        (("recommend@내일",), "시간대"),
        ((card("recommend", ARRIVE),), "24시간"),
        ((card("recommend", ARRIVE + timedelta(minutes=1)),), "24시간"),
        ((card("recommend", ARRIVE - timedelta(hours=24, minutes=1)),), "24시간"),
    ],
)
def test_invalid_cards_are_400_with_message(cards, message):
    provider = GraphProvider()
    response = get_graph(make_api(provider), *cards)

    assert response.status_code == 400, response.json()
    assert list(response.json()) == ["message"]
    assert message in response.json()["message"]
    assert provider.calls == []


def test_card_exactly_24_hours_before_arrive_is_accepted():
    response = get_graph(make_api(GraphProvider()), card("recommend", ARRIVE - timedelta(hours=24)))

    assert response.status_code == 200


def test_id_is_split_at_the_last_at_sign():
    # 시각 쪽에는 @가 없으므로 마지막 @ 앞이 id다. "a@b"처럼 @가 든 id는 허용 옵션이 아니어서 400이다.
    response = get_graph(make_api(GraphProvider()), f"recommend@x@{DEPART.isoformat()}")

    assert response.status_code == 400
    assert "recommend, time, distance, free" in response.json()["message"]


def test_card_id_must_be_a_configured_compare_option():
    provider = GraphProvider()
    api = make_api(provider, route_compare_options=("recommend", "free"))

    assert get_graph(api, card("free")).status_code == 200
    response = get_graph(api, card("time"))
    assert response.status_code == 400
    assert "recommend, free" in response.json()["message"]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ([("fromLat", "35.2")], "출발지 위도와 경도를 함께"),
        ([("toLng", "129.0")], "목적지 위도와 경도를 함께"),
    ],
)
def test_coordinates_must_come_in_pairs(extra, message):
    params = [("from", "김해시청"), ("to", "동의대학교"), ("arrive", ARRIVE.isoformat()), ("card", card("recommend"))]
    response = make_api(GraphProvider()).get("/api/routes/graph", params=params + extra)

    assert response.status_code == 400
    assert message in response.json()["message"]


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ([("to", "동의대학교"), ("arrive", ARRIVE.isoformat())], "출발지가 필요합니다."),
        ([("from", "김해시청"), ("to", "김해시청"), ("arrive", ARRIVE.isoformat())], "출발지와 다른 목적지"),
        ([("from", "김해시청"), ("to", "동의대학교"), ("arrive", "내일")], "ISO 8601"),
        ([("from", "김해시청"), ("to", "동의대학교"), ("arrive", ARRIVE.isoformat()), ("fromLat", "91"), ("fromLng", "1")],
         "출발지 위도는 -90~90"),
    ],
)
def test_route_query_validation_is_reused(params, message):
    response = make_api(GraphProvider()).get("/api/routes/graph", params=params + [("card", card("recommend"))])

    assert response.status_code == 400
    assert message in response.json()["message"]


def test_passed_arrive_is_400():
    response = get_graph(make_api(GraphProvider()), card("recommend", NOW - timedelta(hours=1)), arrive=NOW)

    assert response.status_code == 400
    assert response.json()["message"] == "도착 희망 시각이 이미 지났습니다."


def test_openapi_lists_graph_endpoint():
    schema = make_api(GraphProvider()).get("/openapi.json").json()

    operation = schema["paths"]["/api/routes/graph"]["get"]
    assert "card" in {parameter["name"] for parameter in operation["parameters"]}
