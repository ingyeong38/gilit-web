"""웹 API 테스트. FastAPI TestClient와 가짜 Provider를 써서 실제 API는 부르지 않는다."""

import logging
from unittest.mock import Mock

import pytest
import requests
from fastapi.testclient import TestClient

from app.api.errors import INTERNAL_ERROR_MESSAGE, PROVIDER_ERROR_MESSAGE
from app.api.factory import create_app
from app.config import Settings
from app.departure import (
    DepartureSolver,
    KakaoRouteProvider,
    MockRouteProvider,
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RouteNotFoundError,
    RouteProvider,
    RouteProviderError,
    TravelMode,
    UnsupportedTravelModeError,
)
from tests.conftest import DONGEUI_UNIV, GIMHAE_CITY_HALL, NOW, ConstantProvider, SpyProvider, kst

LOCAL_ORIGIN = "http://localhost:5500"


def body(**overrides):
    """김해시청 -> 동의대학교, 다음 날(11/5) 09:00 도착, 여유 10분."""
    payload = {
        "origin": {"name": "김해시청", "lat": GIMHAE_CITY_HALL.lat, "lng": GIMHAE_CITY_HALL.lng},
        "destination": {"name": "동의대학교", "lat": DONGEUI_UNIV.lat, "lng": DONGEUI_UNIV.lng},
        "arrive_at": "2026-11-05T09:00:00+09:00",
        "buffer_min": 10,
        "travel_mode": "car",
    }
    payload.update(overrides)
    return payload


def make_client(provider: RouteProvider | None = None, settings: Settings | None = None, **kwargs) -> TestClient:
    app = create_app(settings or Settings(), provider or MockRouteProvider(), clock=lambda: NOW)
    return TestClient(app, **kwargs)


class RaisingProvider(RouteProvider):
    def __init__(self, error: Exception) -> None:
        self.error = error

    def get_duration(self, origin, dest, depart_at, travel_mode=TravelMode.CAR) -> int:
        raise self.error


# --- 정상 ---


def test_health():
    response = make_client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_departure_returns_solver_result():
    response = make_client().post("/api/departure", json=body())

    assert response.status_code == 200
    expected = DepartureSolver(MockRouteProvider(), clock=lambda: NOW).solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 9), 10)
    assert response.json() == {
        "recommended_depart_at": expected.depart_at.isoformat(),
        "duration_min": expected.duration_min,
        "expected_arrive_at": expected.arrive_at.isoformat(),
        "desired_arrive_at": "2026-11-05T09:00:00+09:00",
        "buffer_min": 10,
        "buffer_applied": True,
        "converged": expected.converged,
        "api_calls": expected.provider_calls,
        "data_source": "mock",
    }
    assert response.json()["recommended_depart_at"].endswith("+09:00")


def test_buffer_defaults_to_zero_and_mode_to_car():
    payload = body()
    del payload["buffer_min"], payload["travel_mode"]

    data = make_client().post("/api/departure", json=payload).json()

    assert data["buffer_min"] == 0
    assert data["buffer_applied"] is False


@pytest.mark.parametrize(
    "arrive_at",
    ["2026-11-05T09:00:00", "2026-11-05 09:00", "2026-11-05T00:00:00Z"],
    ids=["naive-is-kst", "space-separated", "utc"],
)
def test_arrive_at_is_read_as_kst(arrive_at):
    data = make_client().post("/api/departure", json=body(arrive_at=arrive_at)).json()

    assert data["desired_arrive_at"] == "2026-11-05T09:00:00+09:00"


def test_buffer_not_applied_when_even_leaving_now_is_too_tight():
    # 지금(06:00) 출발해 50분 걸리면 06:50 도착. 07:00 도착 희망에 여유 15분은 둘 수 없다.
    data = make_client(ConstantProvider(50 * 60)).post(
        "/api/departure", json=body(arrive_at="2026-11-04T07:00:00+09:00", buffer_min=15)
    ).json()

    assert data["buffer_applied"] is False
    assert data["recommended_depart_at"] == "2026-11-04T06:10:00+09:00"


# --- 입력 오류: 400 + 필드별 한국어 문장 ---


def with_place(key, **place):
    return body(**{key: {**body()[key], **place}})


