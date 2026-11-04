from datetime import timedelta

import pytest

from app.config import Settings, create_route_provider, load_env_files
from app.departure import Coordinate, KakaoRouteProvider, MockRouteProvider, RouteProvider, TravelMode
from app.departure import ProviderQuotaExceededError
from app.departure.cli import main
from tests.conftest import DONGEUI_UNIV, GIMHAE_CITY_HALL, SEOUL_STATION, kst


def test_route_provider_is_abstract():
    with pytest.raises(TypeError):
        RouteProvider()


def test_mock_rush_hour_is_slower_than_night():
    provider = MockRouteProvider()

    rush = provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8))
    night = provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 3))

    assert rush > night * 1.3


def test_mock_transit_is_slower_than_car():
    provider = MockRouteProvider()

    car = provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 3), TravelMode.CAR)
    transit = provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 3), TravelMode.TRANSIT)

    assert transit > car


@pytest.mark.parametrize("origin", [GIMHAE_CITY_HALL, SEOUL_STATION])
@pytest.mark.parametrize("mode", list(TravelMode))
def test_mock_is_fifo(origin, mode):
    """먼저 출발하면 늦게 도착하지 않는다. DepartureSolver의 이분탐색이 기대는 성질이다."""
    provider = MockRouteProvider()
    previous = None
    for minute in range(0, 24 * 60):
        depart = kst(5, 0) + timedelta(minutes=minute)
        arrival = depart + timedelta(seconds=provider.get_duration(origin, DONGEUI_UNIV, depart, mode))
        assert previous is None or arrival >= previous
        previous = arrival


def test_coordinate_validation():
    assert Coordinate.parse("35.2285, 128.8894") == Coordinate(35.2285, 128.8894)
    with pytest.raises(ValueError):
        Coordinate.parse("35.2285")
    with pytest.raises(ValueError):
        Coordinate(91, 0)


def test_settings_defaults_without_env():
    settings = Settings.from_env({})

    assert settings == Settings()
    assert settings.solver_config().max_calls == 8
    assert isinstance(create_route_provider(settings), MockRouteProvider)


def test_settings_from_env():
    settings = Settings.from_env({"DEPARTURE_MAX_CALLS": "10", "DEPARTURE_SEARCH_WINDOW_MIN": "120"})

    assert settings.solver_config().max_calls == 10
    assert settings.solver_config().search_window == timedelta(hours=2)


@pytest.mark.parametrize(
    ("env", "error"),
    [
        ({"ROUTE_PROVIDER": "naver"}, ValueError),
        ({"DEPARTURE_MAX_CALLS": "many"}, ValueError),
    ],
)
def test_settings_rejects_bad_env(env, error):
    with pytest.raises(error):
        Settings.from_env(env)


def test_kakao_provider_requires_key():
    with pytest.raises(ValueError, match="KAKAO_REST_API_KEY"):
        create_route_provider(Settings.from_env({"ROUTE_PROVIDER": "kakao"}))
    with pytest.raises(ValueError, match="KAKAO_REST_API_KEY"):
        create_route_provider(Settings.from_env({"ROUTE_PROVIDER": "kakao", "KAKAO_REST_API_KEY": "  "}))


def test_kakao_provider_is_selected_and_key_is_hidden():
    settings = Settings.from_env({"ROUTE_PROVIDER": " Kakao ", "KAKAO_REST_API_KEY": "secret-key-123"})
    provider = create_route_provider(settings)

    assert isinstance(provider, KakaoRouteProvider)
    assert "secret-key-123" not in repr(settings)
    assert "secret-key-123" not in repr(provider)


def test_load_env_files_prefers_env_then_backend_then_root(tmp_path, monkeypatch):
    backend_env = tmp_path / "backend.env"
    root_env = tmp_path / "root.env"
    backend_env.write_text("ROUTE_PROVIDER=kakao\nDEPARTURE_MAX_CALLS=5\n", encoding="utf-8")
    root_env.write_text("ROUTE_PROVIDER=mock\nDEPARTURE_MAX_CALLS=6\nKAKAO_REST_API_KEY=from-root\n", encoding="utf-8")
    monkeypatch.setenv("DEPARTURE_MAX_CALLS", "9")

    load_env_files((backend_env, root_env, tmp_path / "missing.env"))
    settings = Settings.from_env()

    assert settings.route_provider == "kakao"
    assert settings.departure_max_calls == 9
    assert settings.kakao_rest_api_key == "from-root"


def test_cli_prints_recommended_departure(capsys):
    exit_code = main(["--from", "35.2285,128.8894", "--to", "35.1441,129.0336", "--arrive", "2099-11-05 09:00", "--buffer", "10"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "권장 출발시각: 2099-11-05 (목)" in out
    assert "여유시간: 10분 반영" in out


def test_cli_reports_past_arrival_without_traceback(capsys):
    exit_code = main(["--from", "35.2285,128.8894", "--to", "35.1441,129.0336", "--arrive", "2000-01-01 09:00"])

    assert exit_code == 1
    assert "도착 희망 시각이 이미 지났습니다." in capsys.readouterr().err


def test_cli_reports_provider_error_without_traceback(capsys, monkeypatch):
    class FailingProvider(RouteProvider):
        def get_duration(self, origin, dest, depart_at, travel_mode=TravelMode.CAR):
            raise ProviderQuotaExceededError("길찾기 API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.")

    monkeypatch.setattr("app.departure.cli.create_route_provider", lambda settings: FailingProvider())
    exit_code = main(["--from", "35.2285,128.8894", "--to", "35.1441,129.0336", "--arrive", "2099-11-05 09:00"])

    assert exit_code == 1
    assert "호출 한도를 초과했습니다" in capsys.readouterr().err
