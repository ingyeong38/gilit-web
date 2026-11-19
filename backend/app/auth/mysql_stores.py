"""UserStore / SessionStore의 MySQL 구현 (AUTH_STORE=mysql). 테이블은 db/schema.sql의 users, sessions.

이메일 중복은 먼저 조회하지 않고 INSERT의 UNIQUE 위반(1062)으로 판단한다. 같은 이메일로 동시에 가입해도 하나만 성공한다.
소셜 가입은 users와 social_accounts를 한 트랜잭션으로 넣는다. 위반된 인덱스 이름으로 이메일·소셜 중복을 구분한다.
"""

from datetime import datetime

from app.auth.errors import EmailAlreadyExistsError, SocialAccountExistsError
from app.auth.stores import SessionRecord, User
from app.db import ConnectionPool, from_db, is_duplicate_entry, to_db

USER_COLUMNS = "id, email, password_hash, nickname, agreed_at, created_at, last_login_at"
USER_COLUMNS_U = ", ".join(f"u.{column.strip()}" for column in USER_COLUMNS.split(","))
SESSION_COLUMNS = "token_hash, user_id, login_provider, created_at, last_seen_at, expires_at"


def _user(row: dict | None) -> User | None:
    if row is None:
        return None
    return User(
        id=int(row["id"]),
        email=row["email"],
        nickname=row["nickname"],
        password_hash=row["password_hash"],
        agreed_at=from_db(row["agreed_at"]),
        created_at=from_db(row["created_at"]),
        last_login_at=from_db(row["last_login_at"]),
    )


def _session(row: dict | None) -> SessionRecord | None:
    if row is None:
        return None
    return SessionRecord(
        token_hash=row["token_hash"],
        user_id=int(row["user_id"]),
        login_provider=row["login_provider"],
        created_at=from_db(row["created_at"]),
        last_seen_at=from_db(row["last_seen_at"]),
        expires_at=from_db(row["expires_at"]),
    )


class MySQLUserStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def create_email_user(self, email: str, password_hash: str, nickname: str, now: datetime) -> User:
        at = to_db(now)
        try:
            with self.pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (email, password_hash, nickname, agreed_at, created_at) VALUES (%s, %s, %s, %s, %s)",
                    (email, password_hash, nickname, at, at),
                )
                user_id = cur.lastrowid
        except Exception as error:
            if is_duplicate_entry(error):
                raise EmailAlreadyExistsError(email) from None
            raise
        return User(
            id=int(user_id),
            email=email,
            nickname=nickname,
            password_hash=password_hash,
            agreed_at=from_db(at),
            created_at=from_db(at),
        )

    def get_by_id(self, user_id: int) -> User | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = %s", (user_id,))
            return _user(cur.fetchone())

    def get_by_email(self, email: str) -> User | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {USER_COLUMNS} FROM users WHERE email = %s", (email,))
            return _user(cur.fetchone())

    def get_by_social(self, provider: str, provider_user_id: str) -> User | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {USER_COLUMNS_U} FROM users u JOIN social_accounts s ON s.user_id = u.id "
                "WHERE s.provider = %s AND s.provider_user_id = %s",
                (provider, provider_user_id),
            )
            return _user(cur.fetchone())

    def create_social_user(
        self, provider: str, provider_user_id: str, email: str | None, nickname: str, now: datetime
    ) -> User:
        at = to_db(now)
        try:
            # 한 연결의 한 트랜잭션. 두 번째 INSERT가 실패하면 connection()이 rollback해 users 행도 남지 않는다.
            with self.pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (email, password_hash, nickname, agreed_at, created_at) VALUES (%s, NULL, %s, %s, %s)",
                    (email, nickname, at, at),
                )
                user_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO social_accounts (user_id, provider, provider_user_id, created_at) VALUES (%s, %s, %s, %s)",
                    (user_id, provider, provider_user_id, at),
                )
        except Exception as error:
            if is_duplicate_entry(error, "uq_social_provider_user"):
                raise SocialAccountExistsError(provider) from None
            if is_duplicate_entry(error, "uq_users_email"):
                raise EmailAlreadyExistsError(email) from None
            raise
        return User(id=int(user_id), email=email, nickname=nickname, agreed_at=from_db(at), created_at=from_db(at))

    def record_login(self, user_id: int, now: datetime) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE users SET last_login_at = %s WHERE id = %s", (to_db(now), user_id))

    def update_nickname(self, user_id: int, nickname: str) -> User | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE users SET nickname = %s WHERE id = %s", (nickname, user_id))
        return self.get_by_id(user_id)


class MySQLSessionStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def create(self, record: SessionRecord) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO sessions ({SESSION_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    record.token_hash,
                    record.user_id,
                    record.login_provider,
                    to_db(record.created_at),
                    to_db(record.last_seen_at),
                    to_db(record.expires_at),
                ),
            )

    def get(self, token_hash: str) -> SessionRecord | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {SESSION_COLUMNS} FROM sessions WHERE token_hash = %s", (token_hash,))
            return _session(cur.fetchone())

    def touch(self, token_hash: str, now: datetime) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE sessions SET last_seen_at = %s WHERE token_hash = %s", (to_db(now), token_hash))

    def delete(self, token_hash: str) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash,))

    def delete_expired(self, now: datetime) -> int:
        with self.pool.connection() as conn, conn.cursor() as cur:
            return cur.execute("DELETE FROM sessions WHERE expires_at <= %s", (to_db(now),))
