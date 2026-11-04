"""KakaoRouteProvider 단위 테스트. requests 세션을 가짜로 바꿔 실제 API는 부르지 않는다."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import requests

from app.departure import (
    DepartureError,
    DepartureSolver,
    KakaoRouteProvider,
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RouteNotFoundError,
    RouteProviderError,
    TravelMode,
    UnsupportedTravelModeError,
)
from app.departure.providers_kakao import KAKAO_FUTURE_DIRECTIONS_URL
from tests.conftest import DONGEUI_UNIV, GIMHAE_CITY_HALL, kst

API_KEY = "test-kakao-key-0123456789abcdef"


def response(status=200, body=None, json_error=False):
    fake = Mock(spec=requests.Response)
    fake.status_code = status
    if json_error:
        fake.json.side_effect = ValueError("not json")
    else:
        fake.json.return_value = body
    return fake


def ok(duration=1855, distance=21970):
    return response(body={"routes": [{"result_code": 0, "result_msg": "길찾기 성공",
                                      "summary": {"duration": duration, "distance": distance}}]})


def make_provider(*responses, **kwargs):
    session = Mock(spec=requests.Session)
    session.get.side_effect = list(responses)
    return KakaoRouteProvider(API_KEY, session=session, **kwargs), session


def sent(session, index=0):
    """index번째 요청의 (url, params, headers, timeout)."""
    call = session.get.call_args_list[index]
    return call.args[0], call.kwargs["params"], call.kwargs["headers"], call.kwargs["timeout"]


def assert_key_hidden(error: BaseException):
    """오류 메시지와 예외 체인(__cause__, __context__) 어디에도 키가 없다."""
    current = error
    while current is not None:
        assert API_KEY not in str(current)
        assert API_KEY not in repr(current.args)
        current = current.__cause__ or current.__context__


def test_returns_summary_duration_in_seconds():
    provider, session = make_provider(ok(duration=1855))

    assert provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10)) == 1855
    url, params, headers, timeout = sent(session)
    assert url == KAKAO_FUTURE_DIRECTIONS_URL
    assert headers == {"Authorization": f"KakaoAK {API_KEY}"}
    assert timeout == 10.0
    assert provider.request_count == 1


def test_converts_lat_lng_to_kakao_lng_lat_order():
    provider, session = make_provider(ok())

    provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10))

    _, params, _, _ = sent(session)
    assert params["origin"] == "128.8894,35.2285"  # 경도,위도
    assert params["destination"] == "129.0336,35.1441"


def test_departure_time_is_kst_and_floored_to_minute():
    provider, session = make_provider(ok())
    # UTC 23:10:59 = KST 다음 날 08:10:59 -> 202611050810
    provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, datetime(2026, 11, 4, 23, 10, 59, tzinfo=timezone.utc))

    _, params, _, _ = sent(session)
    assert params["departure_time"] == "202611050810"


def test_rejects_naive_departure_time():
    provider, session = make_provider()

    with pytest.raises(ValueError, match="시간대"):
        provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, datetime(2026, 11, 5, 8, 10))
    session.get.assert_not_called()


@pytest.mark.parametrize("mode", [TravelMode.TRANSIT, "transit"])
def test_rejects_transit_without_calling_api(mode):
    provider, session = make_provider()

    with pytest.raises(UnsupportedTravelModeError, match="대중교통은 아직 지원하지 않습니다"):
        provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10), mode)
    session.get.assert_not_called()


def test_transit_error_is_user_facing_departure_error(clock):
    provider, _ = make_provider()
    solver = DepartureSolver(provider, clock=clock)

    with pytest.raises(DepartureError, match="대중교통"):
        solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 9), 10, TravelMode.TRANSIT)


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (104, "출발지와 도착지가 5 m 이내로 설정된 경우 경로를 탐색할 수 없음"),
        (103, "도착 지점 주변의 도로를 탐색할 수 없음"),
    ],
)
def test_result_code_error_raises_route_not_found(code, message):
    provider, _ = make_provider(response(body={"routes": [{"result_code": code, "result_msg": message}]}))

    with pytest.raises(RouteNotFoundError) as caught:
        provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10))
    assert caught.value.result_code == code
    assert str(caught.value) == f"경로를 찾을 수 없습니다: {message} (result_code={code})"
    assert isinstance(caught.value, DepartureError)  # 입력 문제이므로 4xx로 다룬다


@pytest.mark.parametrize("status", [401, 403])
def test_auth_error_never_exposes_key(status):
    # 실제 카카오 401 응답은 본문에 키를 그대로 담는다.
    body = {"code": -401, "msg": f"appKey({API_KEY}) does not exist"}
    provider, _ = make_provider(response(status=status, body=body))

    with pytest.raises(ProviderAuthError) as caught:
        provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10))
    assert f"HTTP {status}" in str(caught.value)
    assert "KAKAO_REST_API_KEY" in str(caught.value)  # 변수 이름 안내는 하되 값은 넣지 않는다
    assert_key_hidden(caught.value)


def test_quota_exceeded_on_429():
    provider, _ = make_provider(response(status=429, body={"code": -10, "msg": "API limit has been exceeded."}))

    with pytest.raises(ProviderQuotaExceededError, match="호출 한도를 초과"):
        provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10))


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_error_on_5xx(status):
    provider, _ = make_provider(response(status=status, json_error=True))

    with pytest.raises(ProviderUnavailableError, match=f"HTTP {status}"):
        provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10))


def test_bad_request_includes_kakao_message_but_redacts_key():
    body = {"code": -2, "msg": f"출발지가 유효하지 않습니다. key={API_KEY}"}
    provider, _ = make_provider(response(status=400, body=body))

    with pytest.raises(ProviderBadRequestError) as caught:
        provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10))
    assert "출발지가 유효하지 않습니다" in str(caught.value)
    assert_key_hidden(caught.value)


def test_timeout_is_10_seconds_and_raises_timeout_error():
    provider, session = make_provider(requests.Timeout(f"read timed out headers={API_KEY}"))

    with pytest.raises(ProviderTimeoutError, match="응답이 늦습니다") as caught:
        provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10))
    assert sent(session)[3] == 10.0
    assert caught.value.__context__ is None  # requests 예외(요청 정보 포함)가 따라붙지 않는다
    assert_key_hidden(caught.value)


def test_connection_error_raises_unavailable():
    provider, _ = make_provider(requests.ConnectionError(f"connection refused {API_KEY}"))

    with pytest.raises(ProviderUnavailableError, match="연결하지 못했습니다") as caught:
        provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10))
    assert "ConnectionError" in str(caught.value)
    assert caught.value.__context__ is None
    assert_key_hidden(caught.value)


@pytest.mark.parametrize(
    "bad",
    [
        response(json_error=True),
        response(body={}),
        response(body={"routes": []}),
        response(body={"routes": [{"result_code": 0}]}),
        response(body={"routes": [{"result_code": 0, "summary": {"duration": -5}}]}),
    ],
)
def test_malformed_response_raises_provider_error(bad):
    provider, _ = make_provider(bad)

    with pytest.raises(RouteProviderError):
        provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10))


def test_cache_reuses_same_route_and_minute():
    provider, session = make_provider(ok(duration=1800), ok(duration=2000), ok(duration=2100), ok(duration=2200))

    first = provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10))
    # 같은 분(초는 내림), 같은 순간의 다른 시간대 표현은 캐시를 쓴다.
    again = provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10) + timedelta(seconds=30))
    same_instant_utc = provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, datetime(2026, 11, 4, 23, 10, tzinfo=timezone.utc))
    assert first == again == same_instant_utc == 1800
    assert session.get.call_count == 1

    # 출발시각, 방향이 다르면 새로 조회한다.
    assert provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 11)) == 2000
    assert provider.get_duration(DONGEUI_UNIV, GIMHAE_CITY_HALL, kst(5, 8, 10)) == 2100
    assert session.get.call_count == provider.request_count == 3


def test_errors_are_not_cached():
    provider, session = make_provider(response(status=503, json_error=True), ok(duration=1700))

    with pytest.raises(ProviderUnavailableError):
        provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10))
    assert provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 10)) == 1700
    assert session.get.call_count == 2


def test_cache_evicts_least_recently_used():
    provider, session = make_provider(ok(1000), ok(1100), ok(1200), ok(1300), cache_size=2)

    provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 0))  # A
    provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 1))  # B
    provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 0))  # A 적중 -> B가 가장 오래됨
    provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 2))  # C, B를 버림
    assert session.get.call_count == 3
    assert provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 0)) == 1000  # A는 남아 있음
    assert provider.get_duration(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 8, 1)) == 1300  # B는 다시 조회
    assert session.get.call_count == 4


def test_cache_is_shared_across_solver_requests(clock):
    """같은 조건을 다시 검색하면 API를 부르지 않는다 (일일 쿼터 절약)."""
    session = Mock(spec=requests.Session)
    session.get.side_effect = lambda url, params, headers, timeout: ok(duration=1800 + int(params["departure_time"][-2:]) * 6)
    provider = KakaoRouteProvider(API_KEY, session=session)
    solver = DepartureSolver(provider, clock=clock)

    first = solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 9), 10)
    calls_after_first = session.get.call_count
    second = solver.solve(GIMHAE_CITY_HALL, DONGEUI_UNIV, kst(5, 9), 10)

    assert first.depart_at == second.depart_at
    assert first.provider_calls <= 8
    assert session.get.call_count == calls_after_first


def test_requires_api_key():
    with pytest.raises(ValueError, match="KAKAO_REST_API_KEY"):
        KakaoRouteProvider("")
