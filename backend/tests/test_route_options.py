"""경로 비교 1단계(공급자 계층) 테스트: RouteOption, 옵션별 요약·캐시, 통행료 파싱, avoid, Mock 옵션.

카카오는 가짜 세션으로 요청 파라미터만 확인한다. 실제 호출은 tests/test_kakao_live.py에 있다.
"""

import math
from datetime import timedelta

import pytest

from app.departure import (
    DEFAULT_ROUTE_OPTION,
    ROUTE_OPTIONS,
    MockRouteProvider,
    RouteNotFoundError,
    RouteOption,
    RouteProviderError,
    RouteSummary,
)
from app.routing import parse_detailed_route
from tests.conftest import DONGEUI_UNIV, GIMHAE_CITY_HALL, SEOUL_STATION, ConstantProvider, kst
from tests.test_kakao_provider import FakeMonotonic, make_provider, response, sent

RECOMMEND, TIME, DISTANCE, FREE = (ROUTE_OPTIONS[key] for key in ("recommend", "time", "distance", "free"))


def summary_body(duration=1855, distance=21970, fare=None, result_code=0):
    summary = {"duration": duration, "distance": distance}
    if fare is not None:
        summary["fare"] = fare
    return response(body={"routes": [{"result_code": result_code, "result_msg": "길찾기 성공", "summary": summary}]})


def detailed_body():
    return response(body={"routes": [{"result_code": 0, "summary": {"duration": 600, "distance": 2000, "fare": {"toll": 0}},
                                      "sections": [{"roads": [{"vertexes": [128.8, 35.2, 129.0, 35.22]}]}]}]})


# --- RouteOption ---


def test_route_options_are_the_four_compare_options():
    assert list(ROUTE_OPTIONS) == ["recommend", "time", "distance", "free"]
    assert [option.label for option in ROUTE_OPTIONS.values()] == ["추천", "최단시간", "최단거리", "무료도로"]
    assert FREE.priority == "RECOMMEND" and FREE.avoid == ("toll",)
    assert DEFAULT_ROUTE_OPTION is RECOMMEND


@pytest.mark.parametrize("kwargs", [{"priority": "FASTEST"}, {"avoid": ("highway",)}, {"avoid": ("toll", "bad")}])
def test_route_option_rejects_unknown_kakao_values(kwargs):
    with pytest.raises(ValueError):
        RouteOption("x", "x", **kwargs)


# --- 카카오 요약 요청 파라미터 ---


@pytest.mark.parametrize(
    ("option", "priority", "avoid"),
    [(RECOMMEND, "RECOMMEND", None), (TIME, "TIME", None), (DISTANCE, "DISTANCE", None), (FREE, "RECOMMEND", "toll")],
    ids=["recommend", "time", "distance", "free"],
)
def test_summary_request_parameters(option, priority, avoid):
    provider, session = make_provider(summary_body())

    provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10), option)

    _, params, _, _ = sent(session)
    assert params["priority"] == priority
    assert params["summary"] == "true"
    assert params.get("avoid") == avoid
    assert params["origin"] == "128.8894,35.2285"
    assert params["departure_time"] == "202611050810"
    assert "road_details" not in params


def test_multiple_avoid_values_are_joined_with_pipe():
    provider, session = make_provider(summary_body())

    provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8), RouteOption("x", "x", avoid=("toll", "motorway")))

    assert sent(session)[1]["avoid"] == "toll|motorway"


def test_get_duration_is_recommend_summary():
    provider, session = make_provider(summary_body(duration=1800))

    assert provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10)) == 1800

    _, params, _, _ = sent(session)
    assert params["priority"] == "RECOMMEND"
    assert params["summary"] == "true"
    assert "avoid" not in params


# --- 옵션별 캐시 ---


def test_cache_is_separate_per_option():
    provider, session = make_provider(*(summary_body(duration=1000 + i) for i in range(4)))
    depart = kst(5, 8, 10)

    durations = [provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, depart, option).duration_sec
                 for option in (RECOMMEND, TIME, DISTANCE, FREE)]
    again = [provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, depart, option).duration_sec
             for option in (RECOMMEND, TIME, DISTANCE, FREE)]

    assert durations == again == [1000, 1001, 1002, 1003]
    assert session.get.call_count == provider.request_count == 4


def test_get_duration_shares_cache_with_recommend_option():
    """출발시각 역산(/api/departure)과 경로 비교의 추천 옵션이 같은 조회를 두 번 하지 않는다."""
    provider, session = make_provider(summary_body(duration=1800))

    provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10), RECOMMEND)
    assert provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10)) == 1800

    assert session.get.call_count == 1


def test_option_cache_expires_after_ttl():
    clock = FakeMonotonic()
    provider, session = make_provider(summary_body(duration=1800, fare={"toll": 0}),
                                      summary_body(duration=1900, fare={"toll": 0}),
                                      cache_ttl_sec=600, monotonic=clock)

    first = provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10), FREE)
    clock.now += 600
    second = provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10), FREE)

    assert (first.duration_sec, second.duration_sec) == (1800, 1900)
    assert session.get.call_count == 2


def test_route_not_found_is_not_cached():
    provider, session = make_provider(summary_body(result_code=104), summary_body(duration=1700))

    with pytest.raises(RouteNotFoundError):
        provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8), TIME)
    assert provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8), TIME).duration_sec == 1700
    assert session.get.call_count == 2


# --- 통행료·거리 파싱 ---


