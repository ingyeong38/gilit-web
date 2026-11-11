"""경로 비교 서비스(compare_routes) 테스트. HTTP 없이 가짜 Provider로 확인한다."""

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

import pytest

from app.config import Settings
from app.departure import (
    ROUTE_OPTIONS,
    DepartureError,
    DepartureSolver,
    MockRouteProvider,
    NoFeasibleDepartureError,
    ProviderQuotaExceededError,
    RouteNotFoundError,
    RouteProvider,
    RouteSummary,
    SolverConfig,
    TravelMode,
)
from app.routing import NO_FREE_ROUTE_MESSAGE, OptionRouteProvider, _route_name, compare_routes
from tests.conftest import DONGEUI_UNIV, GIMHAE_CITY_HALL, NOW, kst

ALL_OPTIONS = tuple(ROUTE_OPTIONS.values())
CONFIG = SolverConfig(max_calls=6)
ARRIVE = kst(5, 9)  # 다음 날 09:00 도착, 여유 10분 -> 목표 08:50
TARGET = ARRIVE - timedelta(minutes=10)


@dataclass
class FakeRoute:
    duration_sec: int = 1800  # 출발시각과 무관한 소요시간
    distance_m: int = 20000
    toll: int | None = 1000
    lane: float = 0.0  # 경로 좌표 차이. 같으면 같은 길이다
    road_name: str | None = "가상 고속도로"
    detail_extra_sec: int = 0  # 상세 응답 소요시간 - 요약 소요시간
    error: Exception | None = None


class FakeCompareProvider(RouteProvider):
    """옵션 키별로 정해 둔 경로를 돌려주고 옵션별 호출 수를 센다."""

    def __init__(self, **routes: FakeRoute) -> None:
        # 기본은 옵션마다 다른 길이고, 무료도로는 통행료가 없다.
        defaults = {key: FakeRoute(lane=index / 10, toll=0 if key == "free" else 1000)
                    for index, key in enumerate(ROUTE_OPTIONS)}
        self.routes = {**defaults, **routes}
        self.summary_calls: Counter[str] = Counter()
        self.detail_calls: Counter[str] = Counter()

    def get_duration(self, origin, dest, depart_at, travel_mode=TravelMode.CAR) -> int:
        return self.get_route_summary(origin, dest, depart_at).duration_sec

    def get_route_summary(self, origin, dest, depart_at, option=ROUTE_OPTIONS["recommend"]) -> RouteSummary:
        self.summary_calls[option.key] += 1
        route = self.routes[option.key]
        if route.error:
            raise route.error
        return RouteSummary(route.duration_sec, route.distance_m, route.toll)

    def get_detailed_route(self, origin, dest, depart_at, priority, avoid=()) -> dict:
        key = "free" if "toll" in avoid else priority.lower()
        self.detail_calls[key] += 1
        route = self.routes[key]
        road = {"name": route.road_name, "distance": route.distance_m,
                "vertexes": [128.8, 35.2, 128.9, 35.21 + route.lane, 129.01, 35.23]}
        return {"result_code": 0,
                "summary": {"duration": route.duration_sec + route.detail_extra_sec, "distance": route.distance_m,
                            "fare": {"toll": route.toll}},
                "sections": [{"roads": [road]}]}


class SpyProvider(RouteProvider):
    """다른 Provider를 감싸 옵션별 요약·상세 호출 수를 센다."""

    def __init__(self, inner: RouteProvider) -> None:
        self.inner = inner
        self.summary_calls: Counter[str] = Counter()
        self.detail_calls = 0

    def get_duration(self, origin, dest, depart_at, travel_mode=TravelMode.CAR) -> int:
        return self.inner.get_duration(origin, dest, depart_at, travel_mode)

    def get_route_summary(self, origin, dest, depart_at, option=ROUTE_OPTIONS["recommend"]) -> RouteSummary:
        self.summary_calls[option.key] += 1
        return self.inner.get_route_summary(origin, dest, depart_at, option)

    def get_detailed_route(self, origin, dest, depart_at, priority, avoid=()) -> dict:
        self.detail_calls += 1
        return self.inner.get_detailed_route(origin, dest, depart_at, priority, avoid)


