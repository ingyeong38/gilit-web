"""이메일·소셜 인증과 서버 세션.

세션 쿠키 값은 무작위 토큰이고, 저장소에는 그 SHA-256 해시만 둔다. 저장소가 유출돼도 쿠키를 만들 수 없다.
로그인할 때마다 새 토큰을 발급하고, 요청에 실려 온 이전 세션은 지운다 (세션 고정 방지).
"""

import hashlib
import secrets
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.auth.errors import (
    EMAIL_TAKEN,
    LOGIN_FAILED,
    TOO_MANY_REQUESTS,
    AuthError,
    EmailAlreadyExistsError,
    SocialAccountExistsError,
    SocialEmailConflictError,
)
from app.auth.oauth import OAuthProfile
from app.auth.passwords import PasswordHasher
from app.auth.rate_limit import RateLimiter, retry_after_header
from app.auth.stores import MemorySessionStore, MemoryUserStore, SessionRecord, SessionStore, User, UserStore
from app.auth.validation import NAME_MAX, normalize_email, validate_login, validate_signup
from app.departure import KST

if TYPE_CHECKING:
    from app.db import ConnectionPool, MySQLConfig

SESSION_TTL = timedelta(days=14)  # 고정 만료. 사용해도 늘어나지 않는다
SESSION_TOUCH_INTERVAL = timedelta(hours=1)  # last_seen_at은 이 간격보다 자주 쓰지 않는다
TOKEN_BYTES = 32

AUTH_STORES = ("memory", "mysql")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


@dataclass(frozen=True)
class CurrentUser:
    """로그인한 사용자와 이번 세션의 로그인 방식. 즐겨찾기·기록 API는 user.id를 쓴다."""

    user: User
    login_provider: str

    @property
    def id(self) -> int:
        return self.user.id


@dataclass(frozen=True)
class LoginResult:
    current: CurrentUser
    token: str  # 쿠키에 넣을 원문. 저장하지 않는다


class AuthService:
    def __init__(
        self,
        users: UserStore,
        sessions: SessionStore,
        hasher: PasswordHasher | None = None,
        clock: Callable[[], datetime] | None = None,
        login_ip_limiter: RateLimiter | None = None,
        login_email_limiter: RateLimiter | None = None,
        signup_ip_limiter: RateLimiter | None = None,
    ) -> None:
        self.users = users
        self.sessions = sessions
        self.hasher = hasher or PasswordHasher()
        self._clock = clock or (lambda: datetime.now(KST))
        # docs/api-spec.md 보안 규칙: 로그인 IP·이메일별 분당 5회, 가입 IP별 시간당 10회
        self.login_ip_limiter = login_ip_limiter or RateLimiter(5, 60)
        self.login_email_limiter = login_email_limiter or RateLimiter(5, 60)
        self.signup_ip_limiter = signup_ip_limiter or RateLimiter(10, 3600)

    def now(self) -> datetime:
        return self._clock()

    # --- 가입·로그인 ---

    def signup(self, payload: dict[str, Any], client_ip: str) -> User:
        data = validate_signup(payload)
        _check_limit(self.signup_ip_limiter, client_ip)
        password_hash = self.hasher.hash(data.password)
        try:
            return self.users.create_email_user(data.email, password_hash, data.name, self.now())
        except EmailAlreadyExistsError:
            raise AuthError(409, EMAIL_TAKEN) from None

    def login(self, payload: dict[str, Any], client_ip: str, previous_token: str | None) -> LoginResult:
        data = validate_login(payload)
        _check_limit(self.login_ip_limiter, client_ip)
        _check_limit(self.login_email_limiter, data.email)

        user = self.users.get_by_email(data.email)
        # 계정 없음, 소셜 전용(password_hash None), 비밀번호 틀림을 같은 응답·비슷한 시간으로 처리한다.
        valid = self.hasher.verify(data.password, user.password_hash if user else None)
        if user is None or not valid:
            raise AuthError(401, LOGIN_FAILED)
        return self._start_session(user, "email", previous_token)

    def social_login(self, profile: OAuthProfile, previous_token: str | None) -> LoginResult:
        """소셜 프로필로 로그인한다. 처음이면 가입시킨다 (설계 3-2).

        - (provider, subject)가 연결돼 있으면 그 계정. 제공자 쪽 이메일·이름이 바뀌어도 DB는 바꾸지 않는다.
        - 처음 + 검증된 이메일이 기존 계정과 겹치면 SocialEmailConflictError (계정 생성·연결 없음).
        - 처음 + 이메일 없음·미검증이면 email NULL로, 검증된 새 이메일이면 그 이메일로 가입한다.
        - 동시 첫 로그인으로 UNIQUE 위반이 나면 다시 조회해서 먼저 만들어진 계정으로 로그인한다.
        """
        provider, subject = profile.provider, profile.subject
        user = self.users.get_by_social(provider, subject) or self._social_signup(profile)
        return self._start_session(user, provider, previous_token)

    def _social_signup(self, profile: OAuthProfile) -> User:
        provider, subject = profile.provider, profile.subject
        email = verified_email(profile)
        if email is not None and self.users.get_by_email(email) is not None:
            # 그 이메일 계정이 같은 소셜 계정의 동시 첫 로그인이 방금 만든 것일 수 있다. 그때만 로그인시킨다.
            return self._linked_or_conflict(provider, subject)
        try:
            return self.users.create_social_user(provider, subject, email, social_nickname(profile.name), self.now())
        except (SocialAccountExistsError, EmailAlreadyExistsError):
            # 동시 첫 로그인이 먼저 가입시켰거나(같은 이메일이면 이메일 위반이 먼저 걸린다),
            # 그사이 다른 사람이 그 이메일로 가입했다. 트랜잭션이 rollback돼 남은 행은 없다.
            return self._linked_or_conflict(provider, subject)

    def _linked_or_conflict(self, provider: str, subject: str) -> User:
        user = self.users.get_by_social(provider, subject)
        if user is None:
            raise SocialEmailConflictError(provider)
        return user

    def _start_session(self, user: User, login_provider: str, previous_token: str | None) -> LoginResult:
        """새 세션을 만든다. 요청에 실려 온 이전 세션은 지우고(세션 고정 방지) 만료 세션을 정리한다."""
        now = self.now()
        if previous_token:
            self.sessions.delete(hash_token(previous_token))
        self.sessions.delete_expired(now)
        token = new_token()
        self.sessions.create(
            SessionRecord(
                token_hash=hash_token(token),
                user_id=user.id,
                login_provider=login_provider,
                created_at=now,
                last_seen_at=now,
                expires_at=now + SESSION_TTL,
            )
        )
        self.users.record_login(user.id, now)
        return LoginResult(CurrentUser(user, login_provider), token)

    def logout(self, token: str | None) -> None:
        if token:
            self.sessions.delete(hash_token(token))

    # --- 세션 확인 ---

    def authenticate(self, token: str | None) -> CurrentUser | None:
        """쿠키 값으로 사용자를 찾는다. 없거나 만료됐거나 사용자가 지워졌으면 None."""
        if not token:
            return None
        token_hash = hash_token(token)
        record = self.sessions.get(token_hash)
        if record is None:
            return None
        now = self.now()
        if record.expires_at <= now:
            self.sessions.delete(token_hash)
            return None
        user = self.users.get_by_id(record.user_id)
        if user is None:
            self.sessions.delete(token_hash)
            return None
        if now - record.last_seen_at >= SESSION_TOUCH_INTERVAL:
            self.sessions.touch(token_hash, now)
        return CurrentUser(user, record.login_provider)


