from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api.factory import create_app
from app.config import Settings
from app.departure import Coordinate, ProviderAuthError, RouteProviderError
from app.routing import parse_detailed_route
from tests.conftest import NOW, kst
from tests.test_kakao_provider import make_provider, response


def detail(offset=0, duration=600, distance=2000):
    return {"result_code": 0, "summary": {"duration": duration, "distance": distance, "fare": {"toll": 700}},
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


class RoadProvider:
    def __init__(self, same=False):
        self.same = same
        self.calls = []

    def search_places(self, name):
        return [{"id": name, "name": name, "address": name + " 주소", "lat": 35.2, "lng": 128.8 if name == '출발' else 129.01}]

    def get_detailed_route(self, origin, dest, depart_at, priority):
        self.calls.append((depart_at, priority))
        index = ["RECOMMEND", "TIME", "DISTANCE"].index(priority)
        return detail(0 if self.same else index / 100, 600 if self.same else 600 + index * 60,
                      2000 if self.same else 2000 + index * 100)


def client(provider=None):
    return TestClient(create_app(Settings(route_provider="kakao"), provider or RoadProvider(), clock=lambda: NOW))


def params(**changes):
    return {"from": "출발", "to": "도착", "arrive": kst(5, 9).isoformat(), "buffer": 10, **changes}


def test_final_card_time_distance_path_are_same_response_and_not_mixed():
    response = client().get('/api/routes', params=params())
    assert response.status_code == 200, response.text
    routes = response.json()
    assert len(routes) == 3
    for i, route in enumerate(routes):
        assert route['path'][1]['lat'] == 35.21 + i / 100
        assert route['durationMin'] == 10 + i
        assert route['distanceKm'] == 2 + i / 10
        assert route['dataSource'] == 'kakao'
        assert route['fuel'] is None
        from datetime import datetime
        assert (datetime.fromisoformat(route['arriveTime']) - datetime.fromisoformat(route['departTime'])).total_seconds() == (10 + i) * 60


def test_identical_alternatives_not_fabricated():
    assert len(client(RoadProvider(same=True)).get('/api/routes', params=params()).json()) == 1


@pytest.mark.parametrize('changes', [{'buffer': 2}, {'from': ' '}, {'to': '출발'}, {'arrive': NOW.isoformat()}])
def test_invalid_request(changes):
    assert client().get('/api/routes', params=params(**changes)).status_code in (400, 422)


def test_places_and_ambiguous_name():
    api = client()
    assert api.get('/api/places', params={'q': '출발'}).json()[0]['name'] == '출발'
    provider = RoadProvider()
    provider.search_places = lambda name: [{'name': name, 'address': '중복', 'lat': 35, 'lng': 129}] * 2
    assert client(provider).get('/api/routes', params=params()).status_code == 422


def test_auth_failure_not_replaced_with_mock_and_key_not_exposed():
    provider = RoadProvider()
    provider.get_detailed_route = Mock(side_effect=ProviderAuthError('인증 실패'))
    result = client(provider).get('/api/routes', params=params())
    assert result.status_code == 502
    assert 'path' not in result.text
    assert '인증 실패' not in result.text


def test_mock_backend_does_not_claim_live_routes():
    api = TestClient(create_app(Settings(), clock=lambda: NOW))
    assert api.get('/api/routes', params=params()).status_code == 502


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


@pytest.mark.parametrize('extra', [{'fromLat': 35}, {'fromLat': 95, 'fromLng': 129}, {'fromLat': 'nan', 'fromLng': 129}])
def test_invalid_or_partial_selected_coordinates_rejected(extra):
    assert client().get('/api/routes', params=params(**extra)).status_code in (400, 422)


def test_route_result_cache_reuses_same_query_and_is_bounded():
    provider = RoadProvider()
    api = client(provider)
    first = api.get('/api/routes', params=params())
    count = len(provider.calls)
    second = api.get('/api/routes', params=params())
    assert first.headers['X-Gilit-Route-Cache'] == 'MISS'
    assert second.headers['X-Gilit-Route-Cache'] == 'HIT'
    assert first.json() == second.json()
    assert len(provider.calls) == count
    api.get('/api/routes', params=params(buffer=15))
    assert len(provider.calls) > count


def test_cache_ttl_disabled_expiry_bound_copy_and_past_departure():
    from app.routing import RouteResultCache
    from datetime import timedelta
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