def compare(provider, options=ALL_OPTIONS, config=CONFIG, arrive=ARRIVE, buffer=10):
    return compare_routes(provider, options, config, GIMHAE_CITY_HALL, DONGEUI_UNIV, arrive, buffer, clock=lambda: NOW)


def ids(result):
    return [(card.option.key, card.options) for card in result.cards]


# --- 옵션별 결과 ---


def test_mock_returns_one_card_per_option_from_the_engine():
    provider = MockRouteProvider()

    result = compare(provider)

    assert ids(result) == [(key, [key]) for key in ROUTE_OPTIONS]
    assert result.excluded == {}
    for card in result.cards:
        option = ROUTE_OPTIONS[card.option.key]
        expected = DepartureSolver(OptionRouteProvider(provider, option), CONFIG, clock=lambda: NOW).solve(
            GIMHAE_CITY_HALL, DONGEUI_UNIV, ARRIVE, 10)
        assert card.depart_at == expected.depart_at  # 엔진 결과 그대로
        assert card.arrive_at <= TARGET
        assert card.buffer_applied
        summary = provider.get_route_summary(GIMHAE_CITY_HALL, DONGEUI_UNIV, card.depart_at, option)
        assert (card.duration_sec, card.distance_km, card.toll) == (summary.duration_sec, round(summary.distance_m / 1000, 3), summary.toll)
        assert card.name.startswith("가상") and card.name.endswith(" 경유")
    assert result.cards[-1].toll == 0  # free


def test_card_dict_shape():
    card = compare(MockRouteProvider()).cards[0].to_dict()

    assert list(card) == ["id", "options", "label", "name", "departTime", "arriveTime", "durationMin", "distanceKm",
                          "toll", "fuel", "bufferApplied", "converged", "dataSource", "path", "aiSummary"]
    assert card["id"] == "recommend" and card["label"] == "추천" and card["dataSource"] == "mock"
    assert card["departTime"].endswith("+09:00")
    assert card["path"][0] == {"lat": GIMHAE_CITY_HALL.lat, "lng": GIMHAE_CITY_HALL.lng}


def test_data_source_is_passed_through():
    result = compare_routes(FakeCompareProvider(), ALL_OPTIONS[:1], CONFIG, GIMHAE_CITY_HALL, DONGEUI_UNIV, ARRIVE, 10,
                            clock=lambda: NOW, data_source="kakao")
    assert result.cards[0].to_dict()["dataSource"] == "kakao"


def test_constant_route_card_values():
    card = compare(FakeCompareProvider(), ALL_OPTIONS[:1]).cards[0]

    assert card.depart_at == kst(5, 8, 20)  # 08:50 - 30분
    assert card.to_dict()["arriveTime"] == "2026-11-05T08:50:00+09:00"
    assert card.to_dict()["durationMin"] == 30
    assert (card.distance_km, card.toll, card.name) == (20.0, 1000, "가상 고속도로 경유")


# --- 중복 병합 ---


def test_same_first_summary_and_path_is_merged_without_solving_again():
    provider = FakeCompareProvider(time=FakeRoute())  # recommend와 같은 길

    result = compare(provider)

    assert ids(result) == [("recommend", ["recommend", "time"]), ("distance", ["distance"]), ("free", ["free"])]
    assert provider.summary_calls["time"] == 1  # 첫 조회만 하고 멈춘다
    assert provider.detail_calls["time"] == 1  # 좌표 확인 1회


def test_same_first_summary_but_different_path_is_computed_separately():
    provider = FakeCompareProvider(time=FakeRoute(lane=0.05))  # 요약은 같지만 다른 길

    result = compare(provider)

    assert [card.option.key for card in result.cards] == ["recommend", "time", "distance", "free"]
    assert provider.summary_calls["time"] == provider.summary_calls["recommend"]  # 첫 조회를 다시 하지 않는다
    assert provider.detail_calls["time"] == 2  # 좌표 확인 + 카드