DEFAULT_NICKNAME = "길잇 사용자"


def social_nickname(name: str | None) -> str:
    """제공자 이름을 닉네임으로. 제어·서식 문자를 빼고 20자로 자른다. 비면 "길잇 사용자"."""
    if not isinstance(name, str):
        return DEFAULT_NICKNAME
    cleaned = "".join(ch for ch in unicodedata.normalize("NFC", name) if not unicodedata.category(ch).startswith("C"))
    cleaned = " ".join(cleaned.split())  # 연속 공백 정리
    return cleaned[:NAME_MAX].strip() or DEFAULT_NICKNAME


def verified_email(profile: OAuthProfile) -> str | None:
    """제공자가 검증했다고 알려 준 이메일만 소문자로 돌려준다. 없거나 미검증이거나 형식이 틀리면 None."""
    if not profile.email_verified or not profile.email:
        return None
    try:
        return normalize_email(profile.email)
    except AuthError:
        return None


def _check_limit(limiter: RateLimiter, key: str) -> None:
    retry_after = limiter.hit(key)
    if retry_after is not None:
        raise AuthError(429, TOO_MANY_REQUESTS, headers=retry_after_header(retry_after))


def create_auth_service(
    store: str,
    clock: Callable[[], datetime] | None = None,
    mysql: "MySQLConfig | None" = None,
    pool: "ConnectionPool | None" = None,
) -> AuthService:
    """AUTH_STORE에 맞는 저장소로 AuthService를 만든다.

    mysql이면 연결 풀(pool)을 받아 함께 쓴다. 웹 앱은 factory가 풀을 하나 만들어 회원·즐겨찾기 저장소에 나눠 준다.
    pool을 주지 않으면 접속 정보(mysql)로 새로 만든다 (스크립트·테스트용).
    """
    if store == "memory":
        return AuthService(MemoryUserStore(), MemorySessionStore(), clock=clock)
    if store == "mysql":
        # pymysql은 mysql을 쓸 때만 불러온다.
        from app.auth.mysql_stores import MySQLSessionStore, MySQLUserStore
        from app.db import ConnectionPool

        if pool is None:
            if mysql is None:
                raise ValueError("AUTH_STORE=mysql에는 DB 접속 정보(DB_HOST, DB_NAME, DB_USER, DB_PASSWORD)가 필요합니다.")
            pool = ConnectionPool(mysql)
        return AuthService(MySQLUserStore(pool), MySQLSessionStore(pool), clock=clock)
    raise ValueError(f"AUTH_STORE는 {', '.join(AUTH_STORES)} 중 하나여야 합니다: {store}")
