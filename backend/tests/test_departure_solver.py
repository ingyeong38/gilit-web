from datetime import timedelta

import pytest

from app.departure import (
    ArrivalTimePassedError,
    DepartureSolver,
    MockRouteProvider,
    NoFeasibleDepartureError,
    RouteProvider,
    SearchBudgetExceededError,
    SolverConfig,
    TravelMode,
)
from tests.conftest import (
    DONGEUI_UNIV,
    GIMHAE_CITY_HALL,
    HAEUNDAE,
    NOW,
    SEOUL_STATION,
    ConstantProvider,
    SpyProvider,
    brute_force_latest,
    kst,
)

MINUTE = timedelta(minutes=1)


def floor_minute(value):
    return value.replace(second=0, microsecond=0)


# 혼잡도가 없는 경우

@pytest.mark.parametrize("buffer_min", [0, 5, 10, 15])
def test_no_congestion_matches_simple_subtraction(clock, buffer_min):
    provider = MockRouteProvider(peaks=())
    solver = DepartureSolver(provider, clock=clock)
    arrive = kst(5, 9)

    result = solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, arrive, buffer_min)

    duration = timedelta(seconds=provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, arrive))
    assert result.depart_at == floor_minute(arrive - duration - timedelta(minutes=buffer_min))
    assert result.duration_sec == duration.total_seconds()
    assert result.converged


def test_constant_duration_on_minute_boundary_is_exact(clock):
    solver = DepartureSolver(ConstantProvider(40 * 60), clock=clock)

    result = solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 9), buffer_min=10)

    assert result.depart_at == kst(5, 8, 10)
    assert result.arrive_at == kst(5, 8, 50)
    assert result.duration_min == 40


# 출퇴근 혼잡 구간을 지나는 경우

def test_rush_hour_departs_earlier_than_simple_calculation(clock):
    provider = MockRouteProvider()
    solver = DepartureSolver(provider, clock=clock)
    arrive = kst(5, 9)
    target = arrive - timedelta(minutes=10)

    result = solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, arrive, buffer_min=10)

    free_flow = timedelta(seconds=provider.base_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, TravelMode.CAR))
    at_target = timedelta(seconds=provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, target))
    assert result.depart_at < target - free_flow  # 혼잡 없는 소요시간으로 뺀 값보다 이르다
    assert result.depart_at < target - at_target  # 목표 시각 기준 소요시간으로 한 번 뺀 값보다도 이르다
    assert result.arrive_at <= target
    assert result.depart_at == brute_force_latest(provider, GIMHAE_CITY_HALL, DONGEUI_UNIV, target, kst(5, 3))


def test_rush_hour_takes_longer_than_late_night(clock):
    solver = DepartureSolver(MockRouteProvider(), clock=clock)

    rush = solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 9))
    night = solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 3))

    assert rush.duration_sec > night.duration_sec


# 여유시간

@pytest.mark.parametrize("buffer_min", [0, 5, 10, 15])
def test_buffer_moves_arrival_earlier(clock, buffer_min):
    provider = MockRouteProvider()
    solver = DepartureSolver(provider, clock=clock)
    arrive = kst(5, 9)
    target = arrive - timedelta(minutes=buffer_min)

    result = solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, arrive, buffer_min)

    assert result.arrive_at <= target
    assert result.depart_at == brute_force_latest(provider, GIMHAE_CITY_HALL, DONGEUI_UNIV, target, kst(5, 3))
    assert result.buffer_min == buffer_min
    assert result.buffer_applied is (buffer_min > 0)


def test_larger_buffer_never_departs_later(clock):
    solver = DepartureSolver(MockRouteProvider(), clock=clock)

    departs = [solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 9), b).depart_at for b in (0, 5, 10, 15)]

    assert departs == sorted(departs, reverse=True)


def test_buffer_is_dropped_when_there_is_no_time_for_it():
    # 08:00에 09:00 도착, 소요 55분: 지금 출발하면 08:55 도착이라 10분 여유는 둘 수 없다.
    solver = DepartureSolver(ConstantProvider(55 * 60), clock=lambda: kst(5, 8))

    result = solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 9), buffer_min=10)

    assert result.buffer_applied is False
    assert result.buffer_min == 10
    assert result.depart_at == kst(5, 8, 5)
    assert result.arrive_at == kst(5, 9)


# 예외 처리

@pytest.mark.parametrize("arrive", [NOW, NOW - MINUTE, kst(3, 9)])
def test_arrival_time_already_passed(clock, arrive):
    solver = DepartureSolver(MockRouteProvider(), clock=clock)

    with pytest.raises(ArrivalTimePassedError, match="이미 지났습니다"):
        solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, arrive)


def test_cannot_arrive_even_if_leaving_now():
    spy = SpyProvider(ConstantProvider(60 * 60))
    solver = DepartureSolver(spy, clock=lambda: kst(5, 8, 30))

    with pytest.raises(NoFeasibleDepartureError, match="지금 출발해도"):
        solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 9), buffer_min=10)
    assert spy.calls <= SolverConfig().max_calls