def test_same_path_found_after_solving_is_merged():
    # 첫 조회 요약은 다르지만(거리 표기가 다름) 상세 좌표가 같으면 같은 길이다.
    provider = FakeCompareProvider(time=FakeRoute(distance_m=20001))

    result = compare(provider, ALL_OPTIONS[:2])

    assert ids(result) == [("recommend", ["recommend", "time"])]
    assert result.cards[0].distance_km == 20.0  # 앞 카드의 응답 그대로


def test_free_with_zero_toll_merges_into_toll_free_recommend():
    provider = FakeCompareProvider(recommend=FakeRoute(toll=0), free=FakeRoute(toll=0))

    assert ids(compare(provider, (ROUTE_OPTIONS["recommend"], ROUTE_OPTIONS["free"]))) == [("recommend", ["recommend", "free"])]


# --- 무료도로 ---


def test_free_route_with_toll_is_excluded():
    provider = FakeCompareProvider(free=FakeRoute(toll=500, lane=0.3))

    result = compare(provider)

    assert [card.option.key for card in result.cards] == ["recommend", "time", "distance"]
    assert result.excluded == {"free": NO_FREE_ROUTE_MESSAGE}


def test_free_same_as_toll_card_is_excluded_without_detail_call():
    provider = FakeCompareProvider(free=FakeRoute())  # recommend와 같은 유료 경로

    result = compare(provider)

    assert "free" in result.excluded
    assert all("free" not in card.options for card in result.cards)
    assert provider.summary_calls["free"] == 1
    assert provider.detail_calls["free"] == 0


# --- 부분 실패 ---


def test_failed_option_is_excluded_and_others_remain():
    provider = FakeCompareProvider(distance=FakeRoute(error=RouteNotFoundError("경로를 찾을 수 없습니다.", 103)))

    result = compare(provider)

    assert [card.option.key for card in result.cards] == ["recommend", "time", "free"]
    assert result.excluded == {"distance": "경로를 찾을 수 없습니다."}


def test_all_failed_raises_first_option_error():
    provider = FakeCompareProvider(**{key: FakeRoute(error=RouteNotFoundError(f"{key} 실패")) for key in ROUTE_OPTIONS})

    with pytest.raises(RouteNotFoundError, match="recommend 실패"):
        compare(provider)


def test_all_too_late_raises_engine_error():
    provider = FakeCompareProvider(**{key: FakeRoute(duration_sec=10 * 3600, lane=i) for i, key in enumerate(ROUTE_OPTIONS)})

    with pytest.raises(NoFeasibleDepartureError):
        compare(provider)


def test_provider_error_stops_immediately():
    provider = FakeCompareProvider(time=FakeRoute(error=ProviderQuotaExceededError("한도 초과")))

    with pytest.raises(ProviderQuotaExceededError):
        compare(provider)
    assert provider.summary_calls["distance"] == provider.summary_calls["free"] == 0


def test_empty_options_rejected():
    with pytest.raises(ValueError):
        compare(FakeCompareProvider(), ())


# --- 호출 수 ---


def test_too_small_budget_excludes_options_instead_of_guessing():
    """조회 2회로는 Mock에서 제시간 출발시각을 하나도 확인하지 못한다. 확인 안 된 시각을 안내하지 않는다."""
    provider = SpyProvider(MockRouteProvider())

    with pytest.raises(DepartureError, match="출발시각을 계산하지 못했습니다"):
        compare(provider, config=SolverConfig(max_calls=2))
    assert all(calls <= 2 for calls in provider.summary_calls.values())
    assert provider.detail_calls == 0


@pytest.mark.parametrize("max_calls", [3, 4, 6])
def test_lookups_are_capped_per_option(max_calls):
    provider = SpyProvider(MockRouteProvider())

    result = compare(provider, config=SolverConfig(max_calls=max_calls))

    assert all(calls <= max_calls for calls in provider.summary_calls.values())
    # 상세 조회는 카드를 만든 옵션만 1회. 한도 안에 출발시각을 못 찾은 옵션은 상세 조회 없이 빠진다.
    assert provider.detail_calls == len(result.cards)
    assert len(result.cards) + len(result.excluded) == len(ROUTE_OPTIONS)
    assert result.lookups == sum(provider.summary_calls.values()) + provider.detail_calls
    assert result.lookups <= len(ROUTE_OPTIONS) * (max_calls + 2)
    for card in result.cards:
        assert card.arrive_at <= TARGET  # 한도에 걸려도(converged=False) 늦지 않는다