def without(key, field=None):
    payload = body()
    if field is None:
        del payload[key]
    else:
        del payload[key][field]
    return payload


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (with_place("origin", lat=91), "출발지 위도는 -90~90 사이의 숫자여야 합니다."),
        (with_place("origin", lat="abc"), "출발지 위도는 -90~90 사이의 숫자여야 합니다."),
        (with_place("destination", lng=-180.5), "목적지 경도는 -180~180 사이의 숫자여야 합니다."),
        (with_place("origin", name=""), "출발지 장소 이름은 1~100자로 입력해 주세요."),
        (with_place("origin", name="   "), "출발지 장소 이름은 1~100자로 입력해 주세요."),
        (with_place("destination", name="가" * 101), "목적지 장소 이름은 1~100자로 입력해 주세요."),
        (without("destination"), "목적지가 필요합니다."),
        (without("origin", "lat"), "출발지 위도가 필요합니다."),
        (without("arrive_at"), "도착 희망 시각이 필요합니다."),
        (body(origin="김해시청"), "출발지는 name, lat, lng가 있는 객체여야 합니다."),
        (body(arrive_at="내일 9시"), "도착 희망 시각은 ISO 8601 형식이어야 합니다 (예: 2026-11-06T09:00:00+09:00)."),
        (body(arrive_at=1793840400), "도착 희망 시각은 ISO 8601 형식이어야 합니다 (예: 2026-11-06T09:00:00+09:00)."),
        (body(buffer_min=7), "여유시간은 0, 5, 10, 15분 중 하나여야 합니다."),
        (body(buffer_min="10"), "여유시간은 0, 5, 10, 15분 중 하나여야 합니다."),
        (body(buffer_min=True), "여유시간은 0, 5, 10, 15분 중 하나여야 합니다."),
        (body(buffer_min=-5), "여유시간은 0, 5, 10, 15분 중 하나여야 합니다."),
        (body(travel_mode="bike"), "이동수단은 car 또는 transit이어야 합니다."),
        ([], "요청 본문은 JSON 객체여야 합니다."),
    ],
)
def test_invalid_input_returns_400(payload, message):
    spy = SpyProvider(MockRouteProvider())

    response = make_client(spy).post("/api/departure", json=payload)

    assert response.status_code == 400
    assert response.json() == {"message": message}
    assert spy.calls == 0


def test_malformed_json_returns_400():
    response = make_client().post(
        "/api/departure", content=b"{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json() == {"message": "요청 본문은 JSON 객체여야 합니다."}


def test_past_arrival_returns_400_without_calling_provider():
    spy = SpyProvider(MockRouteProvider())

    response = make_client(spy).post("/api/departure", json=body(arrive_at="2026-11-04T05:59:00+09:00"))

    assert response.status_code == 400
    assert response.json() == {"message": "도착 희망 시각이 이미 지났습니다."}
    assert spy.calls == 0


# --- DepartureError: 4xx + 엔진 메시지 ---


@pytest.mark.parametrize(
    ("provider", "status", "message"),
    [
        (ConstantProvider(10 * 3600), 422, "도착 희망 시각 6시간 전에 출발해도 제시간에 도착할 수 없습니다."),
        (
            RaisingProvider(RouteNotFoundError("경로를 찾을 수 없습니다: 출발지와 도착지가 너무 가깝습니다 (result_code=104)", 104)),
            422,
            "경로를 찾을 수 없습니다: 출발지와 도착지가 너무 가깝습니다 (result_code=104)",
        ),
        (RaisingProvider(UnsupportedTravelModeError("대중교통은 아직 지원하지 않습니다.")), 400, "대중교통은 아직 지원하지 않습니다."),
    ],
    ids=["no-feasible", "route-not-found", "unsupported-mode"],
)
def test_departure_errors_return_4xx(provider, status, message):
    response = make_client(provider).post("/api/departure", json=body())

    assert response.status_code == status
    assert response.json() == {"message": message}


# --- RouteProviderError: 5xx, 내부 정보는 응답에 넣지 않는다 ---


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (ProviderAuthError("카카오 API 인증에 실패했습니다 (HTTP 401). KAKAO_REST_API_KEY와 카카오모빌리티 API 사용 설정을 확인하세요."), 502, PROVIDER_ERROR_MESSAGE),
        (ProviderBadRequestError("길찾기 요청이 거부되었습니다 (HTTP 400): 출발지가 유효하지 않습니다."), 502, PROVIDER_ERROR_MESSAGE),
        (ProviderUnavailableError("길찾기 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요. (ConnectionError)"), 502, PROVIDER_ERROR_MESSAGE),
        (RouteProviderError("길찾기 응답 형식이 올바르지 않습니다."), 502, PROVIDER_ERROR_MESSAGE),
        (ProviderTimeoutError("길찾기 서버 응답이 늦습니다. 잠시 후 다시 시도해 주세요."), 504, "길찾기 서버 응답이 늦습니다. 잠시 후 다시 시도해 주세요."),
        (ProviderQuotaExceededError("길찾기 API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."), 503, "길찾기 API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."),
    ],
    ids=["auth", "bad-request", "unavailable", "malformed", "timeout", "quota"],
)
def test_provider_errors_return_5xx(error, status, message, caplog):
    with caplog.at_level(logging.WARNING, logger="app.api"):
        response = make_client(RaisingProvider(error)).post("/api/departure", json=body())

    assert response.status_code == status
    assert response.json() == {"message": message}
    for internal in ("KAKAO_REST_API_KEY", "HTTP", "ConnectionError"):
        assert internal not in response.text
    assert str(error) in caplog.text  # 원인은 서버 로그에서 확인한다