def test_trip_longer_than_search_window(clock):
    # 서울역 -> 동의대: Mock 기준 7시간이 넘어 기본 탐색 구간(6시간) 안에서는 도착할 수 없다.
    solver = DepartureSolver(MockRouteProvider(), clock=clock)

    with pytest.raises(NoFeasibleDepartureError, match="6시간 전에 출발해도"):
        solver.solve(SEOUL_STATION, DONGEUI_UNIV, kst(5, 18))


def test_longer_search_window_finds_long_trip(clock):
    provider = MockRouteProvider()
    solver = DepartureSolver(provider, SolverConfig(search_window=timedelta(hours=12)), clock=clock)

    result = solver.solve(SEOUL_STATION, DONGEUI_UNIV, kst(5, 18))

    assert result.arrive_at <= kst(5, 18)
    assert result.duration_sec > 6 * 3600


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"buffer_min": -5}, "여유시간"),
        ({"buffer_min": 2.5}, "여유시간"),
        ({"travel_mode": "bike"}, "bike"),
        ({"arrive_by": kst(5, 9).replace(tzinfo=None)}, "시간대"),
    ],
)
def test_invalid_input(clock, kwargs, message):
    solver = DepartureSolver(MockRouteProvider(), clock=clock)
    params = {"origin": GIMHAE_CITY_HALL, "dest": DONGEUI_UNIV, "arrive_by": kst(5, 9)} | kwargs

    with pytest.raises(ValueError, match=message):
        solver.solve(**params)


@pytest.mark.parametrize(
    "config",
    [
        {"max_calls": 1},
        {"tolerance": timedelta(seconds=30)},
        {"tolerance": timedelta(seconds=90)},
        {"search_window": timedelta(minutes=1)},
    ],
)
def test_invalid_config(config):
    with pytest.raises(ValueError):
        SolverConfig(**config)


# 호출 횟수

ROUTES = [(GIMHAE_CITY_HALL, DONGEUI_UNIV), (GIMHAE_CITY_HALL, HAEUNDAE), (SEOUL_STATION, DONGEUI_UNIV)]


def scenarios():
    """하루 전체(23분 간격) x 여유시간 x 이동수단 x 경로"""
    for minutes in range(0, 24 * 60, 23):
        arrive = kst(5, 0) + timedelta(minutes=minutes)
        for buffer_min in (0, 5, 10, 15):
            for mode in TravelMode:
                for origin, dest in ROUTES:
                    yield origin, dest, arrive, buffer_min, mode


@pytest.mark.parametrize("max_calls", [2, 3, 5, 8])
def test_calls_never_exceed_max(clock, max_calls):
    for origin, dest, arrive, buffer_min, mode in scenarios():
        spy = SpyProvider(MockRouteProvider())
        solver = DepartureSolver(spy, SolverConfig(max_calls=max_calls), clock=clock)
        try:
            result = solver.solve(origin, dest, arrive, buffer_min, mode)
        except (NoFeasibleDepartureError, SearchBudgetExceededError):
            pass
        else:
            assert result.provider_calls == spy.calls
            # 수렴하지 못해도 돌려준 출발시각은 실제로 제시간에 도착한다.
            assert result.arrive_at <= arrive - timedelta(minutes=buffer_min if result.buffer_applied else 0)
        assert spy.calls <= max_calls


def test_default_config_finds_exact_latest_departure(clock):
    """기본 설정(최대 8회)으로 모든 시나리오에서 분 단위 정답과 일치한다."""
    provider = MockRouteProvider()
    solver = DepartureSolver(provider, clock=clock)
    checked = 0
    for origin, dest, arrive, buffer_min, mode in scenarios():
        try:
            result = solver.solve(origin, dest, arrive, buffer_min, mode)
        except NoFeasibleDepartureError:
            assert (origin, dest) == (SEOUL_STATION, DONGEUI_UNIV)
            continue
        target = arrive - timedelta(minutes=buffer_min)
        earliest = max(NOW, arrive - timedelta(hours=6))
        assert result.converged
        assert result.depart_at == brute_force_latest(provider, origin, dest, target, earliest, mode)
        checked += 1
    assert checked > 1000


def test_repeated_departure_is_not_queried_twice(clock):
    seen = []

    class RecordingProvider(RouteProvider):
        def get_duration(self, origin, dest, depart_at, travel_mode=TravelMode.CAR):
            seen.append(depart_at)
            return MockRouteProvider().get_duration(origin, dest, depart_at, travel_mode)

    # 여유시간을 둘 수 없어 다시 찾는 경우에도 같은 출발시각은 한 번만 조회한다.
    DepartureSolver(RecordingProvider(), clock=lambda: kst(5, 8)).solve(
        GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 9, 5), buffer_min=15
    )
    assert len(seen) == len(set(seen))
