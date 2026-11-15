"""사용자·세션 저장소. 프로토콜과 메모리 구현.

AUTH_STORE=memory(기본)는 서버를 다시 시작하면 사라진다. 개발과 테스트용이다.
AUTH_STORE=mysql은 같은 프로토콜의 MySQL 구현이다 (mysql_stores.py, db/schema.sql의 users, social_accounts, sessions).
메모리 구현은 웹 서버의 스레드풀에서 동시에 불릴 수 있으므로 잠금을 건다.
"""

import threading
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol

from app.auth.errors import EmailAlreadyExistsError, SocialAccountExistsError

LOGIN_PROVIDERS = ("email", "google", "kakao")
SOCIAL_PROVIDERS = ("google", "kakao")


@dataclass(frozen=True)
class User:
    id: int  # DB BIGINT. API에는 문자열로 내보낸다
    email: str | None  # 소문자. 카카오는 없을 수 있다
    nickname: str
    password_hash: str | None = field(default=None, repr=False)  # 소셜 전용 계정은 None
    agreed_at: datetime | None = None
    created_at: datetime | None = None
    last_login_at: datetime | None = None


@dataclass(frozen=True)
class SessionRecord:
    token_hash: str  # 쿠키 값의 SHA-256. 쿠키 원문은 저장하지 않는다
    user_id: int
    login_provider: str  # email | google | kakao. 응답의 provider
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class UserStore(Protocol):
    def create_email_user(self, email: str, password_hash: str, nickname: str, now: datetime) -> User:
        """이메일 가입자를 만든다. 같은 이메일이 있으면 EmailAlreadyExistsError (먼저 조회하지 않는다)."""
        ...

    def get_by_id(self, user_id: int) -> User | None: ...

    def get_by_email(self, email: str) -> User | None: ...

    def get_by_social(self, provider: str, provider_user_id: str) -> User | None:
        """social_accounts의 (provider, provider_user_id)에 연결된 사용자."""
        ...

    def create_social_user(
        self, provider: str, provider_user_id: str, email: str | None, nickname: str, now: datetime
    ) -> User:
        """소셜 가입자(password_hash 없음)와 소셜 연결을 한 트랜잭션으로 만든다. agreed_at은 now.

        같은 소셜 계정이 이미 있으면 SocialAccountExistsError, 같은 이메일이 있으면 EmailAlreadyExistsError.
        어느 쪽이든 아무것도 남기지 않는다 (먼저 조회하지 않고 UNIQUE 위반으로 판단한다).
        """
        ...

    def record_login(self, user_id: int, now: datetime) -> None:
        """last_login_at을 갱신한다."""
        ...


class SessionStore(Protocol):
    def create(self, record: SessionRecord) -> None: ...

    def get(self, token_hash: str) -> SessionRecord | None: ...

    def touch(self, token_hash: str, now: datetime) -> None:
        """last_seen_at을 갱신한다."""
        ...

    def delete(self, token_hash: str) -> None:
        """없어도 오류를 내지 않는다."""
        ...

    def delete_expired(self, now: datetime) -> int:
        """만료된 세션을 지우고 지운 개수를 돌려준다."""
        ...


class MemoryUserStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._users: dict[int, User] = {}
        self._by_email: dict[str, int] = {}
        self._by_social: dict[tuple[str, str], int] = {}
        self._next_id = 1

    def create_email_user(self, email: str, password_hash: str, nickname: str, now: datetime) -> User:
        with self._lock:
            if email in self._by_email:
                raise EmailAlreadyExistsError(email)
            user = User(
                id=self._next_id,
                email=email,
                nickname=nickname,
                password_hash=password_hash,
                agreed_at=now,
                created_at=now,
            )
            self._next_id += 1
            self._users[user.id] = user
            self._by_email[email] = user.id
            return user

    def add_user(self, user: User) -> User:
        """테스트·개발용: 소셜 전용 계정처럼 이메일 가입 경로로 만들 수 없는 사용자를 넣는다."""
        with self._lock:
            if user.email is not None and user.email in self._by_email:
                raise EmailAlreadyExistsError(user.email)
            user = replace(user, id=self._next_id)
            self._next_id += 1
            self._users[user.id] = user
            if user.email is not None:
                self._by_email[user.email] = user.id
            return user

    def get_by_id(self, user_id: int) -> User | None:
        with self._lock:
            return self._users.get(user_id)

    def get_by_email(self, email: str) -> User | None:
        with self._lock:
            user_id = self._by_email.get(email)
            return self._users.get(user_id) if user_id is not None else None

    def get_by_social(self, provider: str, provider_user_id: str) -> User | None:
        with self._lock:
            user_id = self._by_social.get((provider, provider_user_id))
            return self._users.get(user_id) if user_id is not None else None

    def create_social_user(
        self, provider: str, provider_user_id: str, email: str | None, nickname: str, now: datetime
    ) -> User:
        with self._lock:
            if (provider, provider_user_id) in self._by_social:
                raise SocialAccountExistsError(provider)
            if email is not None and email in self._by_email:
                raise EmailAlreadyExistsError(email)
            user = User(id=self._next_id, email=email, nickname=nickname, agreed_at=now, created_at=now)
            self._next_id += 1
            self._users[user.id] = user
            if email is not None:
                self._by_email[email] = user.id
            self._by_social[(provider, provider_user_id)] = user.id
            return user

    def social_links(self) -> list[tuple[str, str, int]]:
        """테스트용: (provider, provider_user_id, user_id) 목록."""
        with self._lock:
            return [(p, pid, uid) for (p, pid), uid in self._by_social.items()]

    def count(self) -> int:
        """테스트용: 사용자 수."""
        with self._lock:
            return len(self._users)

    def record_login(self, user_id: int, now: datetime) -> None:
        with self._lock:
            if user_id in self._users:
                self._users[user_id] = replace(self._users[user_id], last_login_at=now)


class MemorySessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionRecord] = {}

    def create(self, record: SessionRecord) -> None:
        with self._lock:
            self._sessions[record.token_hash] = record

    def get(self, token_hash: str) -> SessionRecord | None:
        with self._lock:
            return self._sessions.get(token_hash)

    def touch(self, token_hash: str, now: datetime) -> None:
        with self._lock:
            if token_hash in self._sessions:
                self._sessions[token_hash] = replace(self._sessions[token_hash], last_seen_at=now)

    def delete(self, token_hash: str) -> None:
        with self._lock:
            self._sessions.pop(token_hash, None)

    def delete_expired(self, now: datetime) -> int:
        with self._lock:
            expired = [key for key, record in self._sessions.items() if record.expires_at <= now]
            for key in expired:
                del self._sessions[key]
            return len(expired)

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
