from datetime import datetime, timedelta

import pytest

from app.departure import KST, Coordinate, RouteProvider, TravelMode
from tests.auth_backends import make_backend, mysql_live

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


ENGINE_ENV_VARS = (
    "ROUTE_PROVIDER",
    "KAKAO_REST_API_KEY",
    "DEPARTURE_MAX_CALLS",
    "DEPARTURE_SEARCH_WINDOW_MIN",
    "CORS_ORIGINS",
    "ROUTE_COMPARE_OPTIONS",
    "ROUTE_COMPARE_MAX_CALLS",
    "GRAPH_SLOTS_BEFORE",
    "GRAPH_SLOTS_AFTER",
    "GRAPH_SLOT_INTERVAL_MIN",
    "GRAPH_TIME_BUDGET_SEC",
    "GRAPH_MAX_WORKERS",
    "GRAPH_DAILY_CALL_BUDGET",
    "AUTH_STORE",
    "COOKIE_SECURE",
    "SECRET_KEY",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_SSL_CA",
    "TEST_DB_NAME",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "OAUTH_REDIRECT_BASE",
    "OAUTH_MOCK",
    "KAKAO_LOGIN_CLIENT_ID",
    "KAKAO_LOGIN_CLIENT_SECRET",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "AI_SUMMARY_TIMEOUT_SEC",
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """개발자의 환경변수와 .env가 테스트에 섞이지 않게 한다. 기본 테스트가 실제 카카오 API를 부르는 일을 막는다."""
    for name in ENGINE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("app.departure.cli.load_env_files", lambda: None)
    monkeypatch.setattr("app.api.factory.load_env_files", lambda: None)


@pytest.fixture(params=["memory", pytest.param("mysql", marks=mysql_live)])
def store_backend(request):
    """회원 저장소 계약 테스트를 메모리와 MySQL(mysql_live, 기본 실행에서 제외)에서 돌린다 (tests/auth_backends.py)."""
    backend = make_backend(request.param)
    yield backend
    backend.close()


@pytest.fixture(params=["memory", pytest.param("mysql", marks=mysql_live)])
def favorites_backend(request):
    """즐겨찾기 계약 테스트용 저장소 (회원·세션·즐겨찾기). MySQL은 마이그레이션 003이 적용된 테스트 DB가 필요하다."""
    backend = make_backend(request.param, favorites=True)
    yield backend
    backend.close()


@pytest.fixture(params=["memory", pytest.param("mysql", marks=mysql_live)])
def history_backend(request):
    """검색 기록 계약 테스트용 저장소 (회원·세션·검색 기록). 스키마 변경은 필요 없다."""
    backend = make_backend(request.param)
    yield backend
    backend.close()


@pytest.fixture
def clock():
    return lambda: NOW
