import json
import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api.factory import create_app
from app.config import Settings
from app.departure import (
    DEFAULT_ROUTE_OPTION,
    Coordinate,
    ProviderAuthError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    RouteNotFoundError,
    RouteProvider,
    RouteProviderError,
    RouteSummary,
    TravelMode,
)
from app.routing import NO_FREE_ROUTE_MESSAGE, parse_detailed_route
from tests.conftest import DONGEUI_UNIV, NOW, SEOUL_STATION, kst
from tests.test_kakao_provider import make_provider, response

FRONTEND_ROUTES_MOCK = Path(__file__).resolve().parents[2] / "frontend" / "js" / "mock" / "routes.json"
CARD_FIELDS = ["id", "options", "label", "name", "departTime", "arriveTime", "durationMin", "distanceKm", "toll", "fuel",
               "bufferApplied", "converged", "dataSource", "path", "aiSummary"]


def detail(offset=0, duration=600, distance=2000, toll=700):
    return {"result_code": 0, "summary": {"duration": duration, "distance": distance, "fare": {"toll": toll}},
            "sections": [{"roads": [{"vertexes": [128.8, 35.2, 128.9, 35.21 + offset]},
                                     {"vertexes": [128.9, 35.21 + offset, 129, 35.22]}]},
                         {"roads": [{"vertexes": [129, 35.22, 129.01, 35.23]}]}]}


def test_vertex_order_duplicates_and_metrics():
    parsed = parse_detailed_route(detail())
    assert parsed["path"] == [{"lat": 35.2, "lng": 128.8}, {"lat": 35.21, "lng": 128.9},
                              {"lat": 35.22, "lng": 129}, {"lat": 35.23, "lng": 129.01}]
    assert parsed["durationSec"] == 600
    assert parsed["distanceKm"] == 2


@pytest.mark.parametrize("vertices", [[], [129], [129, 35, 130], [None, 35], [True, 35], [129, 95], [float('nan'), 35]])
def test_invalid_geometry_never_draws_endpoint_shortcut(vertices):
    route = detail()
    route["sections"][0]["roads"][0]["vertexes"] = vertices
    with pytest.raises(RouteProviderError):
        parse_detailed_route(route)


def test_no_sections_rejected():
    route = detail()
    route["sections"] = []
    with pytest.raises(RouteProviderError):
        parse_detailed_route(route)


class RoadProvider(RouteProvider):
    """카카오처럼 옵션마다 다른 길을 돌려준다 (same=True면 모두 같은 길). 무료도로는 통행료가 없다."""

    PRIORITIES = ["RECOMMEND", "TIME", "DISTANCE"]

    def __init__(self, same=False):
        self.same = same
        self.summary_calls = []
        self.detail_calls = []

    def _route(self, priority, avoid):
        index = 3 if "toll" in avoid else self.PRIORITIES.index(priority)
        if self.same:
            return detail()
        return detail(index / 100, 600 + index * 60, 2000 + index * 100, toll=0 if index == 3 else 700)

    def search_places(self, name):
        return [{"id": name, "name": name, "address": name + " 주소", "lat": 35.2, "lng": 128.8 if name == '출발' else 129.01}]

    def get_duration(self, origin, dest, depart_at, travel_mode=TravelMode.CAR):
        return self.get_route_summary(origin, dest, depart_at).duration_sec

    def get_route_summary(self, origin, dest, depart_at, option=DEFAULT_ROUTE_OPTION):
        self.summary_calls.append((depart_at, option.key))
        summary = self._route(option.priority, option.avoid)["summary"]
        return RouteSummary(summary["duration"], summary["distance"], summary["fare"]["toll"])

    def get_detailed_route(self, origin, dest, depart_at, priority, avoid=()):
        self.detail_calls.append((depart_at, priority, avoid))
        return self._route(priority, avoid)


def client(provider=None, **kwargs):
    return TestClient(create_app(Settings(route_provider="kakao"), provider or RoadProvider(), clock=lambda: NOW), **kwargs)


def params(**changes):
    return {"from": "출발", "to": "도착", "arrive": kst(5, 9).isoformat(), "buffer": 10, **changes}


def without(key):
    query = params()
    del query[key]
    return query


# --- 정상 ---


