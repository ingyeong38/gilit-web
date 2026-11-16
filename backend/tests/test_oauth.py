"""소셜 로그인(3단계 Google) 테스트. 가짜 OAuthClient를 넣고 실제 Google은 부르지 않는다.

웹 흐름 테스트는 store_backend fixture로 메모리와 MySQL(mysql_live)에서 같은 테스트를 돌린다.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE
from app.api.factory import create_app
from app.api.oauth import OAUTH_COOKIE
from app.auth import (
    AuthService,
    EmailAlreadyExistsError,
    OAuthError,
    OAuthProfile,
    PasswordHasher,
    SocialAccountExistsError,
    SocialEmailConflictError,
    hash_token,
)
from app.auth.oauth import MOCK_CODE, GoogleOAuthClient, MockOAuthClient, code_challenge_s256
from app.auth.oauth_state import OAuthState, OAuthStateError, UsedStates, decode_state_cookie, encode_state_cookie
from app.auth.service import social_nickname, verified_email
from app.config import Settings, create_oauth_clients
from app.departure import MockRouteProvider
from tests.auth_backends import MemoryBackend
from tests.conftest import NOW

BASE_URL = "https://testserver"
SECRET = "test-secret-key-for-state-cookies"
STATE_TTL_SEC = 600


def make_profile(subject="g-123", email="user@example.com", verified=True, name="구글 사용자", provider="google"):
    return OAuthProfile(provider=provider, subject=subject, email=email, email_verified=verified, name=name)


class FakeOAuthClient:
    """제공자 흉내. 인증 화면 주소를 기록하고, 코드 교환 때 정해 둔 프로필(또는 오류)을 돌려준다."""

    def __init__(self, provider="google", profile=None, error=None) -> None:
        self.provider = provider
        self.profile = profile or make_profile(provider=provider)
        self.error = error
        self.authorize_calls: list[tuple[str, str, str]] = []
        self.fetch_calls: list[tuple[str, str, str]] = []

    def authorization_url(self, state, code_challenge, redirect_uri):
        self.authorize_calls.append((state, code_challenge, redirect_uri))
        return f"https://provider.example/authorize?state={state}"

    def fetch_profile(self, code, code_verifier, redirect_uri):
        self.fetch_calls.append((code, code_verifier, redirect_uri))
        if self.error is not None:
            raise self.error
        return self.profile


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@dataclass
class OEnv:
    app: object
    client: TestClient
    backend: object
    clock: FakeClock
    google: FakeOAuthClient
    auth: AuthService

    def new_client(self, **kwargs) -> TestClient:
        return TestClient(self.app, base_url=BASE_URL, follow_redirects=False, **kwargs)


def make_env(backend=None, settings=None, clients=None, google=None) -> OEnv:
    backend = backend or MemoryBackend()
    clock = FakeClock(NOW)
    google = google or FakeOAuthClient()
    auth = AuthService(backend.users, backend.sessions, PasswordHasher(rounds=4), clock=clock)
    settings = settings or Settings(secret_key=SECRET)
    app = create_app(settings, MockRouteProvider(), clock=clock, auth=auth, oauth_clients={"google": google} if clients is None else clients)
    return OEnv(app, TestClient(app, base_url=BASE_URL, follow_redirects=False), backend, clock, google, auth)


@pytest.fixture
def env(store_backend) -> OEnv:
    return make_env(store_backend)


def start(client: TestClient, provider="google"):
    response = client.get(f"/api/auth/{provider}/start")
    assert response.status_code == 302
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    return response, state


def callback(client: TestClient, provider="google", **params):
    return client.get(f"/api/auth/{provider}/callback", params=params)


def auth_result(response) -> str:
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert location.path == "/pages/search.html"
    return parse_qs(location.query)["auth_result"][0]


def set_cookies(response) -> dict[str, str]:
    """Set-Cookie 헤더들을 {이름: 헤더 전체(소문자)}로."""
    cookies = {}
    for header in response.headers.get_list("set-cookie"):
        cookies[header.split("=", 1)[0]] = header.lower()
    return cookies


def login_with_google(env: OEnv, client: TestClient | None = None, code="auth-code"):
    client = client or env.client
    _, state = start(client)
    return callback(client, code=code, state=state)


# --- 시작 ---


def test_start_redirects_to_provider_with_signed_state_cookie(env):
    response, state = start(env.client)

    assert response.headers["location"].startswith("https://provider.example/authorize?")
    assert response.headers["cache-control"] == "no-store"
    cookie = set_cookies(response)[OAUTH_COOKIE]
    attributes = [part.strip() for part in cookie.split(";")]
    assert "httponly" in attributes
    assert "samesite=lax" in attributes
    assert "path=/api/auth" in attributes
    assert f"max-age={STATE_TTL_SEC}" in attributes
    assert "secure" in attributes
    # 쿠키는 서명돼 있고 같은 state를 담는다.
    raw = env.client.cookies.get(OAUTH_COOKIE, path="/api/auth")
    value = decode_state_cookie(SECRET, raw, "google", state, NOW.timestamp())
    assert value.expires_at == int(NOW.timestamp()) + STATE_TTL_SEC


def test_start_uses_pkce_s256_and_same_redirect_uri_for_exchange():
    env = make_env(settings=Settings(secret_key=SECRET, oauth_redirect_base="http://localhost:8000"))

    login_with_google(env)

    (state, challenge, redirect_uri), = env.google.authorize_calls
    (code, verifier, exchange_redirect_uri), = env.google.fetch_calls
    assert redirect_uri == exchange_redirect_uri == "http://localhost:8000/api/auth/google/callback"
    assert 43 <= len(verifier) <= 128
    assert challenge == code_challenge_s256(verifier)
    assert challenge != verifier
    assert code == "auth-code"


def test_each_start_issues_fresh_state(env):
    _, first = start(env.client)
    _, second = start(env.client)

    assert first != second


def test_unknown_provider_is_404_and_unconfigured_provider_fails(env):
    assert env.client.get("/api/auth/naver/start").status_code == 404
    assert env.client.get("/api/auth/naver/start").json() == {"message": "찾을 수 없습니다."}
    assert auth_result(env.client.get("/api/auth/kakao/start")) == "not_configured"  # 4단계 전에는 설정되지 않음
    assert auth_result(callback(env.client, "kakao", code="x", state="y")) == "failed"


def test_google_not_configured_redirects_failed():
    env = make_env(clients={})

    assert auth_result(env.client.get("/api/auth/google/start")) == "not_configured"


# --- 첫 가입 ---


def test_first_login_with_verified_email_creates_account_and_session(env):
    response = login_with_google(env)

    assert auth_result(response) == "success"
    cookies = set_cookies(response)
    assert "max-age=0" in cookies[OAUTH_COOKIE]  # state 쿠키는 지운다
    assert "httponly" in cookies[SESSION_COOKIE] and "samesite=lax" in cookies[SESSION_COOKIE]
    me = env.client.get("/api/auth/me").json()
    assert me["provider"] == "google"
    assert me["email"] == "user@example.com"
    assert me["name"] == "구글 사용자"
    user = env.backend.users.get_by_id(int(me["id"]))
    assert user.password_hash is None
    assert user.agreed_at == NOW and user.created_at == NOW and user.last_login_at == NOW
    assert env.backend.social_links() == [("google", "g-123", user.id)]


@pytest.mark.parametrize(
    "profile",
    [
        make_profile(email=None, verified=False),  # 이메일 없음
        make_profile(email="user@example.com", verified=False),  # 미검증
        make_profile(email="not-an-email", verified=True),  # 형식이 틀린 이메일
    ],
)
def test_first_login_without_verified_email_creates_account_with_null_email(store_backend, profile):
    env = make_env(store_backend, google=FakeOAuthClient(profile=profile))

    assert auth_result(login_with_google(env)) == "success"

    me = env.client.get("/api/auth/me").json()
    assert me["email"] is None
    assert env.backend.users.get_by_id(int(me["id"])).email is None


def test_verified_email_is_normalized_to_lowercase(store_backend):
    env = make_env(store_backend, google=FakeOAuthClient(profile=make_profile(email="  User@Example.COM ")))

    login_with_google(env)

    assert env.client.get("/api/auth/me").json()["email"] == "user@example.com"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("가" * 25, "가" * 20),
        (None, "길잇 사용자"),
        ("", "길잇 사용자"),
        ("   ", "길잇 사용자"),
        ("길\n잇​ 사용자", "길잇 사용자"),
        ("  Hong   Gil  Dong ", "Hong Gil Dong"),
    ],
)
def test_social_nickname(name, expected):
    assert social_nickname(name) == expected


def test_long_name_is_truncated_in_account(store_backend):
    env = make_env(store_backend, google=FakeOAuthClient(profile=make_profile(name="아주긴이름" * 6)))

    login_with_google(env)

    assert env.client.get("/api/auth/me").json()["name"] == ("아주긴이름" * 4)


def test_social_only_account_cannot_use_email_login(env):
    login_with_google(env)

    response = env.new_client().post("/api/auth/login", json={"email": "user@example.com", "password": "gilit1234"})

    assert response.status_code == 401


# --- 재로그인 ---


def test_returning_user_logs_into_same_account_without_changes(env):
    login_with_google(env)
    first_id = env.client.get("/api/auth/me").json()["id"]
    env.google.profile = make_profile(email="changed@example.com", name="바뀐 이름")  # 같은 sub, 제공자 정보 변경
    env.clock.now = NOW + timedelta(days=1)

    second = env.new_client()
    assert auth_result(login_with_google(env, second)) == "success"

    me = second.get("/api/auth/me").json()
    assert me["id"] == first_id
    assert (me["email"], me["name"]) == ("user@example.com", "구글 사용자")  # DB는 바꾸지 않는다
    assert env.backend.user_count() == 1
    assert env.backend.users.get_by_id(int(first_id)).last_login_at == NOW + timedelta(days=1)


def test_social_login_replaces_previous_session(env):
    """세션 고정 방지: 같은 브라우저의 이전 세션은 지운다."""
    login_with_google(env)
    old = env.client.cookies.get(SESSION_COOKIE)

    login_with_google(env)

    new = env.client.cookies.get(SESSION_COOKIE)
    assert new != old
    assert env.backend.sessions.get(hash_token(old)) is None
    assert env.backend.session_count() == 1


# --- 이메일 충돌 ---


def signup_email_user(env: OEnv, email="user@example.com"):
    body = {"name": "이메일가입", "email": email, "password": "gilit1234", "agreeTerms": True, "agreePrivacy": True}
    response = env.new_client().post("/api/auth/signup", json=body)
    assert response.status_code == 201
    return response.json()["id"]


def test_verified_email_of_existing_account_is_email_exists_without_linking(env):
    existing = signup_email_user(env)
    env.google.profile = make_profile(email="USER@example.com")

    response = login_with_google(env)

    assert auth_result(response) == "email_exists"
    assert SESSION_COOKIE not in set_cookies(response)
    assert "max-age=0" in set_cookies(response)[OAUTH_COOKIE]
    assert env.client.get("/api/auth/me").status_code == 401
    assert env.backend.user_count() == 1
    assert env.backend.social_links() == []
    # 기존 계정은 그대로 이메일 로그인할 수 있다.
    login = env.new_client().post("/api/auth/login", json={"email": "user@example.com", "password": "gilit1234"})
    assert login.json()["id"] == existing


def test_unverified_email_matching_existing_account_creates_separate_account(env):
    """미검증 이메일은 믿지 않으므로 기존 계정과 겹쳐도 연결하지 않고 이메일 없는 새 계정을 만든다."""
    existing = signup_email_user(env)
    env.google.profile = make_profile(email="user@example.com", verified=False)

    assert auth_result(login_with_google(env)) == "success"

    me = env.client.get("/api/auth/me").json()
    assert me["id"] != existing
    assert me["email"] is None
    assert env.backend.users.get_by_email("user@example.com").id == int(existing)


def test_email_signup_after_social_signup_is_409(env):
    login_with_google(env)

    body = {"name": "다른사람", "email": "user@example.com", "password": "gilit1234", "agreeTerms": True, "agreePrivacy": True}
    assert env.new_client().post("/api/auth/signup", json=body).status_code == 409


# --- state 검사 ---


def assert_rejected(env: OEnv, response):
    assert auth_result(response) == "failed"
    assert SESSION_COOKIE not in set_cookies(response)
    assert "max-age=0" in set_cookies(response)[OAUTH_COOKIE]  # 실패해도 지운다
    assert env.google.fetch_calls == []  # 코드 교환까지 가지 않는다
    assert env.backend.user_count() == 0


def test_forged_state_is_rejected(env):
    start(env.client)

    assert_rejected(env, callback(env.client, code="auth-code", state="attacker-state"))


def test_missing_state_or_code_is_rejected(env):
    start(env.client)
    assert_rejected(env, callback(env.client, code="auth-code"))

    _, state = start(env.client)
    response = callback(env.client, state=state)
    assert auth_result(response) == "failed"
    assert env.backend.user_count() == 0


def test_missing_cookie_is_rejected(env):
    _, state = start(env.client)
    other_browser = env.new_client()  # state는 알지만 쿠키가 없다 (로그인 CSRF)

    assert_rejected(env, callback(other_browser, code="auth-code", state=state))


def test_tampered_or_foreign_signed_cookie_is_rejected(env):
    _, state = start(env.client)
    raw = env.client.cookies.get(OAUTH_COOKIE, path="/api/auth")
    body, signature = raw.split(".")
    tampered = env.new_client(cookies={OAUTH_COOKIE: f"{body}.{signature[:-2]}AA"})
    foreign = env.new_client(
        cookies={OAUTH_COOKIE: encode_state_cookie("other-secret", OAuthState("google", state, "v" * 64, int(NOW.timestamp()) + 600))}
    )

    assert_rejected(env, callback(tampered, code="auth-code", state=state))
    assert_rejected(env, callback(foreign, code="auth-code", state=state))


def test_expired_state_is_rejected(env):
    _, state = start(env.client)
    env.clock.now = NOW + timedelta(seconds=STATE_TTL_SEC)

    assert_rejected(env, callback(env.client, code="auth-code", state=state))


def test_state_just_before_expiry_is_accepted(env):
    _, state = start(env.client)
    env.clock.now = NOW + timedelta(seconds=STATE_TTL_SEC - 1)

    assert auth_result(callback(env.client, code="auth-code", state=state)) == "success"


def test_provider_mismatch_is_rejected(env):
    """kakao로 시작한 state 쿠키를 google 콜백에 쓸 수 없다."""
    state = "same-state"
    kakao_cookie = encode_state_cookie(SECRET, OAuthState("kakao", state, "v" * 64, int(NOW.timestamp()) + 600))
    client = env.new_client(cookies={OAUTH_COOKIE: kakao_cookie})

    assert_rejected(env, callback(client, code="auth-code", state=state))


def test_state_cookie_can_be_used_only_once(env):
    _, state = start(env.client)
    raw = env.client.cookies.get(OAUTH_COOKIE, path="/api/auth")
    assert auth_result(callback(env.client, code="auth-code", state=state)) == "success"
    assert env.client.cookies.get(OAUTH_COOKIE, path="/api/auth") is None  # 브라우저에서도 지워졌다

    replay = env.new_client(cookies={OAUTH_COOKIE: raw})  # 쿠키와 콜백 URL을 그대로 다시 보낸다
    response = callback(replay, code="auth-code", state=state)

    assert auth_result(response) == "failed"
    assert SESSION_COOKIE not in set_cookies(response)
    assert len(env.google.fetch_calls) == 1


def test_failure_logs_do_not_contain_secrets(env, caplog):
    _, state = start(env.client)
    raw = env.client.cookies.get(OAUTH_COOKIE, path="/api/auth")

    with caplog.at_level(logging.INFO):
        callback(env.client, code="secret-auth-code", state="wrong-state")
        env.google.error = OAuthError("Google 토큰 교환 실패: HTTP 400")
        _, state2 = start(env.client)
        callback(env.client, code="secret-auth-code", state=state2)

    # 테스트 HTTP 클라이언트(httpx) 자체의 요청 로그는 빼고, 우리 앱 로그만 본다.
    app_logs = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))
    assert "state 불일치" in app_logs
    assert "토큰 교환 실패" in app_logs
    for secret in ("secret-auth-code", state, state2, raw, SECRET):
        assert secret not in app_logs


def test_access_log_redacts_callback_query():
    from app.api.oauth import RedactOAuthCallbackQuery, install_access_log_redaction

    def access_record(path):
        return logging.LogRecord(
            "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5", "GET", path, "1.1", 302), None
        )

    callback_record = access_record("/api/auth/google/callback?code=secret-code&state=secret-state")
    other_record = access_record("/api/routes?from=a&to=b")
    RedactOAuthCallbackQuery().filter(callback_record)
    RedactOAuthCallbackQuery().filter(other_record)

    assert callback_record.getMessage() == '127.0.0.1:5 - "GET /api/auth/google/callback?[REDACTED] HTTP/1.1" 302'
    assert other_record.getMessage().endswith('"GET /api/routes?from=a&to=b HTTP/1.1" 302')  # 다른 경로는 그대로
    install_access_log_redaction()
    install_access_log_redaction()
    assert sum(isinstance(f, RedactOAuthCallbackQuery) for f in logging.getLogger("uvicorn.access").filters) == 1


# --- 취소·제공자 오류 ---


def test_access_denied_is_cancelled(env):
    start(env.client)

    response = callback(env.client, error="access_denied", error_description="User denied")

    assert auth_result(response) == "cancelled"
    assert "max-age=0" in set_cookies(response)[OAUTH_COOKIE]
    assert env.google.fetch_calls == []
    assert env.backend.user_count() == 0


def test_other_provider_error_is_failed(env):
    _, state = start(env.client)

    assert auth_result(callback(env.client, error="server_error", state=state)) == "failed"


def test_token_exchange_failure_is_failed(store_backend):
    env = make_env(store_backend, google=FakeOAuthClient(error=OAuthError("Google 토큰 교환 실패: HTTP 400")))

    response = login_with_google(env)

    assert auth_result(response) == "failed"
    assert SESSION_COOKIE not in set_cookies(response)
    assert env.backend.user_count() == 0


def test_profile_from_other_provider_is_rejected(env):
    env.google.profile = make_profile(provider="kakao")

    assert auth_result(login_with_google(env)) == "failed"
    assert env.backend.user_count() == 0


def test_unexpected_error_during_account_handling_is_failed(env, monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("DB 연결 끊김")

    monkeypatch.setattr(env.auth, "social_login", broken)

    with caplog.at_level(logging.ERROR):
        assert auth_result(login_with_google(env)) == "failed"
    assert "소셜 로그인 처리 중 오류" in caplog.text


# --- 동시 첫 로그인 ---


@pytest.mark.parametrize("email", ["race@example.com", None])
def test_concurrent_first_logins_create_one_account(store_backend, email):
    auth = AuthService(store_backend.users, store_backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)
    profile = make_profile(subject="race-sub", email=email, verified=email is not None)
    workers = 8
    barrier = threading.Barrier(workers)

    def attempt(_):
        barrier.wait()
        return auth.social_login(profile, previous_token=None).current.user.id

    with ThreadPoolExecutor(workers) as pool:
        user_ids = list(pool.map(attempt, range(workers)))

    assert len(set(user_ids)) == 1  # 모두 같은 계정으로 로그인 (email_exists로 잘못 막히지 않는다)
    assert store_backend.user_count() == 1
    assert store_backend.social_links() == [("google", "race-sub", user_ids[0])]
    assert store_backend.session_count() == workers


class RaceUsers:
    """사전 조회는 비어 있었지만 INSERT 순간에는 다른 요청이 먼저 넣은 상황을 만든다."""

    def __init__(self, inner, hide_email=False, hide_social_once=False):
        self.inner = inner
        self.hide_email = hide_email
        self.hide_social_once = hide_social_once

    def get_by_email(self, email):
        return None if self.hide_email else self.inner.get_by_email(email)

    def get_by_social(self, provider, subject):
        if self.hide_social_once:
            self.hide_social_once = False
            return None
        return self.inner.get_by_social(provider, subject)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_email_signup_racing_social_signup_is_email_exists(store_backend):
    store_backend.users.create_email_user("race@example.com", "$2b$04$" + "x" * 53, "이메일가입", NOW)
    users = RaceUsers(store_backend.users, hide_email=True)
    auth = AuthService(users, store_backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)

    with pytest.raises(SocialEmailConflictError):
        auth.social_login(make_profile(email="race@example.com"), previous_token=None)

    assert store_backend.social_links() == []  # 트랜잭션이 rollback돼 남은 행이 없다
    assert store_backend.user_count() == 1


def test_social_account_created_meanwhile_is_reused(store_backend):
    first = store_backend.users.create_social_user("google", "g-123", None, "먼저", NOW)
    users = RaceUsers(store_backend.users, hide_social_once=True)
    auth = AuthService(users, store_backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)

    result = auth.social_login(make_profile(email=None, verified=False), previous_token=None)

    assert result.current.user.id == first.id
    assert store_backend.user_count() == 1


# --- 저장소: 소셜 가입 트랜잭션 ---


def test_create_social_user_and_lookup(store_backend):
    users = store_backend.users

    user = users.create_social_user("google", "g-1", "a@example.com", "구글", NOW)

    assert users.get_by_social("google", "g-1") == users.get_by_id(user.id)
    assert users.get_by_social("kakao", "g-1") is None
    assert users.get_by_social("google", "g-2") is None
    stored = users.get_by_id(user.id)
    assert (stored.email, stored.nickname, stored.password_hash, stored.agreed_at) == ("a@example.com", "구글", None, NOW)


def test_create_social_user_duplicate_social_leaves_nothing(store_backend):
    users = store_backend.users
    users.create_social_user("google", "g-1", None, "처음", NOW)

    with pytest.raises(SocialAccountExistsError):
        users.create_social_user("google", "g-1", "new@example.com", "두번째", NOW)

    assert users.get_by_email("new@example.com") is None  # users 행도 rollback
    assert store_backend.user_count() == 1


def test_create_social_user_duplicate_email_leaves_nothing(store_backend):
    users = store_backend.users
    users.create_email_user("a@example.com", "$2b$04$" + "x" * 53, "이메일", NOW)

    with pytest.raises(EmailAlreadyExistsError):
        users.create_social_user("google", "g-1", "a@example.com", "구글", NOW)

    assert users.get_by_social("google", "g-1") is None
    assert store_backend.social_links() == []
    assert store_backend.user_count() == 1


def test_same_subject_on_different_providers_are_different_accounts(store_backend):
    users = store_backend.users

    google = users.create_social_user("google", "12345", None, "구글", NOW)
    kakao = users.create_social_user("kakao", "12345", None, "카카오", NOW)

    assert google.id != kakao.id


# --- OAUTH_MOCK ---


def test_oauth_mock_full_flow_without_external_calls():
    settings = Settings(secret_key=SECRET, oauth_mock=True)
    backend = MemoryBackend()
    auth = AuthService(backend.users, backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)
    app = create_app(settings, MockRouteProvider(), clock=lambda: NOW, auth=auth)
    client = TestClient(app, base_url=BASE_URL, follow_redirects=False)

    started = client.get("/api/auth/google/start")
    location = started.headers["location"]
    assert location.startswith("/api/auth/google/callback?code=mock-code&state=")  # 제공자 화면 없이 곧바로 콜백
    finished = client.get(location)

    assert auth_result(finished) == "success"
    assert client.get("/api/auth/me").json() == {
        "id": "1",
        "name": "Mock google 사용자",
        "email": "mock.google@example.com",
        "provider": "google",
    }


def test_oauth_mock_rejects_wrong_code():
    with pytest.raises(OAuthError):
        MockOAuthClient("google").fetch_profile("real-code", "v", "/cb")
    assert MockOAuthClient("google").fetch_profile(MOCK_CODE, "v", "/cb").subject == "mock-google-user"


# --- 설정 ---


def test_oauth_settings_from_env_hide_secret():
    settings = Settings.from_env(
        {
            "GOOGLE_CLIENT_ID": "client-id.apps.googleusercontent.com",
            "GOOGLE_CLIENT_SECRET": "very-secret-value",
            "OAUTH_REDIRECT_BASE": "http://localhost:8000/",
            "OAUTH_MOCK": "0",
            "SECRET_KEY": SECRET,
        }
    )

    assert settings.google_client_id == "client-id.apps.googleusercontent.com"
    assert settings.oauth_redirect_base == "http://localhost:8000"  # 끝의 /는 뺀다
    assert settings.oauth_mock is False
    assert "very-secret-value" not in repr(settings)
    clients = create_oauth_clients(settings)
    assert isinstance(clients["google"], GoogleOAuthClient)
    assert "very-secret-value" not in repr(clients)


@pytest.mark.parametrize(
    ("env", "missing"),
    [
        ({"GOOGLE_CLIENT_ID": "id"}, ["GOOGLE_CLIENT_SECRET", "SECRET_KEY", "OAUTH_REDIRECT_BASE"]),
        ({"GOOGLE_CLIENT_SECRET": "s", "SECRET_KEY": "k", "OAUTH_REDIRECT_BASE": "http://localhost:8000"}, ["GOOGLE_CLIENT_ID"]),
        ({"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "s", "OAUTH_REDIRECT_BASE": "http://localhost:8000"}, ["SECRET_KEY"]),
    ],
)
def test_partial_google_settings_name_missing_variables(env, missing, caplog):
    assert create_oauth_clients(Settings.from_env(env)) == {}
    for name in missing:
        assert name in caplog.text
    assert "s" not in caplog.messages[-1].split("환경변수")[1]  # 값은 출력하지 않는다


def test_no_social_settings_means_no_clients():
    assert create_oauth_clients(Settings.from_env({})) == {}


@pytest.mark.parametrize("value", ["localhost:8000", "http://localhost:8000/app", "ftp://localhost", "http://"])
def test_invalid_redirect_base_raises(value):
    with pytest.raises(ValueError, match="OAUTH_REDIRECT_BASE"):
        Settings.from_env({"OAUTH_REDIRECT_BASE": value})


def test_oauth_mock_only_with_memory_store():
    with pytest.raises(ValueError, match="AUTH_STORE=memory"):
        create_oauth_clients(Settings(oauth_mock=True, auth_store="mysql", secret_key=SECRET))
    with pytest.raises(ValueError, match="SECRET_KEY"):
        create_oauth_clients(Settings(oauth_mock=True))
    clients = create_oauth_clients(Settings(oauth_mock=True, secret_key=SECRET))
    assert isinstance(clients["google"], MockOAuthClient)


def test_oauth_mock_overrides_real_google_settings():
    """OAUTH_MOCK=1이면 Google 설정이 있어도 실제 Google을 부르지 않는다."""
    settings = Settings(oauth_mock=True, secret_key=SECRET, google_client_id="id", google_client_secret="s")

    assert isinstance(create_oauth_clients(settings)["google"], MockOAuthClient)


def test_injected_clients_require_secret_key():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        create_app(Settings(), MockRouteProvider(), oauth_clients={"google": FakeOAuthClient()})


# --- state 쿠키 ---


def state_value(**overrides):
    values = {"provider": "google", "state": "s-1", "verifier": "v" * 64, "expires_at": 2_000_000_000}
    values.update(overrides)
    return OAuthState(**values)


def test_state_cookie_round_trip():
    cookie = encode_state_cookie(SECRET, state_value())

    assert decode_state_cookie(SECRET, cookie, "google", "s-1", 1_999_999_999) == state_value()


@pytest.mark.parametrize(
    ("cookie", "provider", "state", "now", "reason"),
    [
        (None, "google", "s-1", 0, "쿠키 없음"),
        ("", "google", "s-1", 0, "쿠키 없음"),
        ("valid", "google", None, 0, "state 없음"),
        ("no-dot", "google", "s-1", 0, "형식 오류"),
        ("한글.서명", "google", "s-1", 0, "형식 오류"),
        ("abc.def", "google", "s-1", 0, "서명 불일치"),
        ("valid", "google", "s-1", 2_000_000_000, "만료"),
        ("valid", "kakao", "s-1", 0, "제공자 불일치"),
        ("valid", "google", "s-2", 0, "state 불일치"),
    ],
)
def test_state_cookie_rejections(cookie, provider, state, now, reason):
    if cookie == "valid":
        cookie = encode_state_cookie(SECRET, state_value())

    with pytest.raises(OAuthStateError, match=reason):
        decode_state_cookie(SECRET, cookie, provider, state, now)


def test_signed_but_malformed_payload_is_rejected():
    import base64
    import hashlib
    import hmac

    body = base64.urlsafe_b64encode(b'{"p":"google"}').rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()

    with pytest.raises(OAuthStateError, match="내용 오류"):
        decode_state_cookie(SECRET, f"{body}.{signature}", "google", "s-1", 0)


def test_used_states_consume_once_and_forget_after_expiry():
    used = UsedStates()
    value = state_value(expires_at=100)

    assert used.consume(value, 50) is True
    assert used.consume(value, 60) is False
    assert used.consume(replace(value, state="s-2"), 60) is True
    assert used.consume(value, 100) is True  # 만료 후에는 기억하지 않는다 (쿠키 자체가 만료로 거부된다)


# --- GoogleOAuthClient (가짜 HTTP 세션) ---


class FakeResponse:
    def __init__(self, status_code=200, body=None, text_body=False):
        self.status_code = status_code
        self._body = body
        self._text_body = text_body

    def json(self):
        if self._text_body:
            raise ValueError("not json")
        return self._body


class FakeSession:
    def __init__(self, token=None, userinfo=None, error=None):
        self.token = token if token is not None else FakeResponse(200, {"access_token": "at-1", "token_type": "Bearer"})
        self.userinfo = userinfo if userinfo is not None else FakeResponse(
            200, {"sub": "1098", "email": "g@example.com", "email_verified": True, "name": "구글"}
        )
        self.error = error
        self.posts = []
        self.gets = []

    def post(self, url, data=None, timeout=None):
        self.posts.append((url, data, timeout))
        if self.error:
            raise self.error
        return self.token

    def get(self, url, headers=None, timeout=None):
        self.gets.append((url, headers, timeout))
        return self.userinfo


def google(session):
    return GoogleOAuthClient("cid.apps.googleusercontent.com", "csecret", session=session)


def test_google_authorization_url_parameters():
    url = google(FakeSession()).authorization_url("st", "ch", "http://localhost:8000/api/auth/google/callback")

    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    assert query == {
        "response_type": "code",
        "client_id": "cid.apps.googleusercontent.com",
        "redirect_uri": "http://localhost:8000/api/auth/google/callback",
        "scope": "openid email profile",
        "state": "st",
        "code_challenge": "ch",
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    assert "csecret" not in url


def test_google_fetch_profile_exchanges_code_with_verifier():
    session = FakeSession()

    profile = google(session).fetch_profile("the-code", "the-verifier", "http://localhost:8000/api/auth/google/callback")

    assert profile == OAuthProfile("google", "1098", "g@example.com", True, "구글")
    (url, data, timeout), = session.posts
    assert url == "https://oauth2.googleapis.com/token"
    assert data == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "client_id": "cid.apps.googleusercontent.com",
        "client_secret": "csecret",
        "redirect_uri": "http://localhost:8000/api/auth/google/callback",
        "code_verifier": "the-verifier",
    }
    assert timeout == 5
    (url, headers, _), = session.gets
    assert url == "https://openidconnect.googleapis.com/v1/userinfo"
    assert headers == {"Authorization": "Bearer at-1"}


@pytest.mark.parametrize(
    ("info", "email", "verified", "name"),
    [
        ({"sub": "1", "email": "a@example.com", "email_verified": "true"}, "a@example.com", True, None),
        ({"sub": "1", "email": "a@example.com", "email_verified": False}, "a@example.com", False, None),
        ({"sub": "1"}, None, False, None),
        ({"sub": "1", "email": 123, "name": ["x"]}, None, False, None),
    ],
)
def test_google_profile_fields(info, email, verified, name):
    profile = google(FakeSession(userinfo=FakeResponse(200, info))).fetch_profile("c", "v", "r")

    assert (profile.email, profile.email_verified, profile.name) == (email, verified, name)


@pytest.mark.parametrize(
    "session",
    [
        FakeSession(token=FakeResponse(400, {"error": "invalid_grant", "error_description": "the-code expired"})),
        FakeSession(token=FakeResponse(200, {"token_type": "Bearer"})),  # access_token 없음
        FakeSession(token=FakeResponse(200, text_body=True)),
        FakeSession(token=FakeResponse(200, ["not", "object"])),
        FakeSession(userinfo=FakeResponse(401, {"error": "invalid_token"})),
        FakeSession(userinfo=FakeResponse(200, {"email": "a@example.com"})),  # sub 없음
        FakeSession(error=requests.ConnectionError("connection refused")),
        FakeSession(error=requests.Timeout("timed out")),
    ],
)
def test_google_failures_raise_oauth_error_without_secrets(session):
    with pytest.raises(OAuthError) as caught:
        google(session).fetch_profile("the-code", "the-verifier", "r")

    message = str(caught.value)
    for secret in ("the-code", "the-verifier", "csecret", "at-1"):
        assert secret not in message


def test_verified_email_helper():
    assert verified_email(make_profile(email=" A@B.com ", verified=True)) == "a@b.com"
    assert verified_email(make_profile(email="a@b.com", verified=False)) is None
    assert verified_email(make_profile(email=None, verified=True)) is None
    assert verified_email(make_profile(email="x" * 300 + "@b.com", verified=True)) is None
