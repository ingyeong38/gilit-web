"""회원 저장소 계약 테스트용 백엔드 (메모리 / MySQL).

같은 테스트를 두 저장소에서 돌린다. MySQL 쪽은 mysql_live 마커가 붙어 기본 pytest에서 빠진다:

    venv/Scripts/python -m pytest -m mysql_live

접속 정보는 DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_SSL_CA와 TEST_DB_NAME(환경변수, backend/.env, 루트 .env 순)이다.
테스트는 TEST_DB_NAME DB의 users, social_accounts, sessions를 비우므로, 이름이 _test로 끝나고 DB_NAME과 다를 때만 실행한다.
isolated_env fixture가 환경변수를 지우기 전, import 시점에 읽는다. os.environ은 바꾸지 않는다.
"""

import os
from datetime import datetime

import pytest
from dotenv import dotenv_values

from app.auth import MemorySessionStore, MemoryUserStore, User
from app.favorites import MemoryFavoriteStore
from app.history import MemoryHistoryStore
from app.config import ENV_FILES
from app.db import ConnectionPool, MySQLConfig, to_db
from app.departure import KST

DB_VARS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_SSL_CA", "TEST_DB_NAME")
AUTH_TABLES = ("sessions", "social_accounts", "favorite_places", "search_history", "users")  # 지우는 순서 (FK)


def _read_vars() -> dict[str, str]:
    values = {name: os.environ.get(name, "") for name in DB_VARS}
    for path in ENV_FILES:
        if path.is_file():
            file_values = dotenv_values(path)
            for name in DB_VARS:
                if not values[name]:
                    values[name] = file_values.get(name) or ""
    return values


def find_test_config() -> tuple[MySQLConfig | None, str]:
    values = _read_vars()
    missing = [name for name in ("DB_HOST", "DB_USER", "DB_PASSWORD", "TEST_DB_NAME") if not values[name].strip()]
    if missing:
        return None, f"MySQL 테스트 DB 설정이 없어 건너뜁니다 ({', '.join(missing)})."
    test_db = values["TEST_DB_NAME"].strip()
    if not test_db.endswith("_test"):
        return None, f"TEST_DB_NAME은 _test로 끝나야 합니다 (테스트가 데이터를 지운다): {test_db}"
    if test_db == values["DB_NAME"].strip():
        return None, "TEST_DB_NAME이 DB_NAME과 같습니다. 개발 DB를 지우지 않도록 다른 DB를 쓰세요."
    try:
        port = int(values["DB_PORT"].strip() or 3306)
    except ValueError:
        return None, "DB_PORT는 정수여야 합니다."
    config = MySQLConfig(
        host=values["DB_HOST"].strip(),
        port=port,
        database=test_db,
        user=values["DB_USER"].strip(),
        password=values["DB_PASSWORD"],
        ssl_ca=values["DB_SSL_CA"].strip() or None,
    )
    return config, ""


MYSQL_CONFIG, MYSQL_SKIP_REASON = find_test_config()
mysql_live = [pytest.mark.mysql_live, pytest.mark.skipif(MYSQL_CONFIG is None, reason=MYSQL_SKIP_REASON)]


class MemoryBackend:
    kind = "memory"
    persistent = False

    def __init__(self) -> None:
        self.users = MemoryUserStore()
        self.sessions = MemorySessionStore()
        self.favorites = MemoryFavoriteStore()
        self.history = MemoryHistoryStore()

    def history_rows(self) -> list[tuple[int, int | None]]:
        """검색 기록 전체 (id, user_id), id 순."""
        return [(row.id, row.user_id) for row in self.history.rows()]

    def add_social_only_user(self, email: str | None, nickname: str) -> User:
        return self.users.add_user(User(id=0, email=email, nickname=nickname, agreed_at=datetime.now(KST)))

    def session_count(self) -> int:
        return len(self.sessions)

    def user_count(self) -> int:
        return self.users.count()

    def social_links(self) -> list[tuple[str, str, int]]:
        return sorted(self.users.social_links())

    def restarted(self) -> "MemoryBackend":
        """서버를 다시 시작한 것처럼 새 저장소를 만든다. 메모리는 데이터가 사라진다."""
        return MemoryBackend()

    def close(self) -> None:
        pass