def test_cards_are_camelcase_and_from_one_detailed_response_each():
    result = client().get('/api/routes', params=params())

    assert result.status_code == 200, result.text
    assert result.headers['Cache-Control'] == 'no-store'
    routes = result.json()
    assert [route['id'] for route in routes] == ['recommend', 'time', 'distance', 'free']
    assert [route['label'] for route in routes] == ['추천', '최단시간', '최단거리', '무료도로']
    for i, route in enumerate(routes):
        assert list(route) == CARD_FIELDS
        assert route['options'] == [route['id']]
        assert route['path'][1]['lat'] == 35.21 + i / 100
        assert route['durationMin'] == 10 + i
        assert route['distanceKm'] == 2 + i / 10
        assert route['toll'] == (0 if route['id'] == 'free' else 700)
        assert route['dataSource'] == 'kakao'
        assert route['fuel'] is None
        assert route['name'] == route['label']  # 도로 이름이 없는 응답
        assert (datetime.fromisoformat(route['arriveTime']) - datetime.fromisoformat(route['departTime'])).total_seconds() == (10 + i) * 60
        assert datetime.fromisoformat(route['arriveTime']) <= kst(5, 8, 50)
        assert route['departTime'].endswith('+09:00')


def test_frontend_card_fields_are_all_present():
    """프론트 목업(js/mock/routes.json)의 카드 필드가 실제 응답에서 빠지지 않는다."""
    frontend_fields = set().union(*(card.keys() for card in json.loads(FRONTEND_ROUTES_MOCK.read_text(encoding='utf-8'))))
    expected = {'id', 'label', 'name', 'departTime', 'arriveTime', 'durationMin', 'distanceKm', 'toll', 'fuel', 'path',
                'dataSource', 'bufferApplied', 'converged', 'aiSummary'}

    assert expected - frontend_fields <= {'bufferApplied', 'converged'}  # 목업에 아직 없는 필드
    for route in client().get('/api/routes', params=params()).json():
        assert frontend_fields | expected <= set(route)
        assert set(route['aiSummary']) == {'title', 'text'}


def test_identical_alternatives_are_merged_not_fabricated(caplog):
    with caplog.at_level(logging.INFO, logger='app.api'):
        routes = client(RoadProvider(same=True)).get('/api/routes', params=params()).json()

    assert len(routes) == 1
    assert routes[0]['options'] == ['recommend', 'time', 'distance']
    # 같은 유료 길이라 무료도로는 빠지고, 이유는 응답이 아니라 로그에 남는다.
    free_logs = [record for record in caplog.records if 'free' in record.getMessage()]
    assert free_logs and free_logs[0].levelno == logging.INFO
    assert NO_FREE_ROUTE_MESSAGE in free_logs[0].getMessage()
    assert NO_FREE_ROUTE_MESSAGE not in json.dumps(routes, ensure_ascii=False)


def test_failed_option_is_left_out_and_logged_as_warning(caplog):
    provider = RoadProvider()
    original = provider.get_route_summary

    def summary(origin, dest, depart_at, option=DEFAULT_ROUTE_OPTION):
        if option.key == 'distance':
            raise RouteNotFoundError('해당 조건으로 자동차 경로를 찾을 수 없습니다.', 103)
        return original(origin, dest, depart_at, option)

    provider.get_route_summary = summary
    with caplog.at_level(logging.INFO, logger='app.api'):
        result = client(provider).get('/api/routes', params=params())

    assert result.status_code == 200
    assert [route['id'] for route in result.json()] == ['recommend', 'time', 'free']
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert any('distance' in message and '경로를 찾을 수 없습니다' in message for message in warnings)


def test_mock_backend_compares_routes_with_coordinates():
    api = TestClient(create_app(Settings(), clock=lambda: NOW))

    result = api.get('/api/routes', params=params(fromLat=35.2285, fromLng=128.8894, toLat=35.1441, toLng=129.0336))

    assert result.status_code == 200, result.text
    routes = result.json()
    assert [route['id'] for route in routes] == ['recommend', 'time', 'distance', 'free']
    assert all(route['dataSource'] == 'mock' and route['name'].startswith('가상') for route in routes)


def test_mock_backend_needs_coordinates_for_names():
    api = TestClient(create_app(Settings(), clock=lambda: NOW))

    result = api.get('/api/routes', params=params())

    assert result.status_code == 422
    assert result.json() == {'message': '장소를 하나로 확인할 수 없어요. 정확한 장소명이나 주소로 다시 검색해 주세요.'}