def test_kakao_auth_error_does_not_leak_api_key():
    api_key = "live-looking-key-0123456789abcdef"
    unauthorized = Mock(spec=requests.Response)
    unauthorized.status_code = 401
    unauthorized.json.return_value = {"msg": f"invalid key: {api_key}"}  # 카카오는 본문에 키를 돌려준다
    session = Mock(spec=requests.Session)
    session.get.return_value = unauthorized
    settings = Settings(route_provider="kakao", kakao_rest_api_key=api_key)

    response = make_client(KakaoRouteProvider(api_key, session=session), settings).post("/api/departure", json=body())

    assert response.status_code == 502
    assert api_key not in response.text


def test_kakao_provider_result_is_labeled():
    session = Mock(spec=requests.Session)
    ok = Mock(spec=requests.Response)
    ok.status_code = 200
    ok.json.return_value = {"routes": [{"result_code": 0, "summary": {"duration": 1800, "distance": 21970}}]}
    session.get.return_value = ok
    settings = Settings(route_provider="kakao", kakao_rest_api_key="k")

    data = make_client(KakaoRouteProvider("k", session=session), settings).post("/api/departure", json=body()).json()

    assert data["data_source"] == "kakao"
    assert data["recommended_depart_at"] == "2026-11-05T08:20:00+09:00"


def test_unexpected_error_returns_500_without_details():
    client = make_client(RaisingProvider(RuntimeError("db password=hunter2")), raise_server_exceptions=False)

    response = client.post("/api/departure", json=body())

    assert response.status_code == 500
    assert response.json() == {"message": INTERNAL_ERROR_MESSAGE}


@pytest.mark.parametrize(
    ("method", "path", "status", "message"),
    [("get", "/api/nothing", 404, "찾을 수 없습니다."), ("get", "/api/departure", 405, "허용되지 않은 요청 방식입니다.")],
)
def test_http_errors_use_message_format(method, path, status, message):
    response = getattr(make_client(), method)(path)

    assert response.status_code == status
    assert response.json() == {"message": message}


# --- CORS ---


def test_cors_preflight_allows_local_frontend():
    response = make_client().options(
        "/api/departure",
        headers={"Origin": LOCAL_ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == LOCAL_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_headers_on_actual_request():
    response = make_client().post("/api/departure", json=body(), headers={"Origin": "http://127.0.0.1:5500"})

    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5500"


def test_cors_rejects_other_origins():
    client = make_client(settings=Settings(cors_origins=("https://gilit.example.com",)))

    preflight = client.options(
        "/api/departure", headers={"Origin": LOCAL_ORIGIN, "Access-Control-Request-Method": "POST"}
    )
    actual = client.post("/api/departure", json=body(), headers={"Origin": LOCAL_ORIGIN})

    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in actual.headers
    allowed = client.post("/api/departure", json=body(), headers={"Origin": "https://gilit.example.com"})
    assert allowed.headers["access-control-allow-origin"] == "https://gilit.example.com"


# --- 앱 구성 ---


def test_provider_is_created_once_per_app(monkeypatch):
    created = []

    def fake_create(settings):
        created.append(SpyProvider(MockRouteProvider()))
        return created[-1]

    monkeypatch.setattr("app.api.factory.create_route_provider", fake_create)
    app = create_app(Settings(), clock=lambda: NOW)
    client = TestClient(app)

    client.post("/api/departure", json=body())
    client.post("/api/departure", json=body(buffer_min=5))

    assert len(created) == 1
    assert app.state.provider is created[0]
    assert created[0].calls > 0


def test_create_app_reads_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://gilit.example.com, http://localhost:3000/")
    monkeypatch.setenv("ROUTE_CACHE_TTL_SEC", "60")

    settings = create_app().state.settings

    assert settings.cors_origins == ("https://gilit.example.com", "http://localhost:3000")
    assert settings.route_cache_ttl_sec == 60
    assert settings.route_provider == "mock"


def test_swagger_docs_list_departure_endpoint():
    client = make_client()

    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    assert "/api/departure" in spec["paths"]
    assert "/health" in spec["paths"]
