"""카카오 로그인(4단계) 테스트. 가짜 OAuthClient·가짜 HTTP 세션을 쓰고 실제 카카오는 부르지 않는다.

웹 흐름은 3단계 공용 라우트(/api/auth/{provider}/start·callback)를 그대로 쓴다.
store_backend fixture로 메모리와 MySQL(mysql_live)에서 같은 테스트를 돌린다.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE
from app.api.factory import create_app
from app.api.oauth import OAUTH_COOKIE
from app.auth import AuthService, OAuthError, OAuthProfile, PasswordHasher
from app.auth.oauth import MOCK_CODE, KakaoOAuthClient, MockOAuthClient
from app.config import Settings, create_oauth_clients
from app.departure import MockRouteProvider
from tests.auth_backends import MemoryBackend
from tests.conftest import NOW
from tests.test_oauth import (
    BASE_URL,
    SECRET,
    FakeClock,
    FakeOAuthClient,
    auth_result,
    callback,
    make_profile,
    set_cookies,
    start,
)


def kakao_profile(subject="4001234567", email=None, verified=False, name="카카오친구"):
    return make_profile(subject=subject, email=email, verified=verified, name=name, provider="kakao")


@dataclass
class KEnv:
    app: object
    client: TestClient
    backend: object
    clock: FakeClock
    google: FakeOAuthClient
    kakao: FakeOAuthClient

    def new_client(self, **kwargs) -> TestClient:
        return TestClient(self.app, base_url=BASE_URL, follow_redirects=False, **kwargs)


def make_env(backend=None, kakao_profile_=None, google_profile=None, kakao_error=None) -> KEnv:
    backend = backend or MemoryBackend()
    clock = FakeClock(NOW)
    google = FakeOAuthClient("google", profile=google_profile)
    kakao = FakeOAuthClient("kakao", profile=kakao_profile_ or kakao_profile(), error=kakao_error)
    auth = AuthService(backend.users, backend.sessions, PasswordHasher(rounds=4), clock=clock)
    app = create_app(
        Settings(secret_key=SECRET), MockRouteProvider(), clock=clock, auth=auth, oauth_clients={"google": google, "kakao": kakao}
    )
    return KEnv(app, TestClient(app, base_url=BASE_URL, follow_redirects=False), backend, clock, google, kakao)


@pytest.fixture
def env(store_backend) -> KEnv:
    return make_env(store_backend)


def login(env: KEnv, provider="kakao", client: TestClient | None = None):
    client = client or env.client
    _, state = start(client, provider)
    return callback(client, provider, code=f"{provider}-code", state=state)


def me(client: TestClient):
    return client.get("/api/auth/me")


# --- 첫 가입 ---


def test_kakao_first_login_without_email_creates_account(env):
    response = login(env)

    assert auth_result(response) == "success"
    assert "max-age=0" in set_cookies(response)[OAUTH_COOKIE]
    body = me(env.client).json()
    assert body["provider"] == "kakao"
    assert body["email"] is None
    assert body["name"] == "카카오친구"
    user = env.backend.users.get_by_id(int(body["id"]))
    assert (user.password_hash, user.agreed_at) == (None, NOW)
    assert env.backend.social_links() == [("kakao", "4001234567", user.id)]


def test_kakao_first_login_with_verified_email_stores_email(store_backend):
    env = make_env(store_backend, kakao_profile(email="Friend@Kakao.com", verified=True))

    assert auth_result(login(env)) == "success"

    assert me(env.client).json()["email"] == "friend@kakao.com"


def test_kakao_unverified_email_is_not_stored(store_backend):
    env = make_env(store_backend, kakao_profile(email="friend@kakao.com", verified=False))

    assert auth_result(login(env)) == "success"

    assert me(env.client).json()["email"] is None
    assert env.backend.users.get_by_email("friend@kakao.com") is None


def test_kakao_nickname_missing_uses_default(store_backend):
    env = make_env(store_backend, kakao_profile(name=None))

    login(env)

    assert me(env.client).json()["name"] == "길잇 사용자"


def test_kakao_returning_user_gets_same_account(env):
    login(env)
    first = me(env.client).json()["id"]
    env.kakao.profile = kakao_profile(name="바뀐닉네임")
    other_browser = env.new_client()

    assert auth_result(login(env, client=other_browser)) == "success"

    again = me(other_browser).json()
    assert again["id"] == first
    assert again["name"] == "카카오친구"  # 제공자 쪽 변경은 반영하지 않는다
    assert env.backend.user_count() == 1


# --- 이메일 충돌 ---


def test_kakao_verified_email_of_email_account_is_email_exists(env):
    body = {"name": "이메일가입", "email": "friend@kakao.com", "password": "gilit1234", "agreeTerms": True, "agreePrivacy": True}
    assert env.new_client().post("/api/auth/signup", json=body).status_code == 201
    env.kakao.profile = kakao_profile(email="friend@kakao.com", verified=True)

    response = login(env)

    assert auth_result(response) == "email_exists"
    assert SESSION_COOKIE not in set_cookies(response)
    assert env.backend.social_links() == []
    assert env.backend.user_count() == 1


@pytest.mark.parametrize("first", ["google", "kakao"])
def test_google_and_kakao_with_same_verified_email_are_not_linked(env, first):
    """같은 사람이어도 이메일만 보고 계정을 합치지 않는다. 먼저 가입한 쪽만 계정이 생기고 나중 쪽은 email_exists."""
    env.google.profile = make_profile(subject="g-1", email="same@example.com", verified=True)
    env.kakao.profile = kakao_profile(subject="k-1", email="SAME@example.com", verified=True)
    second = "kakao" if first == "google" else "google"

    assert auth_result(login(env, first)) == "success"
    owner = me(env.client).json()
    later = env.new_client()
    response = login(env, second, client=later)

    assert auth_result(response) == "email_exists"
    assert me(later).status_code == 401
    assert owner["provider"] == first
    assert [link[0] for link in env.backend.social_links()] == [first]
    assert env.backend.user_count() == 1
    # 먼저 가입한 쪽은 계속 그 방법으로 로그인된다.
    assert auth_result(login(env, first, client=env.new_client())) == "success"


def test_kakao_unverified_email_same_as_google_account_creates_separate_account(env):
    env.google.profile = make_profile(subject="g-1", email="same@example.com", verified=True)
    env.kakao.profile = kakao_profile(subject="k-1", email="same@example.com", verified=False)
    login(env, "google")
    google_id = me(env.client).json()["id"]
    kakao_browser = env.new_client()

    assert auth_result(login(env, "kakao", client=kakao_browser)) == "success"

    kakao_user = me(kakao_browser).json()
    assert kakao_user["id"] != google_id
    assert kakao_user["email"] is None
    assert env.backend.user_count() == 2


# --- 취소·검사 ---


def test_kakao_cancel_is_cancelled(env):
    start(env.client, "kakao")

    response = callback(env.client, "kakao", error="access_denied", error_description="User denied access")

    assert auth_result(response) == "cancelled"
    assert "max-age=0" in set_cookies(response)[OAUTH_COOKIE]
    assert env.kakao.fetch_calls == []


def test_kakao_forged_state_is_rejected(env):
    start(env.client, "kakao")

    response = callback(env.client, "kakao", code="kakao-code", state="forged")

    assert auth_result(response) == "failed"
    assert env.kakao.fetch_calls == []
    assert env.backend.user_count() == 0


def test_google_state_cannot_be_used_on_kakao_callback(env):
    """구글로 시작한 state 쿠키를 카카오 콜백에 쓸 수 없다 (provider 검사)."""
    _, google_state = start(env.client, "google")

    response = callback(env.client, "kakao", code="kakao-code", state=google_state)

    assert auth_result(response) == "failed"
    assert env.kakao.fetch_calls == [] and env.google.fetch_calls == []


def test_kakao_token_exchange_failure_is_failed(store_backend):
    env = make_env(store_backend, kakao_error=OAuthError("카카오 토큰 교환 실패: HTTP 401"))

    assert auth_result(login(env)) == "failed"
    assert env.backend.user_count() == 0


def test_kakao_start_passes_state_and_redirect_uri(env):
    response, state = start(env.client, "kakao")

    (sent_state, _challenge, redirect_uri), = env.kakao.authorize_calls
    assert sent_state == state
    assert redirect_uri == "/api/auth/kakao/callback"  # OAUTH_REDIRECT_BASE가 없으면 상대 경로
    assert response.headers["location"].startswith("https://provider.example/authorize?")


@pytest.mark.parametrize("email", [None, "race@kakao.com"])
def test_concurrent_kakao_first_logins_create_one_account(store_backend, email):
    auth = AuthService(store_backend.users, store_backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)
    profile = kakao_profile(subject="race-kakao", email=email, verified=email is not None)
    workers = 8
    barrier = threading.Barrier(workers)

    def attempt(_):
        barrier.wait()
        return auth.social_login(profile, previous_token=None).current.user.id

    with ThreadPoolExecutor(workers) as pool:
        ids = list(pool.map(attempt, range(workers)))

    assert len(set(ids)) == 1
    assert store_backend.user_count() == 1
    assert store_backend.social_links() == [("kakao", "race-kakao", ids[0])]


# --- OAUTH_MOCK ---


def test_oauth_mock_kakao_flow_creates_account_without_email():
    backend = MemoryBackend()
    auth = AuthService(backend.users, backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)
    app = create_app(Settings(secret_key=SECRET, oauth_mock=True), MockRouteProvider(), clock=lambda: NOW, auth=auth)
    client = TestClient(app, base_url=BASE_URL, follow_redirects=False)

    location = client.get("/api/auth/kakao/start").headers["location"]
    assert location.startswith("/api/auth/kakao/callback?code=mock-code&state=")
    assert auth_result(client.get(location)) == "success"

    assert me(client).json() == {"id": "1", "name": "Mock kakao 사용자", "email": None, "provider": "kakao"}


def test_oauth_mock_has_both_providers():
    clients = create_oauth_clients(Settings(oauth_mock=True, secret_key=SECRET))

    assert set(clients) == {"google", "kakao"}
    assert all(isinstance(c, MockOAuthClient) for c in clients.values())
    assert clients["kakao"].fetch_profile(MOCK_CODE, "v", "r").email is None


# --- 설정 ---


def test_kakao_settings_create_client_and_hide_secret():
    settings = Settings.from_env(
        {
            "KAKAO_LOGIN_CLIENT_ID": "rest-api-key",
            "KAKAO_LOGIN_CLIENT_SECRET": "kakao-secret-value",
            "SECRET_KEY": SECRET,
            "OAUTH_REDIRECT_BASE": "http://localhost:8000",
        }
    )

    clients = create_oauth_clients(settings)

    assert set(clients) == {"kakao"}
    assert isinstance(clients["kakao"], KakaoOAuthClient)
    assert "kakao-secret-value" not in repr(settings)
    assert "kakao-secret-value" not in repr(clients)


def test_google_and_kakao_can_be_configured_together():
    settings = Settings.from_env(
        {
            "GOOGLE_CLIENT_ID": "gid",
            "GOOGLE_CLIENT_SECRET": "gsecret",
            "KAKAO_LOGIN_CLIENT_ID": "kid",
            "KAKAO_LOGIN_CLIENT_SECRET": "ksecret",
            "SECRET_KEY": SECRET,
            "OAUTH_REDIRECT_BASE": "http://localhost:8000",
        }
    )

    assert set(create_oauth_clients(settings)) == {"google", "kakao"}


@pytest.mark.parametrize(
    ("env", "missing", "present"),
    [
        ({"KAKAO_LOGIN_CLIENT_ID": "kid"}, ["KAKAO_LOGIN_CLIENT_SECRET", "SECRET_KEY", "OAUTH_REDIRECT_BASE"], []),
        (
            {"KAKAO_LOGIN_CLIENT_SECRET": "ksecret", "SECRET_KEY": "k", "OAUTH_REDIRECT_BASE": "http://localhost:8000"},
            ["KAKAO_LOGIN_CLIENT_ID"],
            ["KAKAO_LOGIN_CLIENT_SECRET", "SECRET_KEY"],
        ),
    ],
)
def test_partial_kakao_settings_name_missing_variables_only(env, missing, present, caplog):
    assert create_oauth_clients(Settings.from_env(env)) == {}
    message = caplog.messages[-1]
    assert message.startswith("카카오 로그인 비활성화:")
    for name in missing:
        assert name in message
    for name in present:
        assert name not in message
    assert "ksecret" not in message and "kid" not in message.replace("KAKAO_LOGIN_CLIENT_ID", "")


def test_kakao_login_keys_are_separate_from_route_key():
    """길찾기용 KAKAO_REST_API_KEY만 있으면 카카오 로그인은 켜지지 않는다."""
    assert create_oauth_clients(Settings.from_env({"KAKAO_REST_API_KEY": "route-key", "SECRET_KEY": SECRET})) == {}


# --- KakaoOAuthClient (가짜 HTTP 세션) ---


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


USER_ME = {
    "id": 4001234567,
    "connected_at": "2026-11-15T01:00:00Z",
    "kakao_account": {
        "profile_nickname_needs_agreement": False,
        "profile": {"nickname": "카카오친구", "is_default_nickname": False},
        "email_needs_agreement": False,
        "is_email_valid": True,
        "is_email_verified": True,
        "email": "friend@kakao.com",
    },
    "properties": {"nickname": "옛날닉네임"},
}


class KakaoSession:
    def __init__(self, token=None, user=None, error=None):
        self.token = token or FakeResponse(200, {"token_type": "bearer", "access_token": "kakao-at", "expires_in": 43199})
        self.user = user or FakeResponse(200, USER_ME)
        self.error = error
        self.posts, self.gets = [], []

    def post(self, url, data=None, timeout=None, headers=None):
        self.posts.append((url, data, timeout, headers))
        if self.error:
            raise self.error
        return self.token

    def get(self, url, headers=None, timeout=None):
        self.gets.append((url, headers, timeout))
        return self.user


def kakao_client(session):
    return KakaoOAuthClient("rest-api-key", "kakao-secret", session=session)


def test_kakao_authorization_url_has_state_but_no_pkce():
    url = kakao_client(KakaoSession()).authorization_url("st", "challenge", "http://localhost:8000/api/auth/kakao/callback")

    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://kauth.kakao.com/oauth/authorize"
    assert query == {
        "response_type": "code",
        "client_id": "rest-api-key",
        "redirect_uri": "http://localhost:8000/api/auth/kakao/callback",
        "state": "st",
    }
    assert "kakao-secret" not in url


def test_kakao_fetch_profile_exchanges_code_with_client_secret():
    session = KakaoSession()

    profile = kakao_client(session).fetch_profile("the-code", "unused-verifier", "http://localhost:8000/api/auth/kakao/callback")

    assert profile == OAuthProfile("kakao", "4001234567", "friend@kakao.com", True, "카카오친구")
    (url, data, timeout, headers), = session.posts
    assert url == "https://kauth.kakao.com/oauth/token"
    assert data == {
        "grant_type": "authorization_code",
        "client_id": "rest-api-key",
        "client_secret": "kakao-secret",
        "redirect_uri": "http://localhost:8000/api/auth/kakao/callback",
        "code": "the-code",
    }
    assert "code_verifier" not in data
    assert headers == {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
    assert timeout == 5
    (url, headers, _), = session.gets
    assert url == "https://kapi.kakao.com/v2/user/me"
    assert headers == {"Authorization": "Bearer kakao-at", "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}


@pytest.mark.parametrize(
    ("account", "email", "verified"),
    [
        ({"email": "a@kakao.com", "is_email_valid": True, "is_email_verified": True}, "a@kakao.com", True),
        ({"email": "a@kakao.com", "is_email_valid": False, "is_email_verified": True}, "a@kakao.com", False),  # 만료된 이메일
        ({"email": "a@kakao.com", "is_email_valid": True, "is_email_verified": False}, "a@kakao.com", False),
        ({"email": "a@kakao.com", "is_email_valid": "true", "is_email_verified": "true"}, "a@kakao.com", False),  # 불리언만 인정
        ({"email_needs_agreement": True}, None, False),  # 이메일 동의 안 함
        ({}, None, False),
    ],
)
def test_kakao_email_is_verified_only_when_valid_and_verified(account, email, verified):
    profile = KakaoOAuthClient.profile_from({"id": 1, "kakao_account": account})

    assert (profile.email, profile.email_verified) == (email, verified)


@pytest.mark.parametrize(
    ("info", "name"),
    [
        ({"id": 1, "kakao_account": {"profile": {"nickname": "닉"}}}, "닉"),
        ({"id": 1, "properties": {"nickname": "폐기예정"}}, None),  # properties.nickname은 쓰지 않는다
        ({"id": 1, "kakao_account": {"profile_nickname_needs_agreement": True}}, None),
        ({"id": 1, "kakao_account": "broken"}, None),
    ],
)
def test_kakao_nickname_comes_from_kakao_account_profile(info, name):
    assert KakaoOAuthClient.profile_from(info).name == name


@pytest.mark.parametrize("subject", [4001234567, "4001234567"])
def test_kakao_id_becomes_string(subject):
    assert KakaoOAuthClient.profile_from({"id": subject}).subject == "4001234567"


@pytest.mark.parametrize("info", [{}, {"id": None}, {"id": ""}, {"id": True}, {"id": [1]}])
def test_kakao_profile_without_id_is_error(info):
    with pytest.raises(OAuthError, match="회원번호"):
        KakaoOAuthClient.profile_from(info)


@pytest.mark.parametrize(
    "session",
    [
        KakaoSession(token=FakeResponse(400, {"error": "invalid_grant", "error_description": "the-code"})),
        KakaoSession(token=FakeResponse(401, {"error": "invalid_client", "error_code": "KOE010"})),  # client_secret 틀림
        KakaoSession(token=FakeResponse(200, {"token_type": "bearer"})),
        KakaoSession(token=FakeResponse(200, ValueError("not json"))),
        KakaoSession(user=FakeResponse(401, {"msg": "this access token does not exist", "code": -401})),
        KakaoSession(user=FakeResponse(200, {"kakao_account": {}})),
        KakaoSession(error=requests.ConnectionError("refused")),
        KakaoSession(error=requests.Timeout("timeout")),
    ],
)
def test_kakao_failures_raise_oauth_error_without_secrets(session):
    with pytest.raises(OAuthError) as caught:
        kakao_client(session).fetch_profile("the-code", "v", "r")

    message = str(caught.value)
    assert message.startswith("카카오")
    for secret in ("the-code", "kakao-secret", "kakao-at", "rest-api-key"):
        assert secret not in message