def test_mock_backend_still_has_no_place_search():
    api = TestClient(create_app(Settings(), clock=lambda: NOW))
    assert api.get('/api/places', params={'q': '김해'}).status_code == 502


def test_compare_options_setting_controls_cards():
    settings = Settings(route_provider="kakao", route_compare_options=("free", "recommend"))
    api = TestClient(create_app(settings, RoadProvider(), clock=lambda: NOW))

    assert [route['id'] for route in api.get('/api/routes', params=params()).json()] == ['free', 'recommend']


# --- 400: 필드별 메시지 ---


@pytest.mark.parametrize(('query', 'message'), [
    (params(buffer=2), '여유시간은 0, 5, 10, 15분 중 하나여야 합니다.'),
    (params(buffer='ten'), '여유시간은 0, 5, 10, 15분 중 하나여야 합니다.'),
    (params(**{'from': ' '}), '출발지는 1~100자로 입력해 주세요.'),
    (params(to='가' * 101), '목적지는 1~100자로 입력해 주세요.'),
    (params(to='출발'), '출발지와 다른 목적지를 입력해 주세요.'),
    (without('from'), '출발지가 필요합니다.'),
    (without('to'), '목적지가 필요합니다.'),
    (without('arrive'), '도착 희망 시각이 필요합니다.'),
    (params(arrive='내일 9시'), '도착 희망 시각은 ISO 8601 형식이어야 합니다 (예: 2026-11-06T09:00:00+09:00).'),
    (params(arrive=NOW.isoformat()), '도착 희망 시각이 이미 지났습니다.'),
    (params(fromLat=35), '출발지 위도와 경도를 함께 보내 주세요.'),
    (params(toLng=129), '목적지 위도와 경도를 함께 보내 주세요.'),
    (params(fromLat=95, fromLng=129), '출발지 위도는 -90~90 사이의 숫자여야 합니다.'),
    (params(fromLat='nan', fromLng=129), '출발지 위도는 -90~90 사이의 숫자여야 합니다.'),
    (params(toLat=35, toLng='abc'), '목적지 경도는 -180~180 사이의 숫자여야 합니다.'),
], ids=['buffer', 'buffer-text', 'blank-from', 'long-to', 'same-place', 'no-from', 'no-to', 'no-arrive', 'bad-arrive',
        'past-arrive', 'half-from', 'half-to', 'lat-range', 'lat-nan', 'lng-text'])
def test_invalid_request_returns_400_with_field_message(query, message):
    provider = RoadProvider()

    result = client(provider).get('/api/routes', params=query)

    assert result.status_code == 400
    assert result.json() == {'message': message}
    assert provider.summary_calls == provider.detail_calls == []


def test_naive_arrive_is_kst():
    routes = client().get('/api/routes', params=params(arrive='2026-11-05T09:00:00')).json()
    assert datetime.fromisoformat(routes[0]['arriveTime']) <= kst(5, 8, 50)


# --- 422 ---


def test_ambiguous_place_name_is_422():
    provider = RoadProvider()
    provider.search_places = lambda name: [{'name': name, 'address': '중복', 'lat': 35, 'lng': 129}] * 2
    result = client(provider).get('/api/routes', params=params())
    assert result.status_code == 422
    assert provider.summary_calls == []


def test_all_options_too_late_is_422():
    api = TestClient(create_app(Settings(), clock=lambda: NOW))
    # 06:00에 서울역 -> 동의대학교, 06:30 도착은 어떤 옵션으로도 불가능하다.
    query = params(arrive=kst(4, 6, 30).isoformat(), buffer=0, fromLat=SEOUL_STATION.lat, fromLng=SEOUL_STATION.lng,
                   toLat=DONGEUI_UNIV.lat, toLng=DONGEUI_UNIV.lng)

    result = api.get('/api/routes', params=query)

    assert result.status_code == 422
    assert result.json() == {'message': '지금 출발해도 도착 희망 시각까지 도착할 수 없습니다.'}


# --- 5xx ---


