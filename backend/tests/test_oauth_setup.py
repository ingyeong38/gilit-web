"""실제 키 없이 설정 누락의 격리와 다른 API의 가용성을 검증한다."""
import pytest
from fastapi.testclient import TestClient
from app.api.factory import create_app
from app.config import Settings, create_oauth_clients
from app.departure import MockRouteProvider


@pytest.mark.parametrize('values', [
    {}, {'GOOGLE_CLIENT_ID': 'test-only-id'},
    {'KAKAO_LOGIN_CLIENT_SECRET': 'test-only-secret'},
    {'GOOGLE_CLIENT_ID': 'test-only-id', 'GOOGLE_CLIENT_SECRET': 'test-only-secret'},
])
def test_missing_oauth_settings_do_not_disable_other_apis(values, caplog):
    app = create_app(Settings.from_env(values), MockRouteProvider())
    client = TestClient(app, base_url='https://testserver', follow_redirects=False)
    assert client.get('/health').status_code == 200
    for provider in ('google', 'kakao'):
        started = client.get(f'/api/auth/{provider}/start')
        assert started.status_code == 302
        assert started.headers['location'] == '/pages/search.html?auth_result=not_configured'
        assert 'gilit_session' not in started.headers.get('set-cookie', '')
    assert client.get('/api/auth/me').status_code == 401
    body = {'name': '테스트', 'email': 'setup@example.com', 'password': 'gilit1234',
            'agreeTerms': True, 'agreePrivacy': True}
    assert client.post('/api/auth/signup', json=body).status_code == 201
    assert client.post('/api/auth/login', json={'email': body['email'], 'password': body['password']}).status_code == 200
    assert client.get('/api/auth/me').json()['provider'] == 'email'
    assert client.post('/api/auth/logout').status_code == 204
    assert client.get('/api/auth/me').status_code == 401
    assert 'test-only-secret' not in caplog.text
    assert 'test-only-id' not in caplog.text


@pytest.mark.parametrize('ready, incomplete', [('google', 'kakao'), ('kakao', 'google')])
def test_incomplete_provider_does_not_disable_ready_provider(ready, incomplete):
    prefixes = {'google': 'GOOGLE', 'kakao': 'KAKAO_LOGIN'}
    prefix = prefixes[ready]
    env = {'SECRET_KEY': 'unit-test-signing-secret', 'OAUTH_REDIRECT_BASE': 'http://localhost:8000',
           f'{prefix}_CLIENT_ID': 'test-only-id', f'{prefix}_CLIENT_SECRET': 'test-only-secret',
           f'{prefixes[incomplete]}_CLIENT_ID': 'incomplete-test-id'}
    clients = create_oauth_clients(Settings.from_env(env))
    assert set(clients) == {ready}
