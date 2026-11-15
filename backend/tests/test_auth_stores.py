"""회원·세션 저장소 계약 테스트. store_backend fixture로 메모리와 MySQL(mysql_live)에서 같은 테스트를 돌린다.

    venv/Scripts/python -m pytest                      # 메모리만
    venv/Scripts/python -m pytest -m mysql_live        # MySQL 테스트 DB (tests/auth_backends.py)
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pymysql
import pytest
from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE
from app.api.factory import create_app
from app.auth import AuthService, EmailAlreadyExistsError, PasswordHasher, SessionRecord, hash_token
from app.config import Settings
from app.db import ConnectionPool, MySQLConfig, from_db, to_db
from app.departure import KST, MockRouteProvider
from tests.auth_backends import make_backend, mysql_live
from tests.conftest import NOW

HASH = "$2b$04$abcdefghijklmnopqrstuuJ0yB1Qv4uX3n3bq0Zb5vO9sHq0cS1m2"  # 형식만 맞춘 값 (저장소는 해시를 해석하지 않는다)
requires_mysql = mysql_live  # 마커 목록: [mysql_live, skipif]


def session(token_hash="a" * 64, user_id=1, created=NOW, ttl=timedelta(days=14)) -> SessionRecord:
    return SessionRecord(token_hash, user_id, "email", created, created, created + ttl)


# --- 사용자 ---


def test_create_and_read_user(store_backend):
    users = store_backend.users

    created = users.create_email_user("user@example.com", HASH, "길잇", NOW)

    by_email = users.get_by_email("user@example.com")
    by_id = users.get_by_id(created.id)
    assert by_email == by_id
    assert by_email.id == created.id
    assert (by_email.email, by_email.nickname, by_email.password_hash) == ("user@example.com", "길잇", HASH)
    assert by_email.agreed_at == NOW and by_email.created_at == NOW
    assert by_email.agreed_at.utcoffset() == timedelta(hours=9)  # 시간대가 있는 KST로 돌아온다
    assert by_email.last_login_at is None
    assert users.get_by_email("nobody@example.com") is None
    assert users.get_by_id(created.id + 1000) is None


def test_duplicate_email_raises_and_keeps_first_user(store_backend):
    users = store_backend.users
    first = users.create_email_user("user@example.com", HASH, "처음", NOW)

    with pytest.raises(EmailAlreadyExistsError):
        users.create_email_user("user@example.com", HASH, "두번째", NOW)

    assert users.get_by_email("user@example.com").id == first.id
    assert users.get_by_email("user@example.com").nickname == "처음"


def test_concurrent_signup_with_same_email_creates_one_user(store_backend):
    """먼저 조회하지 않고 INSERT의 UNIQUE 위반으로 판단하므로, 동시에 가입해도 하나만 성공한다."""
    users = store_backend.users
    workers = 10
    barrier = threading.Barrier(workers)

    def attempt(i: int) -> str:
        barrier.wait()
        try:
            users.create_email_user("race@example.com", HASH, f"사용자{i}", NOW)
            return "created"
        except EmailAlreadyExistsError:
            return "duplicate"

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(attempt, range(workers)))

    assert results.count("created") == 1
    assert results.count("duplicate") == workers - 1
    assert users.get_by_email("race@example.com") is not None


def test_concurrent_signup_api_returns_one_201_and_rest_409(store_backend):
    auth = AuthService(store_backend.users, store_backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)
    app = create_app(Settings(), MockRouteProvider(), clock=lambda: NOW, auth=auth)
    workers = 8
    barrier = threading.Barrier(workers)
    body = {"name": "길잇", "email": "race@example.com", "password": "gilit1234", "agreeTerms": True, "agreePrivacy": True}

    def attempt(i: int) -> int:
        client = TestClient(app, base_url="https://testserver", client=(f"10.0.0.{i}", 50000))  # 가입 횟수 제한은 IP별
        barrier.wait()
        return client.post("/api/auth/signup", json=body).status_code

    with ThreadPoolExecutor(workers) as pool:
        statuses = list(pool.map(attempt, range(workers)))

    assert sorted(statuses) == [201] + [409] * (workers - 1)


def test_record_login_updates_last_login_at(store_backend):
    users = store_backend.users
    user = users.create_email_user("user@example.com", HASH, "길잇", NOW)

    users.record_login(user.id, NOW + timedelta(hours=3))

    assert users.get_by_id(user.id).last_login_at == NOW + timedelta(hours=3)


def test_utf8mb4_nickname_round_trip(store_backend):
    users = store_backend.users

    user = users.create_email_user("emoji@example.com", HASH, "길잇🚗드라이버", NOW)

    assert users.get_by_id(user.id).nickname == "길잇🚗드라이버"


def test_users_without_email_can_coexist(store_backend):
    """카카오 가입자처럼 이메일이 없는 계정이 여럿 있어도 된다 (001: users.email NULL 허용)."""
    first = store_backend.add_social_only_user(None, "카카오1")
    second = store_backend.add_social_only_user(None, "카카오2")

    assert first.id != second.id
    assert first.email is None and second.email is None
    assert store_backend.users.get_by_id(second.id).password_hash is None


# --- 세션 ---


def test_session_create_get_touch_delete(store_backend):
    user = store_backend.users.create_email_user("user@example.com", HASH, "길잇", NOW)
    sessions = store_backend.sessions
    record = session(user_id=user.id)

    sessions.create(record)
    assert sessions.get(record.token_hash) == record

    sessions.touch(record.token_hash, NOW + timedelta(hours=2))
    touched = sessions.get(record.token_hash)
    assert touched.last_seen_at == NOW + timedelta(hours=2)
    assert touched.expires_at == record.expires_at

    sessions.delete(record.token_hash)
    assert sessions.get(record.token_hash) is None
    sessions.delete(record.token_hash)  # 없어도 오류가 나지 않는다
    sessions.touch("b" * 64, NOW)


def test_delete_expired_removes_only_expired_sessions(store_backend):
    user = store_backend.users.create_email_user("user@example.com", HASH, "길잇", NOW)
    sessions = store_backend.sessions
    sessions.create(session("1" * 64, user.id, created=NOW - timedelta(days=15)))  # 이미 만료
    sessions.create(session("2" * 64, user.id, created=NOW - timedelta(days=14)))  # 지금 만료 (경계)
    sessions.create(session("3" * 64, user.id, created=NOW - timedelta(days=13)))  # 유효

    assert sessions.delete_expired(NOW) == 2

    assert sessions.get("1" * 64) is None
    assert sessions.get("2" * 64) is None
    assert sessions.get("3" * 64) is not None
    assert sessions.delete_expired(NOW) == 0


def make_app(backend, clock):
    auth = AuthService(backend.users, backend.sessions, PasswordHasher(rounds=4), clock=clock)
    app = create_app(Settings(), MockRouteProvider(), clock=clock, auth=auth)
    return TestClient(app, base_url="https://testserver")


def signup_and_login(client: TestClient, email: str = "user@example.com") -> str:
    body = {"name": "길잇", "email": email, "password": "gilit1234", "agreeTerms": True, "agreePrivacy": True}
    assert client.post("/api/auth/signup", json=body).status_code == 201
    response = client.post("/api/auth/login", json={"email": email, "password": "gilit1234"})
    assert response.status_code == 200
    return response.cookies[SESSION_COOKIE]


def test_login_cleans_up_other_expired_sessions(store_backend):
    """만료된 세션은 로그인할 때 지운다. 다른 사용자의 만료 세션도 함께 정리된다."""
    other = store_backend.users.create_email_user("old@example.com", HASH, "예전사용자", NOW)
    store_backend.sessions.create(session("e" * 64, other.id, created=NOW - timedelta(days=20)))
    store_backend.sessions.create(session("f" * 64, other.id, created=NOW - timedelta(days=1)))
    clock_now = [NOW]
    client = make_app(store_backend, lambda: clock_now[0])

    signup_and_login(client)

    assert store_backend.sessions.get("e" * 64) is None
    assert store_backend.sessions.get("f" * 64) is not None
    assert store_backend.session_count() == 2  # 아직 유효한 다른 세션 + 방금 만든 세션


def test_session_survives_server_restart_only_with_persistent_store(store_backend):
    """MySQL은 서버를 다시 시작해도(새 연결 풀·저장소·앱) 같은 쿠키로 로그인이 유지된다. 메모리는 사라진다."""
    token = signup_and_login(make_app(store_backend, lambda: NOW))

    restarted = store_backend.restarted()
    try:
        response = make_app(restarted, lambda: NOW).get("/api/auth/me", cookies=None, headers={"Cookie": f"{SESSION_COOKIE}={token}"})
    finally:
        restarted.close()

    if store_backend.persistent:
        assert response.status_code == 200
        assert response.json()["email"] == "user@example.com"
    else:
        assert response.status_code == 401


# --- MySQL 전용 ---


@pytest.fixture
def mysql_backend():
    backend = make_backend("mysql")
    yield backend
    backend.close()


@pytest.mark.mysql_live
@requires_mysql[1]
def test_connection_uses_kst_time_zone_and_utf8mb4(mysql_backend):
    (row,) = mysql_backend.execute(
        "SELECT @@session.time_zone AS tz, @@character_set_connection AS cs, @@character_set_client AS client"
    )

    assert row == {"tz": "+09:00", "cs": "utf8mb4", "client": "utf8mb4"}


@pytest.mark.mysql_live
@requires_mysql[1]
def test_datetime_is_stored_as_kst_wall_clock(mysql_backend):
    """DB에는 시간대 없는 한국 시각이 들어간다. UTC로 바뀌어 저장되지 않는다."""
    utc_instant = datetime(2026, 11, 4, 0, 30, tzinfo=KST).astimezone(tz=None)  # 같은 순간을 다른 시간대로
    user = mysql_backend.users.create_email_user("tz@example.com", HASH, "시간대", utc_instant)

    (row,) = mysql_backend.execute("SELECT CAST(created_at AS CHAR) AS created FROM users WHERE id = %s", (user.id,))

    assert row["created"] == "2026-11-04 00:30:00"


@pytest.mark.mysql_live
@requires_mysql[1]
def test_deleting_user_cascades_sessions(mysql_backend):
    user = mysql_backend.users.create_email_user("bye@example.com", HASH, "탈퇴", NOW)
    mysql_backend.sessions.create(session(user_id=user.id))

    mysql_backend.execute("DELETE FROM users WHERE id = %s", (user.id,))

    assert mysql_backend.sessions.get("a" * 64) is None


@pytest.mark.mysql_live
@requires_mysql[1]
def test_session_provider_check_constraint(mysql_backend):
    user = mysql_backend.users.create_email_user("chk@example.com", HASH, "제약", NOW)
    bad = SessionRecord("c" * 64, user.id, "naver", NOW, NOW, NOW + timedelta(days=1))

    with pytest.raises(pymysql.err.OperationalError):  # CHECK 위반은 3819 (OperationalError)
        mysql_backend.sessions.create(bad)


@pytest.mark.mysql_live
@requires_mysql[1]
def test_pool_recovers_after_server_drops_idle_connection(mysql_backend):
    """MySQL이 쉬는 연결을 끊어도(wait_timeout, DB 재시작) 다음 요청은 새 연결로 처리한다."""
    mysql_backend.users.create_email_user("pool@example.com", HASH, "풀", NOW)
    with mysql_backend.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT CONNECTION_ID() AS id")
        idle_id = cur.fetchone()["id"]
    # 풀에서 쉬고 있는 연결을 서버 쪽에서 끊는다 (같은 계정의 연결은 KILL할 수 있다).
    killer = pymysql.connect(**mysql_backend.config.connect_kwargs())
    try:
        with killer.cursor() as cur:
            cur.execute("KILL %s", (idle_id,))
    finally:
        killer.close()

    assert mysql_backend.users.get_by_email("pool@example.com") is not None
    with mysql_backend.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT CONNECTION_ID() AS id, @@session.time_zone AS tz")
        row = cur.fetchone()
    assert row["id"] != idle_id
    assert row["tz"] == "+09:00"  # 새 연결에도 시간대 설정이 적용된다


# --- 연결 풀과 시각 변환 (DB 없이) ---


class FakeConnection:
    def __init__(self, alive: bool = True) -> None:
        self.alive = alive
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.rollback_fails = False

    def ping(self):
        if not self.alive:
            raise pymysql.err.OperationalError(2006, "MySQL server has gone away")

    def commit(self):
        self.commits += 1

    def rollback(self):
        if self.rollback_fails:
            raise pymysql.err.OperationalError(2013, "Lost connection")
        self.rollbacks += 1

    def close(self):
        self.closed = True


def fake_pool(size: int = 2):
    opened: list[FakeConnection] = []

    def connect(**kwargs):
        opened.append(FakeConnection())
        return opened[-1]

    config = MySQLConfig(host="localhost", database="gilit", user="gilit_app", password="pw")
    return ConnectionPool(config, size=size, connect=connect), opened


def test_pool_commits_on_success_and_reuses_connection():
    pool, opened = fake_pool()

    with pool.connection() as first:
        pass
    with pool.connection() as second:
        pass

    assert first is second
    assert len(opened) == 1
    assert first.commits == 2


def test_pool_rolls_back_on_error_and_keeps_connection():
    pool, opened = fake_pool()

    with pytest.raises(ValueError), pool.connection():
        raise ValueError("boom")

    assert opened[0].rollbacks == 1 and opened[0].commits == 0
    with pool.connection() as conn:
        assert conn is opened[0]


def test_pool_discards_connection_when_rollback_fails():
    pool, opened = fake_pool()

    with pytest.raises(ValueError), pool.connection() as conn:
        conn.rollback_fails = True
        raise ValueError("boom")

    assert opened[0].closed
    with pool.connection() as conn:
        assert conn is not opened[0]


def test_pool_replaces_dead_idle_connection():
    pool, opened = fake_pool()
    with pool.connection() as conn:
        pass
    conn.alive = False

    with pool.connection() as fresh:
        pass

    assert fresh is not conn
    assert conn.closed
    assert len(opened) == 2


def test_pool_keeps_at_most_size_idle_connections():
    pool, opened = fake_pool(size=1)
    first_cm, second_cm = pool.connection(), pool.connection()
    first, second = first_cm.__enter__(), second_cm.__enter__()  # 동시에 두 개 사용

    first_cm.__exit__(None, None, None)
    second_cm.__exit__(None, None, None)

    assert len(opened) == 2
    assert not first.closed and second.closed  # 쉬는 연결은 1개만 남는다


def test_to_db_and_from_db_use_kst_wall_clock_seconds():
    aware = datetime(2026, 11, 4, 6, 0, 0, 999_999, tzinfo=KST)

    stored = to_db(aware)

    assert stored == datetime(2026, 11, 4, 6, 0, 0)  # 반올림하지 않고 버린다
    assert stored.tzinfo is None
    assert to_db(aware.astimezone(tz=None)) == stored  # 다른 시간대로 와도 한국 시각으로 저장
    assert from_db(stored) == aware.replace(microsecond=0)
    assert to_db(None) is None and from_db(None) is None