@pytest.mark.parametrize(('error', 'status'), [
    (ProviderAuthError('인증 실패 KAKAO_REST_API_KEY'), 502),
    (ProviderQuotaExceededError('길찾기 API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.'), 503),
    (ProviderTimeoutError('길찾기 서버 응답이 늦습니다. 잠시 후 다시 시도해 주세요.'), 504),
], ids=['auth', 'quota', 'timeout'])
def test_provider_failure_is_5xx_and_not_replaced_with_mock(error, status):
    provider = RoadProvider()
    provider.get_route_summary = Mock(side_effect=error)

    result = client(provider).get('/api/routes', params=params())

    assert result.status_code == status
    assert 'path' not in result.text
    assert 'KAKAO_REST_API_KEY' not in result.text
    assert provider.get_route_summary.call_count == 1  # 다른 옵션은 부르지 않는다


def test_detailed_failure_is_5xx():
    provider = RoadProvider()
    provider.get_detailed_route = Mock(side_effect=ProviderAuthError('인증 실패'))
    result = client(provider).get('/api/routes', params=params())
    assert result.status_code == 502
    assert '인증 실패' not in result.text


# --- 카카오 어댑터 (상세 요청, 장소 검색) ---


def test_detailed_request_parameters_and_shared_auth_handling():
    provider, session = make_provider(response(body={'routes': [detail()]}))
    provider.get_detailed_route(Coordinate(35.2, 128.8), Coordinate(35.23, 129.01), kst(5, 8), 'TIME')
    query = session.get.call_args.kwargs['params']
    assert query['priority'] == 'TIME'
    assert query['summary'] == 'false'
    assert query['alternatives'] == 'false'
    assert query['origin'] == '128.8,35.2'


def test_server_keyword_and_address_fallback():
    provider, _ = make_provider(response(body={'documents': []}), response(body={'documents': [
        {'address_name': '부산광역시 주소', 'x': '129.01', 'y': '35.23'}]}))
    place = provider.search_places('부산광역시 주소')[0]
    assert place['lat'] == 35.23
    assert place['lng'] == 129.01


def test_selected_coordinates_avoid_ambiguous_name_lookup():
    provider = RoadProvider()
    provider.search_places = Mock(side_effect=AssertionError("selected coordinates must be used"))
    result = client(provider).get('/api/routes', params=params(fromLat=35.2, fromLng=128.8, toLat=35.23, toLng=129.01))
    assert result.status_code == 200
    provider.search_places.assert_not_called()


# --- 응답 캐시 ---


def test_route_result_cache_reuses_same_query_and_is_bounded():
    provider = RoadProvider()
    api = client(provider)
    first = api.get('/api/routes', params=params())
    count = len(provider.summary_calls) + len(provider.detail_calls)
    second = api.get('/api/routes', params=params())
    assert first.headers['X-Gilit-Route-Cache'] == 'MISS'
    assert second.headers['X-Gilit-Route-Cache'] == 'HIT'
    assert second.headers['Cache-Control'] == 'no-store'
    assert first.json() == second.json()
    assert len(provider.summary_calls) + len(provider.detail_calls) == count
    api.get('/api/routes', params=params(buffer=15))
    assert len(provider.summary_calls) + len(provider.detail_calls) > count


def test_cache_ttl_disabled_expiry_bound_copy_and_past_departure():
    from app.routing import RouteResultCache
    ticks = [0]
    cache = RouteResultCache(ttl=10, max_entries=1, monotonic=lambda: ticks[0])
    routes = [{"path": [{"lat": 35, "lng": 129}], "departTime": kst(5, 8).isoformat()}]
    cache.put('one', routes)
    copy = cache.get('one', NOW)
    copy[0]['path'][0]['lat'] = 40
    assert cache.get('one', NOW)[0]['path'][0]['lat'] == 35
    ticks[0] = 10
    assert cache.get('one', NOW) is None
    cache.put('one', routes)
    cache.put('two', routes)
    assert cache.get('one', NOW) is None
    assert cache.get('two', kst(5, 9)) is None
    disabled = RouteResultCache(ttl=0)
    disabled.put('one', routes)
    assert disabled.get('one', NOW) is None


# --- /docs ---


def test_openapi_shows_card_schema():
    spec = client().get('/openapi.json').json()
    schema = spec['paths']['/api/routes']['get']['responses']['200']['content']['application/json']['schema']
    assert schema['items']['$ref'].endswith('/RouteCardResponse')
    assert list(spec['components']['schemas']['RouteCardResponse']['properties']) == CARD_FIELDS
    assert {param['name'] for param in spec['paths']['/api/routes']['get']['parameters']} >= {
        'from', 'to', 'arrive', 'buffer', 'fromLat', 'fromLng', 'toLat', 'toLng'}