def test_merged_option_costs_two_lookups():
    provider = FakeCompareProvider(time=FakeRoute())

    result = compare(provider, ALL_OPTIONS[:2])

    assert result.lookups == provider.summary_calls["recommend"] + 1 + 1 + 1  # recommend 요약·상세 + time 요약·상세


# --- 상세 소요시간이 요약과 다를 때 ---


def test_longer_detail_duration_moves_departure_earlier(caplog):
    provider = FakeCompareProvider(recommend=FakeRoute(detail_extra_sec=300))

    with caplog.at_level(logging.WARNING, logger="app.routing"):
        card = compare(provider, ALL_OPTIONS[:1]).cards[0]

    assert card.depart_at == kst(5, 8, 15)  # 08:50 - 35분
    assert card.duration_sec == 2100
    assert card.arrive_at <= TARGET
    assert card.detail_depart_at == kst(5, 8, 20)
    assert "상세 소요시간이 요약과 다릅니다" in caplog.text


def test_shorter_detail_duration_keeps_departure():
    card = compare(FakeCompareProvider(recommend=FakeRoute(detail_extra_sec=-120)), ALL_OPTIONS[:1]).cards[0]

    assert card.depart_at == kst(5, 8, 20)
    assert card.duration_sec == 1680


def test_detail_mismatch_that_needs_leaving_before_now_is_excluded():
    provider = FakeCompareProvider(recommend=FakeRoute(detail_extra_sec=3600))

    with pytest.raises(NoFeasibleDepartureError):
        compare(provider, ALL_OPTIONS[:1], arrive=kst(4, 7), buffer=0)  # 06:30 출발 -> 상세로는 05:30 출발해야 함


# --- 카드 이름 ---


def test_route_name_uses_longest_road_by_total_distance():
    route = {"sections": [{"roads": [{"name": "남해고속도로", "distance": 8000}, {"name": "가야대로", "distance": 9000}]},
                          {"roads": [{"name": "남해고속도로", "distance": 3000}, {"name": "", "distance": 20000}]}]}

    assert _route_name(route, "추천") == "남해고속도로 경유"


@pytest.mark.parametrize("roads", [[], [{"name": "", "distance": 100}], [{"distance": 100}], [{"name": "도로", "distance": None}]])
def test_route_name_falls_back_to_label(roads):
    assert _route_name({"sections": [{"roads": roads}]}, "최단거리") == "최단거리"


def test_unnamed_roads_use_label_in_card():
    card = compare(FakeCompareProvider(recommend=FakeRoute(road_name=None)), ALL_OPTIONS[:1]).cards[0]

    assert card.name == "추천"


# --- 설정 ---


def test_compare_settings_defaults():
    settings = Settings.from_env({})

    assert settings.route_options() == ALL_OPTIONS
    assert settings.compare_solver_config().max_calls == 6


def test_compare_settings_from_env():
    settings = Settings.from_env({"ROUTE_COMPARE_OPTIONS": " Free, recommend ", "ROUTE_COMPARE_MAX_CALLS": "4"})

    assert [option.key for option in settings.route_options()] == ["free", "recommend"]  # 적은 순서가 카드 순서
    assert settings.compare_solver_config().max_calls == 4


@pytest.mark.parametrize("value", ["recommend,fastest", "time,time", "recommend;time"])
def test_compare_options_reject_invalid(value):
    with pytest.raises(ValueError, match="ROUTE_COMPARE_OPTIONS"):
        Settings.from_env({"ROUTE_COMPARE_OPTIONS": value})


def test_compare_max_calls_must_allow_engine():
    with pytest.raises(ValueError, match="max_calls"):
        Settings.from_env({"ROUTE_COMPARE_MAX_CALLS": "1"}).compare_solver_config()
