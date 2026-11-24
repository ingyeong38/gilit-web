"""프론트 공개 설정 GET /api/config 테스트. 응답은 kakaoJsKey·ga4MeasurementId 두 개뿐이어야 한다."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.api.factory import create_app
from app.config import Settings, valid_ga4_measurement_id
from app.departure import MockRouteProvider

BASE_URL = "https://testserver"
JS_KEY = "fake-kakao-js-key-0001"
MEASUREMENT_ID = "G-FAKE123"
# 응답에 절대 나오면 안 되는 값. 모두 가짜 값이다.
SECRETS = {
    "KAKAO_REST_API_KEY": "fake-kakao-rest-key-0002",
    "GOOGLE_CLIENT_ID": "fake-google-client-id-0003",
    "GOOGLE_CLIENT_SECRET": "fake-google-client-secret-0004",
    "KAKAO_LOGIN_CLIENT_ID": "fake-kakao-login-id-0005",
    "KAKAO_LOGIN_CLIENT_SECRET": "fake-kakao-login-secret-0006",
    "SECRET_KEY": "fake-secret-key-0007",
    "GEMINI_API_KEY": "fake-gemini-key-0008",
    "GEMINI_MODEL": "fake-gemini-model-0009",
    "DB_HOST": "fake-db-host-0010",
    "DB_USER": "fake-db-user-0011",
    "DB_PASSWORD": "fake-db-password-0012",
    "DB_NAME": "fake_db_name_0013",
    "GA4_PROPERTY_ID": "9990014",
    "GOOGLE_APPLICATION_CREDENTIALS": "C:/fake/adc-0015.json",
    "OAUTH_REDIRECT_BASE": "http://localhost:8000",
}


def get_config(app) -> "TestClient.get":
    return TestClient(app, base_url=BASE_URL).get("/api/config")


def app_from_env(monkeypatch, **env) -> object:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return create_app()  # .env는 conftest가 막고, 위 환경변수만 읽는다


def test_returns_both_values_when_set(monkeypatch):
    response = get_config(app_from_env(monkeypatch, KAKAO_JS_KEY=JS_KEY, GA4_MEASUREMENT_ID=MEASUREMENT_ID))
    assert response.status_code == 200
    assert response.json() == {"kakaoJsKey": JS_KEY, "ga4MeasurementId": MEASUREMENT_ID}


def test_empty_strings_when_unset():
    response = get_config(create_app(Settings(), MockRouteProvider()))
    assert response.status_code == 200
    assert response.json() == {"kakaoJsKey": "", "ga4MeasurementId": ""}


@pytest.mark.parametrize("bad", ["UA-12345-1", "g-abc123", "G-", "G-ABC 123", "G-ABC<script>", "AW-123", "G-ABC\n-1"])
def test_invalid_measurement_id_becomes_empty_and_logs_name_only(monkeypatch, caplog, bad):
    with caplog.at_level(logging.DEBUG):
        app = app_from_env(monkeypatch, GA4_MEASUREMENT_ID=bad)
    assert get_config(app).json()["ga4MeasurementId"] == ""
    assert "GA4_MEASUREMENT_ID" in caplog.text
    if len(bad) > 2:  # "G-"는 경고 문구의 형식 안내(G-XXXX)와 겹친다
        assert bad not in caplog.text


def test_measurement_id_surrounding_whitespace_is_trimmed(monkeypatch):
    app = app_from_env(monkeypatch, GA4_MEASUREMENT_ID="  G-ABC\n")
    assert get_config(app).json()["ga4MeasurementId"] == "G-ABC"


def test_measurement_id_is_revalidated_even_if_settings_built_directly():
    app = create_app(Settings(ga4_measurement_id="not-an-id"), MockRouteProvider())
    assert get_config(app).json()["ga4MeasurementId"] == ""
    assert valid_ga4_measurement_id(" G-OK1 ") == "G-OK1"


def test_only_two_keys_and_no_secrets(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        app = app_from_env(monkeypatch, KAKAO_JS_KEY=JS_KEY, GA4_MEASUREMENT_ID=MEASUREMENT_ID, **SECRETS)
        response = get_config(app)
    assert set(response.json()) == {"kakaoJsKey", "ga4MeasurementId"}
    body = response.text
    for name, value in SECRETS.items():
        if name == "OAUTH_REDIRECT_BASE":
            continue
        assert value not in body, name
    # 값은 로그에 남기지 않는다 (공개 값이라도).
    for value in (JS_KEY, MEASUREMENT_ID, *SECRETS.values()):
        if value.startswith("http"):
            continue
        assert value not in caplog.text


def test_no_login_needed_and_no_store():
    client = TestClient(create_app(Settings(kakao_js_key=JS_KEY), MockRouteProvider()), base_url=BASE_URL)
    response = client.get("/api/config")  # 세션 쿠키 없음
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    # 다른 출처의 페이지가 GET하더라도 출처 검사(POST 등 전용)에 막히지 않는다.
    assert client.get("/api/config", headers={"Origin": "https://other.example"}).status_code == 200


def test_settings_repr_hides_js_key():
    assert JS_KEY not in repr(Settings(kakao_js_key=JS_KEY))
