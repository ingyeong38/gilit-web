from datetime import datetime, timedelta

import pytest

from app.departure import KST, Coordinate, RouteProvider, TravelMode

GIMHAE_CITY_HALL = Coordinate(35.2285, 128.8894)
DONGEUI_UNIV = Coordinate(35.1441, 129.0336)
HAEUNDAE = Coordinate(35.1631, 129.1635)
SEOUL_STATION = Coordinate(37.5547, 126.9707)

# 테스트 기준 현재 시각: 2026-11-04 (수) 06:00. 도착 희망 시각은 대부분 다음 날(목) 출근 시간대다.
NOW = datetime(2026, 11, 4, 6, 0, tzinfo=KST)


def kst(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=KST)


class ConstantProvider(RouteProvider):
    """시간대와 무관하게 같은 소요시간을 돌려준다."""

    def __init__(self, seconds: int) -> None:
        self.seconds = seconds

    def get_duration(self, origin, dest, depart_at, travel_mode=TravelMode.CAR) -> int:
        return self.seconds


class SpyProvider(RouteProvider):
    """다른 Provider를 감싸 실제 호출 횟수를 센다."""

    def __init__(self, inner: RouteProvider) -> None:
        self.inner = inner
        self.calls = 0

    def get_duration(self, origin, dest, depart_at, travel_mode=TravelMode.CAR) -> int:
        self.calls += 1
        return self.inner.get_duration(origin, dest, depart_at, travel_mode)


def brute_force_latest(provider, origin, dest, target, earliest, travel_mode=TravelMode.CAR):
    """earliest부터 1분 간격으로 모두 조회해, target까지 도착하는 가장 늦은 출발시각을 찾는다 (정답 확인용)."""
    latest = None
    depart = earliest
    while depart <= target:
        if depart + timedelta(seconds=provider.get_duration(origin, dest, depart, travel_mode)) <= target:
            latest = depart
        depart += timedelta(minutes=1)
    return latest


ENGINE_ENV_VARS = ("ROUTE_PROVIDER", "KAKAO_REST_API_KEY", "DEPARTURE_MAX_CALLS", "DEPARTURE_SEARCH_WINDOW_MIN")


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """개발자의 환경변수와 .env가 테스트에 섞이지 않게 한다. 기본 테스트가 실제 카카오 API를 부르는 일을 막는다."""
    for name in ENGINE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("app.departure.cli.load_env_files", lambda: None)


@pytest.fixture
def clock():
    return lambda: NOW