@pytest.mark.parametrize(
    ("fare", "toll"),
    [({"taxi": 25000, "toll": 1600}, 1600), ({"toll": 0}, 0), ({"toll": 1600.0}, 1600), ({"taxi": 25000}, None), (None, None)],
    ids=["toll", "zero", "float", "no-toll-key", "no-fare"],
)
def test_toll_parsing(fare, toll):
    provider, _ = make_provider(summary_body(duration=1855, distance=21970, fare=fare))

    summary = provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8), RECOMMEND)

    assert summary == RouteSummary(duration_sec=1855, distance_m=21970, toll=toll)


@pytest.mark.parametrize("toll", [-100, "1600", True, math.nan, math.inf], ids=["negative", "string", "bool", "nan", "inf"])
def test_invalid_toll_is_provider_error(toll):
    provider, _ = make_provider(summary_body(fare={"toll": toll}))

    with pytest.raises(RouteProviderError, match="통행료"):
        provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8), RECOMMEND)


def test_missing_distance_is_provider_error():
    provider, _ = make_provider(response(body={"routes": [{"result_code": 0, "summary": {"duration": 1800}}]}))

    with pytest.raises(RouteProviderError, match="거리"):
        provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8), RECOMMEND)


# --- 상세 경로 avoid ---


def test_detailed_route_sends_avoid():
    provider, session = make_provider(detailed_body(), detailed_body())

    provider.get_detailed_route(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8), "RECOMMEND", ("toll",))
    provider.get_detailed_route(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8), "TIME")  # routing.py의 기존 호출 형태

    with_avoid, without_avoid = sent(session, 0)[1], sent(session, 1)[1]
    assert with_avoid["avoid"] == "toll"
    assert with_avoid["road_details"] == "true"
    assert "avoid" not in without_avoid


def test_detailed_route_rejects_unknown_avoid():
    provider, session = make_provider(detailed_body())

    with pytest.raises(ValueError):
        provider.get_detailed_route(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8), "RECOMMEND", ("highway",))
    assert session.get.call_count == 0


# --- MockRouteProvider ---


def test_mock_recommend_summary_matches_get_duration():
    """기존 출발시각 역산 결과(/api/departure의 mock 응답)가 바뀌지 않는다."""
    provider = MockRouteProvider()
    for hour in (3, 8, 18):
        depart = kst(5, hour)
        assert provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, depart, RECOMMEND).duration_sec == \
            provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, depart)


def test_mock_options_differ_like_real_routes():
    provider = MockRouteProvider()
    summaries = {key: provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 3), option)
                 for key, option in ROUTE_OPTIONS.items()}

    assert min(summaries, key=lambda key: summaries[key].duration_sec) == "time"
    assert min(summaries, key=lambda key: summaries[key].distance_m) == "distance"
    assert summaries["free"].toll == 0
    assert all(summaries[key].toll > 0 for key in ("recommend", "time", "distance"))
    assert all(summary.toll % 100 == 0 for summary in summaries.values())


@pytest.mark.parametrize("key", list(ROUTE_OPTIONS))
def test_mock_detailed_route_matches_summary_and_parses(key):
    option = ROUTE_OPTIONS[key]
    provider = MockRouteProvider()
    depart = kst(5, 8, 10)

    detailed = provider.get_detailed_route(GIMHAE_CITY_HALL, DONGEUI_UNIV, depart, option.priority, option.avoid)
    parsed = parse_detailed_route(detailed)  # routing.py가 카카오 응답을 읽는 함수 그대로
    summary = provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, depart, option)

    assert parsed["durationSec"] == summary.duration_sec
    assert parsed["distanceKm"] == round(summary.distance_m / 1000, 3)
    assert parsed["toll"] == summary.toll
    assert parsed["path"][0] == {"lat": GIMHAE_CITY_HALL.lat, "lng": GIMHAE_CITY_HALL.lng}
    assert parsed["path"][-1] == {"lat": DONGEUI_UNIV.lat, "lng": DONGEUI_UNIV.lng}
    longest = max((road for section in detailed["sections"] for road in section["roads"]), key=lambda road: road["distance"])
    assert longest["name"].startswith("가상")


def test_mock_paths_differ_per_option():
    provider = MockRouteProvider()
    paths = {
        tuple((p["lat"], p["lng"]) for p in parse_detailed_route(
            provider.get_detailed_route(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8), option.priority, option.avoid))["path"])
        for option in ROUTE_OPTIONS.values()
    }
    assert len(paths) == len(ROUTE_OPTIONS)


@pytest.mark.parametrize("origin", [GIMHAE_CITY_HALL, SEOUL_STATION])
@pytest.mark.parametrize("key", list(ROUTE_OPTIONS))
def test_mock_options_are_fifo(origin, key):
    """옵션마다 혼잡 계수가 달라도 먼저 출발하면 늦게 도착하지 않는다 (역산 엔진의 가정)."""
    provider = MockRouteProvider()
    previous = None
    for minute in range(0, 24 * 60):
        depart = kst(5, 0) + timedelta(minutes=minute)
        arrival = depart + timedelta(seconds=provider.get_route_summary(origin, DONGEUI_UNIV, depart, ROUTE_OPTIONS[key]).duration_sec)
        assert previous is None or arrival >= previous
        previous = arrival


def test_mock_same_point_has_no_route():
    with pytest.raises(RouteNotFoundError) as caught:
        MockRouteProvider().get_route_summary(GIMHAE_CITY_HALL, GIMHAE_CITY_HALL, kst(5, 8), FREE)
    assert caught.value.result_code == 104


def test_duration_only_providers_do_not_support_route_compare():
    provider = ConstantProvider(600)

    with pytest.raises(NotImplementedError):
        provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8))
    with pytest.raises(NotImplementedError):
        provider.get_detailed_route(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8), "RECOMMEND")
