"""회원 API 테스트 (1단계: 이메일 인증, 메모리 저장소). 외부 API와 DB는 쓰지 않는다.

TestClient는 https://testserver로 띄운다. 세션 쿠키에 Secure가 붙어 있어 http로는 쿠키 저장소가 쿠키를 보내지 않는다.
bcrypt cost는 테스트 속도를 위해 4로 낮춘다. 기본값 12는 따로 확인한다.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated

import bcrypt
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE, optional_user, require_user
from app.api.factory import create_app
from app.auth import (
    AuthService,
    CurrentUser,
    MemorySessionStore,
    MemoryUserStore,
    PasswordHasher,
    RateLimiter,
    User,
    create_auth_service,
    hash_token,
)
from app.config import Settings
from app.departure import MockRouteProvider
from tests.conftest import NOW

BASE_URL = "https://testserver"
PASSWORD = "gilit1234"


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


@dataclass
class Env:
    app: object
    client: TestClient
    users: MemoryUserStore
    sessions: MemorySessionStore
    clock: FakeClock
    monotonic: FakeMonotonic

    def new_client(self, ip: str = "testclient", **kwargs) -> TestClient:
        return TestClient(self.app, base_url=BASE_URL, client=(ip, 50000), **kwargs)

    def me_with(self, token: str):
        return self.new_client(cookies={SESSION_COOKIE: token}).get("/api/auth/me")


def make_env(settings: Settings | None = None) -> Env:
    users, sessions = MemoryUserStore(), MemorySessionStore()
    clock, monotonic = FakeClock(NOW), FakeMonotonic()
    auth = AuthService(
        users,
        sessions,
        PasswordHasher(rounds=4),
        clock=clock,
        login_ip_limiter=RateLimiter(5, 60, clock=monotonic),
        login_email_limiter=RateLimiter(5, 60, clock=monotonic),
        signup_ip_limiter=RateLimiter(10, 3600, clock=monotonic),
    )
    app = create_app(settings or Settings(), MockRouteProvider(), clock=clock, auth=auth)
    return Env(app, TestClient(app, base_url=BASE_URL), users, sessions, clock, monotonic)


@pytest.fixture
def env() -> Env:
    return make_env()


def signup_body(**overrides):
    payload = {"name": "길잇", "email": "user@example.com", "password": PASSWORD, "agreeTerms": True, "agreePrivacy": True}
    payload.update(overrides)
    return payload


def signup(client: TestClient, **overrides):
    return client.post("/api/auth/signup", json=signup_body(**overrides))


def login(client: TestClient, email: str = "user@example.com", password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def set_cookie_header(response) -> str:
    return response.headers.get("set-cookie", "")


# --- 회원가입 ---


def test_signup_returns_user_without_session(env):
    response = signup(env.client, name="  길잇  ", email="  User@Example.COM ")

    assert response.status_code == 201
    assert response.json() == {"id": "1", "name": "길잇", "email": "user@example.com", "provider": "email"}
    assert "set-cookie" not in response.headers  # 가입만 하고 로그인 세션은 만들지 않는다
    assert len(env.sessions) == 0
    assert env.client.get("/api/auth/me").status_code == 401


def test_signup_records_agreement_time(env):
    signup(env.client)

    user = env.users.get_by_email("user@example.com")
    assert user.agreed_at == NOW
    assert user.created_at == NOW


def test_signup_duplicate_email_is_409_case_insensitive(env):
    assert signup(env.client).status_code == 201

    response = signup(env.client, email="USER@example.com", name="다른사람")

    assert response.status_code == 409
    assert response.json() == {"message": "이미 가입된 이메일입니다."}


def test_signup_duplicate_of_social_only_account_is_409(env):
    env.users.add_user(User(id=0, email="kakao@example.com", nickname="카카오사용자"))

    response = signup(env.client, email="kakao@example.com")

    assert response.status_code == 409


NAME_MSG = "이름은 2~20자로 입력해 주세요."
EMAIL_MSG = "올바른 이메일 형식이 아닙니다."
PASSWORD_MSG = "비밀번호는 영문과 숫자를 포함해 8~64자로 입력해 주세요."
AGREE_MSG = "필수 약관에 모두 동의해 주세요."


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": "길"}, NAME_MSG),
        ({"name": "   길   "}, NAME_MSG),  # 공백을 지우면 1자
        ({"name": "가" * 21}, NAME_MSG),
        ({"name": None}, NAME_MSG),
        ({"name": 12345}, NAME_MSG),
        ({"name": "길\n잇"}, NAME_MSG),  # 제어 문자
        ({"name": "길​잇"}, NAME_MSG),  # 제로폭 공백
        ({"email": "not-an-email"}, EMAIL_MSG),
        ({"email": "a@b"}, EMAIL_MSG),
        ({"email": "a b@example.com"}, EMAIL_MSG),
        ({"email": "user@exam\nple.com"}, EMAIL_MSG),  # 앞뒤 공백은 지우지만 중간 줄바꿈은 거부
        ({"email": "a" * 243 + "@example.com"}, EMAIL_MSG),  # 255자
        ({"email": None}, EMAIL_MSG),
        ({"password": "abc1234"}, PASSWORD_MSG),  # 7자
        ({"password": "a1" * 33}, PASSWORD_MSG),  # 66자
        ({"password": "abcdefgh"}, PASSWORD_MSG),  # 숫자 없음
        ({"password": "12345678"}, PASSWORD_MSG),  # 영문 없음
        ({"password": "abcdefg٣"}, PASSWORD_MSG),  # 아라비아 숫자는 숫자로 보지 않는다
        ({"password": "a1" + "가" * 24}, PASSWORD_MSG),  # 26자지만 74바이트 (bcrypt 한계 72바이트)
        ({"password": 12345678}, PASSWORD_MSG),
        ({"agreeTerms": False}, AGREE_MSG),
        ({"agreePrivacy": False}, AGREE_MSG),
        ({"agreeTerms": "true"}, AGREE_MSG),  # 문자열은 동의로 보지 않는다
        ({"agreePrivacy": 1}, AGREE_MSG),
        ({"agreeTerms": None}, AGREE_MSG),
    ],
)
def test_signup_validation_errors_are_400_with_spec_message(env, overrides, message):
    response = signup(env.client, **overrides)

    assert response.status_code == 400
    assert response.json() == {"message": message}
    assert env.users.get_by_email("user@example.com") is None


def test_signup_name_error_is_not_place_name_message(env):
    """공통 오류 변환의 "장소 이름" 문구가 회원가입에 섞이지 않는다."""
    response = env.client.post("/api/auth/signup", json={"email": "user@example.com"})

    assert response.json() == {"message": NAME_MSG}


def test_signup_accepts_boundary_values(env):
    response = signup(env.client, name="길잇", password="a1" + "x" * 62)  # 이름 2자, 비밀번호 64자

    assert response.status_code == 201


def test_signup_checks_fields_in_frontend_order(env):
    response = signup(env.client, name="길", email="bad", password="short", agreeTerms=False)

    assert response.json() == {"message": NAME_MSG}


@pytest.mark.parametrize("content", [b"[1, 2]", b'"text"', b"{not json"])
def test_signup_body_must_be_json_object(env, content):
    response = env.client.post("/api/auth/signup", content=content, headers={"Content-Type": "application/json"})

    assert response.status_code == 400
    assert response.json() == {"message": "요청 본문은 JSON 객체여야 합니다."}


# --- 비밀번호 저장 ---


def test_password_is_stored_as_bcrypt_hash_not_plaintext(env):
    signup(env.client)

    user = env.users.get_by_email("user@example.com")
    assert user.password_hash != PASSWORD
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$2b$04$")
    assert bcrypt.checkpw(PASSWORD.encode(), user.password_hash.encode())
    assert "password_hash" not in repr(user)  # 로그에 찍혀도 해시가 나오지 않는다


def test_signup_response_never_contains_password_or_hash(env):
    text = signup(env.client).text

    assert PASSWORD not in text
    assert "$2b$" not in text
    assert "password" not in text


def test_default_bcrypt_cost_is_12():
    assert PasswordHasher().hash("gilit1234").startswith("$2b$12$")
    assert create_auth_service("memory").hasher.rounds == 12


# --- 로그인 ---


def test_login_sets_session_cookie_and_returns_user(env):
    signup(env.client)

    response = login(env.client, email=" USER@example.com ")

    assert response.status_code == 200
    assert response.json() == {"id": "1", "name": "길잇", "email": "user@example.com", "provider": "email"}
    cookie = set_cookie_header(response)
    attributes = [part.strip().lower() for part in cookie.split(";")]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "httponly" in attributes
    assert "samesite=lax" in attributes
    assert "path=/" in attributes
    assert "secure" in attributes
    assert f"max-age={14 * 24 * 3600}" in attributes
    assert not any(part.startswith("domain=") for part in attributes)
    assert env.users.get_by_email("user@example.com").last_login_at == NOW


def test_me_after_login_returns_same_user(env):
    signup(env.client)
    login(env.client)

    response = env.client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {"id": "1", "name": "길잇", "email": "user@example.com", "provider": "email"}


def test_cookie_secure_can_be_turned_off_for_local_http():
    env = make_env(Settings(cookie_secure=False))
    signup(env.client)

    cookie = set_cookie_header(login(env.client)).lower()

    assert "httponly" in cookie
    assert "secure" not in cookie


def test_session_store_keeps_only_token_hash(env):
    signup(env.client)
    token = login(env.client).cookies[SESSION_COOKIE]

    assert env.sessions.get(token) is None
    record = env.sessions.get(hash_token(token))
    assert record is not None
    assert record.login_provider == "email"
    assert record.expires_at == NOW + timedelta(days=14)


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("user@example.com", "wrong1234"),  # 비밀번호 틀림
        ("nobody@example.com", PASSWORD),  # 계정 없음
        ("kakao@example.com", PASSWORD),  # 소셜 전용 계정 (password_hash 없음)
        ("user@example.com", "a1" + "가" * 40),  # 72바이트를 넘는 비밀번호
    ],
)
def test_login_failures_share_one_401_message(env, email, password):
    signup(env.client)
    env.users.add_user(User(id=0, email="kakao@example.com", nickname="카카오사용자"))

    response = login(env.client, email=email, password=password)

    assert response.status_code == 401
    assert response.json() == {"message": "이메일 또는 비밀번호가 올바르지 않습니다."}
    assert "set-cookie" not in response.headers
    assert len(env.sessions) == 0


@pytest.mark.parametrize("email", ["nobody@example.com", "kakao@example.com"])
def test_login_runs_bcrypt_even_without_password_hash(env, monkeypatch, email):
    """계정이 없거나 소셜 전용이어도 bcrypt 비교를 한 번 해서 응답 시간으로 계정 존재가 드러나지 않게 한다."""
    env.users.add_user(User(id=0, email="kakao@example.com", nickname="카카오사용자"))
    calls = []
    real_checkpw = bcrypt.checkpw
    monkeypatch.setattr("app.auth.passwords.bcrypt.checkpw", lambda pw, h: calls.append(h) or real_checkpw(pw, h))

    login(env.client, email=email)

    assert len(calls) == 1
    assert calls[0].startswith(b"$2b$04$")  # 실제 계정과 같은 cost의 더미 해시


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"email": "user@example.com"}, "비밀번호를 입력해 주세요."),
        ({"email": "user@example.com", "password": ""}, "비밀번호를 입력해 주세요."),
        ({"email": "user@example.com", "password": 1234}, "비밀번호를 입력해 주세요."),
        ({"email": "bad", "password": PASSWORD}, EMAIL_MSG),
        ({"password": PASSWORD}, EMAIL_MSG),
    ],
)
def test_login_validation_errors_are_400(env, body, message):
    response = env.client.post("/api/auth/login", json=body)

    assert response.status_code == 400
    assert response.json() == {"message": message}


# --- 로그아웃·me ---


def test_me_without_session_is_401(env):
    response = env.client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"message": "로그인이 필요합니다."}


def test_me_with_unknown_token_is_401(env):
    assert env.me_with("forged-token").status_code == 401


def test_logout_deletes_session_and_expires_cookie(env):
    signup(env.client)
    token = login(env.client).cookies[SESSION_COOKIE]

    response = env.client.post("/api/auth/logout")

    assert response.status_code == 204
    assert response.content == b""
    cookie = set_cookie_header(response).lower()
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "max-age=0" in cookie
    assert len(env.sessions) == 0
    assert env.client.get("/api/auth/me").status_code == 401
    # 쿠키를 따로 보관해 둔 사람이 다시 보내도 서버 세션이 없으므로 401이다.
    assert env.me_with(token).status_code == 401


def test_logout_without_session_is_204(env):
    assert env.client.post("/api/auth/logout").status_code == 204
    assert env.me_with("whatever").status_code == 401
    assert env.new_client(cookies={SESSION_COOKIE: "whatever"}).post("/api/auth/logout").status_code == 204


# --- 세션 고정 방지·만료 ---


def test_each_login_issues_new_token_and_deletes_previous_session(env):
    signup(env.client)
    first = login(env.client).cookies[SESSION_COOKIE]

    second = login(env.client).cookies[SESSION_COOKIE]  # 같은 브라우저(쿠키 저장소)에서 다시 로그인

    assert first != second
    assert env.me_with(first).status_code == 401
    assert env.me_with(second).status_code == 200
    assert len(env.sessions) == 1


def test_planted_session_cookie_is_not_adopted(env):
    """공격자가 심어 둔 쿠키 값이 로그인 후의 세션 ID가 되지 않는다."""
    signup(env.client)
    planted = "attacker-chosen-session-id"
    victim = env.new_client(cookies={SESSION_COOKIE: planted})

    issued = login(victim).cookies[SESSION_COOKIE]

    assert issued != planted
    assert env.me_with(planted).status_code == 401
    assert env.me_with(issued).status_code == 200


def test_login_from_another_device_keeps_other_sessions(env):
    signup(env.client)
    phone = login(env.new_client()).cookies[SESSION_COOKIE]
    laptop = login(env.new_client()).cookies[SESSION_COOKIE]

    assert env.me_with(phone).status_code == 200
    assert env.me_with(laptop).status_code == 200


def test_session_expires_after_14_days(env):
    signup(env.client)
    token = login(env.client).cookies[SESSION_COOKIE]

    env.clock.now = NOW + timedelta(days=14) - timedelta(seconds=1)
    assert env.me_with(token).status_code == 200

    env.clock.now = NOW + timedelta(days=14)
    assert env.me_with(token).status_code == 401
    assert len(env.sessions) == 0


def test_session_use_does_not_extend_expiry_and_touches_hourly(env):
    signup(env.client)
    token = login(env.client).cookies[SESSION_COOKIE]

    env.clock.now = NOW + timedelta(minutes=30)
    env.me_with(token)
    assert env.sessions.get(hash_token(token)).last_seen_at == NOW  # 1시간 안에는 쓰지 않는다

    env.clock.now = NOW + timedelta(hours=2)
    env.me_with(token)
    record = env.sessions.get(hash_token(token))
    assert record.last_seen_at == NOW + timedelta(hours=2)
    assert record.expires_at == NOW + timedelta(days=14)


# --- 출처 검사 ---


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Referer": "https://evil.example/page"},
        {"Origin": "http://testserver"},  # 같은 호스트라도 scheme이 다르면 다른 출처
    ],
)
def test_unsafe_requests_from_other_origins_are_403(env, headers):
    signup(env.client)

    response = env.client.post("/api/auth/login", json={"email": "user@example.com", "password": PASSWORD}, headers=headers)

    assert response.status_code == 403
    assert response.json() == {"message": "허용되지 않은 출처의 요청입니다."}
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "headers",
    [
        {},  # 브라우저 밖 클라이언트 (Origin, Referer 없음)
        {"Origin": BASE_URL},  # 같은 출처 (개발: http://localhost:8000)
        {"Origin": "http://localhost:5500"},  # CORS_ORIGINS 기본값
        {"Referer": f"{BASE_URL}/pages/search.html"},
    ],
)
def test_unsafe_requests_from_allowed_origins_pass(env, headers):
    signup(env.client)

    response = env.client.post("/api/auth/login", json={"email": "user@example.com", "password": PASSWORD}, headers=headers)

    assert response.status_code == 200


def test_logout_from_other_origin_is_blocked_and_session_survives(env):
    signup(env.client)
    token = login(env.client).cookies[SESSION_COOKIE]

    response = env.client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert env.me_with(token).status_code == 200


def test_origin_check_covers_other_api_posts_but_not_get(env):
    blocked = env.client.post("/api/departure", json={}, headers={"Origin": "https://evil.example"})
    read = env.client.get("/api/auth/me", headers={"Origin": "https://evil.example"})

    assert blocked.status_code == 403
    assert read.status_code == 401  # GET은 출처 검사 대상이 아니다


def test_origin_check_uses_configured_cors_origins():
    env = make_env(Settings(cors_origins=("https://gilit.example.com",)))
    signup(env.client)

    allowed = login(env.new_client(headers={"Origin": "https://gilit.example.com"}))
    default_dev = login(env.new_client(headers={"Origin": "http://localhost:5500"}))

    assert allowed.status_code == 200
    assert default_dev.status_code == 403


# --- 횟수 제한 ---

TOO_MANY = {"message": "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."}


def test_login_is_limited_to_5_per_minute_per_ip(env):
    for i in range(5):
        assert login(env.client, email=f"user{i}@example.com").status_code == 401

    response = login(env.client, email="other@example.com")

    assert response.status_code == 429
    assert response.json() == TOO_MANY
    assert response.headers["retry-after"] == "60"
    # 다른 IP는 영향받지 않는다.
    assert login(env.new_client(ip="10.0.0.2"), email="other@example.com").status_code == 401


def test_login_is_limited_to_5_per_minute_per_email_across_ips(env):
    signup(env.client)
    for i in range(5):
        assert login(env.new_client(ip=f"10.0.0.{i}"), password="wrong1234").status_code == 401

    # 다른 IP에서 맞는 비밀번호로 와도 이 이메일은 막힌다 (비밀번호 대입 방지).
    response = login(env.new_client(ip="10.0.1.1"))

    assert response.status_code == 429
    assert response.json() == TOO_MANY


def test_login_limit_resets_after_window(env):
    signup(env.client)
    for _ in range(5):
        login(env.client, password="wrong1234")
    assert login(env.client).status_code == 429

    env.monotonic.value += 60

    assert login(env.client).status_code == 200


def test_rejected_login_attempts_do_not_extend_the_window(env):
    for _ in range(5):
        login(env.client, password="wrong1234")
    env.monotonic.value += 30
    for _ in range(3):
        assert login(env.client).status_code == 429

    env.monotonic.value += 30  # 처음 시도로부터 60초

    assert login(env.client).status_code == 401


def test_signup_is_limited_to_10_per_hour_per_ip(env):
    for i in range(10):
        assert signup(env.client, email=f"user{i}@example.com").status_code == 201

    response = signup(env.client, email="user10@example.com")

    assert response.status_code == 429
    assert response.json() == TOO_MANY
    assert response.headers["retry-after"] == "3600"
    assert env.users.get_by_email("user10@example.com") is None

    env.monotonic.value += 3600
    assert signup(env.client, email="user10@example.com").status_code == 201


def test_invalid_signup_input_does_not_use_up_the_limit(env):
    for _ in range(20):
        assert signup(env.client, name="길").status_code == 400

    assert signup(env.client).status_code == 201


# --- 다른 API에서 쓰는 로그인 의존성 ---


def add_probe_routes(app):
    @app.get("/api/_probe/required")
    def required(current: Annotated[CurrentUser, Depends(require_user)]):
        return {"id": current.id, "provider": current.login_provider}

    @app.get("/api/_probe/optional")
    def optional(current: Annotated[CurrentUser | None, Depends(optional_user)]):
        return {"id": current.id if current else None}


def test_require_user_and_optional_user_dependencies(env):
    add_probe_routes(env.app)
    anonymous = env.new_client()

    assert anonymous.get("/api/_probe/required").status_code == 401
    assert anonymous.get("/api/_probe/required").json() == {"message": "로그인이 필요합니다."}
    assert anonymous.get("/api/_probe/optional").json() == {"id": None}

    signup(env.client)
    login(env.client)
    assert env.client.get("/api/_probe/required").json() == {"id": 1, "provider": "email"}
    assert env.client.get("/api/_probe/optional").json() == {"id": 1}


# --- 설정 ---


def test_auth_settings_defaults():
    settings = Settings.from_env({})

    assert settings.auth_store == "memory"
    assert settings.cookie_secure is True
    assert settings.secret_key is None


def test_auth_settings_from_env():
    settings = Settings.from_env({"AUTH_STORE": " MySQL ", "COOKIE_SECURE": "false", "SECRET_KEY": "s3cr3t-value"})

    assert settings.auth_store == "mysql"
    assert settings.cookie_secure is False
    assert settings.secret_key == "s3cr3t-value"
    assert "s3cr3t-value" not in repr(settings)


@pytest.mark.parametrize(("env", "name"), [({"AUTH_STORE": "redis"}, "AUTH_STORE"), ({"COOKIE_SECURE": "maybe"}, "COOKIE_SECURE")])
def test_invalid_auth_settings_raise(env, name):
    with pytest.raises(ValueError, match=name):
        Settings.from_env(env)


def test_mysql_store_is_not_available_yet():
    with pytest.raises(ValueError, match="2단계"):
        create_app(Settings(auth_store="mysql"), MockRouteProvider())


def test_app_from_env_uses_memory_store_by_default():
    app = create_app(Settings(), MockRouteProvider())

    assert isinstance(app.state.auth.users, MemoryUserStore)
    assert isinstance(app.state.auth.sessions, MemorySessionStore)