class MySQLBackend:
    kind = "mysql"
    persistent = True

    def __init__(self, config: MySQLConfig) -> None:
        from app.auth.mysql_stores import MySQLSessionStore, MySQLUserStore

        from app.favorites.mysql_stores import MySQLFavoriteStore
        from app.history.mysql_stores import MySQLHistoryStore

        self.config = config
        self.pool = ConnectionPool(config)
        self.users = MySQLUserStore(self.pool)
        self.sessions = MySQLSessionStore(self.pool)
        self.favorites = MySQLFavoriteStore(self.pool)
        self.history = MySQLHistoryStore(self.pool)

    def history_rows(self) -> list[tuple[int, int | None]]:
        rows = self.execute("SELECT id, user_id FROM search_history ORDER BY id")
        return [(int(r["id"]), int(r["user_id"]) if r["user_id"] is not None else None) for r in rows]

    def execute(self, sql: str, params: tuple = ()):
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def check_schema(self) -> None:
        tables = {next(iter(row.values())) for row in self.execute("SHOW TABLES")}
        missing = [t for t in AUTH_TABLES if t not in tables]
        if missing:
            pytest.fail(
                f"테스트 DB {self.config.database}에 {', '.join(missing)} 테이블이 없습니다. "
                "db/schema.sql(이미 만든 DB는 db/migrations/)을 적용하세요 (db/README.md).",
                pytrace=False,
            )
        (row,) = self.execute("SELECT DATABASE() AS db")
        assert row["db"].endswith("_test")

    def check_favorites_migration(self) -> None:
        """즐겨찾기 테스트는 마이그레이션 003(UNIQUE·CHECK)이 적용된 DB에서만 돈다."""
        indexes = {
            row["INDEX_NAME"]
            for row in self.execute(
                "SELECT INDEX_NAME FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'favorite_places'"
            )
        }
        checks = {
            row["CONSTRAINT_NAME"]
            for row in self.execute(
                "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'favorite_places' AND CONSTRAINT_TYPE = 'CHECK'"
            )
        }
        missing = [name for name in ("uq_favorite_user_name",) if name not in indexes]
        missing += [name for name in ("chk_favorite_label",) if name not in checks]
        if missing:
            pytest.fail(
                f"테스트 DB {self.config.database}에 마이그레이션 003이 적용되지 않았습니다 (없음: {', '.join(missing)}). "
                "관리자 계정으로 db/migrations/003_favorite_places_constraints.sql을 실행하세요 (db/README.md).",
                pytrace=False,
            )

    def reset(self) -> None:
        for table in AUTH_TABLES:
            self.execute(f"DELETE FROM {table}")  # 서비스 계정에는 TRUNCATE(DROP 권한)가 없다

    def add_social_only_user(self, email: str | None, nickname: str) -> User:
        now = to_db(datetime.now(KST))
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash, nickname, agreed_at, created_at) VALUES (%s, NULL, %s, %s, %s)",
                (email, nickname, now, now),
            )
            user_id = cur.lastrowid
        return self.users.get_by_id(user_id)

    def session_count(self) -> int:
        (row,) = self.execute("SELECT COUNT(*) AS n FROM sessions")
        return int(row["n"])

    def user_count(self) -> int:
        (row,) = self.execute("SELECT COUNT(*) AS n FROM users")
        return int(row["n"])

    def social_links(self) -> list[tuple[str, str, int]]:
        rows = self.execute("SELECT provider, provider_user_id, user_id FROM social_accounts")
        return sorted((r["provider"], r["provider_user_id"], int(r["user_id"])) for r in rows)

    def restarted(self) -> "MySQLBackend":
        """서버를 다시 시작한 것처럼 새 연결 풀과 저장소를 만든다. DB 데이터는 남는다."""
        return MySQLBackend(self.config)

    def close(self) -> None:
        self.pool.close()


def make_backend(kind: str, favorites: bool = False):
    """favorites=True면 MySQL에 마이그레이션 003이 적용돼 있는지도 확인한다 (즐겨찾기 테스트용)."""
    if kind == "memory":
        return MemoryBackend()
    backend = MySQLBackend(MYSQL_CONFIG)
    backend.check_schema()
    if favorites:
        backend.check_favorites_migration()
    backend.reset()
    return backend
