"""그래프 경로의 카카오 캐시 우회. 실제 KakaoRouteProvider를 쓰고 HTTP(requests 세션)만 가짜로 바꾼다.

카카오 약관상 응답을 캐시(임시 포함)하지 않으므로, 그래프 조회는 Provider 메모리 캐시를 읽지도 쓰지도 않는다.
기존 F3(/api/departure)·F5(/api/routes)의 조회(get_duration, get_route_summary)는 지금처럼 캐시를 쓴다.
"""

import threading
import time
from unittest.mock import Mock

import requests
from fastapi.testclient import TestClient

from app.api.factory import create_app
from app.config import Settings
from app.departure import ROUTE_OPTIONS, KakaoRouteProvider
from app.route_graph import DailyCallBudget, GraphCard, GraphConfig, collect_route_graphs
from tests.conftest import DONGEUI_UNIV, GIMHAE_CITY_HALL, NOW, kst
from tests.test_kakao_provider import API_KEY, ok

RECOMMEND = ROUTE_OPTIONS["recommend"]
DEPART = kst(5, 8)


def fake_session() -> Mock:
    session = Mock(spec=requests.Session)
    session.get.side_effect = lambda *args, **kwargs: ok(duration=1855)
    return session


def collect(provider, cards=None):
    cards = cards or [GraphCard("recommend", RECOMMEND, DEPART)]
    return collect_route_graphs(provider, GIMHAE_CITY_HALL, DONGEUI_UNIV, cards, GraphConfig(), now=NOW, arrive=kst(5, 9),
                                budget=DailyCallBudget(1000), deadline=time.monotonic() + 5)


def test_graph_path_calls_http_every_time_for_the_same_slot():
    session = fake_session()
    provider = KakaoRouteProvider(API_KEY, session=session)

    provider.get_route_summary_uncached(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART, RECOMMEND)
    provider.get_route_summary_uncached(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART, RECOMMEND)

    assert session.get.call_count == 2
    assert provider.request_count == 2
    assert provider._cache == {}  # 그래프 응답은 캐시에 쓰지 않는다


def test_graph_service_twice_calls_http_twice_per_slot():
    session = fake_session()
    provider = KakaoRouteProvider(API_KEY, session=session)

    first = collect(provider)
    second = collect(provider)

    assert first == second
    assert len(first[0]["points"]) == 7
    assert session.get.call_count == 14
    assert provider._cache == {}


def test_graph_path_ignores_entries_cached_by_f3_f5():
    session = fake_session()
    provider = KakaoRouteProvider(API_KEY, session=session)
    provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART, RECOMMEND)  # F5가 캐시에 넣는다
    assert session.get.call_count == 1

    provider.get_route_summary_uncached(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART, RECOMMEND)

    assert session.get.call_count == 2  # 캐시 적중으로 돌려주지 않는다


def test_f3_f5_lookups_keep_using_the_cache():
    session = fake_session()
    provider = KakaoRouteProvider(API_KEY, session=session)

    assert provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART) == 1855  # F3
    assert provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART) == 1855
    provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART, RECOMMEND)  # F5, 같은 캐시 키
    provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART, ROUTE_OPTIONS["time"])
    provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART, ROUTE_OPTIONS["time"])

    assert session.get.call_count == 2  # recommend 1회 + time 1회
    assert len(provider._cache) == 2


def test_graph_lookups_do_not_change_f3_f5_cache_behaviour():
    session = fake_session()
    provider = KakaoRouteProvider(API_KEY, session=session)
    collect(provider)  # 그래프가 먼저 같은 슬롯을 조회해도
    calls = session.get.call_count

    provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART)
    provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART)

    assert session.get.call_count == calls + 1  # F3는 처음 한 번 부르고 그다음은 캐시


def test_graph_requests_use_same_parameters_as_summary_lookup():
    session = fake_session()
    provider = KakaoRouteProvider(API_KEY, session=session)

    provider.get_route_summary_uncached(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART, ROUTE_OPTIONS["free"])
    provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART, ROUTE_OPTIONS["free"])

    first, second = session.get.call_args_list
    assert first.kwargs["params"] == second.kwargs["params"]
    assert first.kwargs["params"]["avoid"] == "toll" and first.kwargs["params"]["summary"] == "true"
    assert first.kwargs["headers"] == {"Authorization": f"KakaoAK {API_KEY}"}


def test_graph_path_uses_one_session_per_worker_thread_and_f3_f5_keep_shared_session():
    shared = fake_session()
    created: list[tuple[int, Mock]] = []
    lock = threading.Lock()

    def factory():
        session = fake_session()
        with lock:
            created.append((threading.get_ident(), session))
        return session

    provider = KakaoRouteProvider(API_KEY, session=shared, session_factory=factory)
    barrier = threading.Barrier(2)

    def lookup():
        barrier.wait()
        for _ in range(2):
            provider.get_route_summary_uncached(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART, RECOMMEND)

    threads = [threading.Thread(target=lookup) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(created) == 2 and len({ident for ident, _ in created}) == 2  # 스레드마다 세션 하나
    assert [session.get.call_count for _, session in created] == [2, 2]  # 같은 스레드는 세션을 다시 쓴다
    assert shared.get.call_count == 0

    provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, DEPART)
    assert shared.get.call_count == 1  # F3/F5는 기존 공유 세션


def test_api_with_kakao_provider_has_no_response_cache():
    session = fake_session()
    provider = KakaoRouteProvider(API_KEY, session=session)
    api = TestClient(create_app(Settings(route_provider="kakao"), provider, clock=lambda: NOW))
    params = [("from", "김해시청"), ("to", "동의대학교"), ("arrive", kst(5, 9).isoformat()),
              ("fromLat", "35.2285"), ("fromLng", "128.8894"), ("toLat", "35.1441"), ("toLng", "129.0336"),
              ("card", f"recommend@{DEPART.isoformat()}")]

    first = api.get("/api/routes/graph", params=params)
    second = api.get("/api/routes/graph", params=params)

    assert first.status_code == second.status_code == 200
    assert first.json()[0]["points"][3] == {"departTime": "2026-11-05T08:00:00+09:00", "durationMin": 31}
    assert session.get.call_count == 14
    assert provider._cache == {}
