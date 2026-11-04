"""실제 카카오모빌리티 API 호출 테스트. 기본 실행에서 빠진다.

    venv/Scripts/python -m pytest -m kakao_live

KAKAO_REST_API_KEY(환경변수, backend/.env, 루트 .env 순)가 없으면 건너뛴다. 한 번 실행에 API를 약 10회 부른다.
"""

import os
from datetime import datetime, timedelta

import pytest
from dotenv import dotenv_values

from app.config import ENV_FILES
from app.departure import KST, DepartureSolver, KakaoRouteProvider, RouteNotFoundError
from tests.conftest import DONGEUI_UNIV, GIMHAE_CITY_HALL


def _find_key() -> str | None:
    # isolated_env fixture가 환경변수를 지우기 전, import 시점에 읽는다. os.environ은 바꾸지 않는다.
    key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    for path in ENV_FILES:
        if not key and path.is_file():
            key = (dotenv_values(path).get("KAKAO_REST_API_KEY") or "").strip()
    return key or None


API_KEY = _find_key()
pytestmark = [
    pytest.mark.kakao_live,
    pytest.mark.skipif(API_KEY is None, reason="KAKAO_REST_API_KEY가 없어 실제 API 테스트를 건너뜁니다."),
]


def tomorrow_at(hour: int, minute: int = 0) -> datetime:
    return (datetime.now(KST) + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)


@pytest.fixture(scope="module")
def provider():
    return KakaoRouteProvider(API_KEY)


def test_live_duration_is_plausible(provider):
    seconds = provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, tomorrow_at(8, 10))

    # 김해시청 -> 동의대학교는 약 22km. 10분~2시간 안이면 정상 응답으로 본다.
    assert 10 * 60 < seconds < 2 * 60 * 60


def test_live_same_point_is_route_not_found(provider):
    with pytest.raises(RouteNotFoundError) as caught:
        provider.get_duration(GIMHAE_CITY_HALL, GIMHAE_CITY_HALL, tomorrow_at(8, 10))
    assert caught.value.result_code == 104


def test_live_solver_finds_departure_within_budget(provider):
    arrive = tomorrow_at(9)
    result = DepartureSolver(provider).solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, arrive, 10)

    assert result.provider_calls <= 8
    assert result.buffer_applied
    assert result.arrive_at <= arrive - timedelta(minutes=10)
    assert result.depart_at < arrive
