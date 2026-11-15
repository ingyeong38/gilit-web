"""MySQL 연결 (PyMySQL). 회원·즐겨찾기·기록 저장소가 함께 쓴다.

접속 정보는 환경변수(DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SSL_CA)로만 받는다 (app/config.py).
로컬 MySQL과 RDS는 .env 값만 바꾸면 된다. 서비스 계정(gilit_app)에는 SELECT, INSERT, UPDATE, DELETE만 준다.

- 연결마다 utf8mb4와 SET time_zone = '+09:00'을 적용한다. DB의 DATETIME은 모두 한국 시간이다 (db/README.md).
- 파이썬 쪽은 시간대가 있는 datetime(KST)을 쓰고, DB와 주고받을 때만 to_db / from_db로 바꾼다.
- 모든 쿼리는 파라미터 바인딩(%s)으로 실행한다. 문자열을 이어 붙여 SQL을 만들지 않는다.
"""

import logging
import queue
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

import pymysql
import pymysql.cursors

from app.departure import KST

logger = logging.getLogger("app.db")

DUPLICATE_ENTRY = 1062  # MySQL ER_DUP_ENTRY (UNIQUE 위반)
SESSION_INIT = "SET time_zone = '+09:00'"


@dataclass(frozen=True)
class MySQLConfig:
    host: str
    database: str
    user: str
    password: str = field(repr=False)
    port: int = 3306
    ssl_ca: str | None = None  # RDS는 CA 번들 경로를 주면 TLS로 연결한다
    connect_timeout: int = 5
    read_timeout: int = 10
    write_timeout: int = 10

    def connect_kwargs(self) -> dict:
        kwargs = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "charset": "utf8mb4",
            "init_command": SESSION_INIT,
            "autocommit": False,
            "cursorclass": pymysql.cursors.DictCursor,
            "connect_timeout": self.connect_timeout,
            "read_timeout": self.read_timeout,
            "write_timeout": self.write_timeout,
        }
        if self.ssl_ca:
            kwargs["ssl"] = {"ca": self.ssl_ca}
        return kwargs


class ConnectionPool:
    """작은 연결 풀. 웹 서버 스레드풀에서 동시에 쓸 수 있다.

    connection()은 블록이 정상으로 끝나면 commit, 예외가 나면 rollback한다. 쉬는 연결은 최대 size개까지 둔다.
    오래 쉰 연결(MySQL wait_timeout으로 끊김)은 꺼낼 때 ping으로 확인하고, 끊겼으면 새로 연다.
    처음 쓸 때 연결하므로 DB가 꺼져 있어도 앱은 뜬다 (요청은 500).
    """

    def __init__(self, config: MySQLConfig, size: int = 5, connect=pymysql.connect) -> None:
        self.config = config
        self._connect = connect
        self._idle: queue.LifoQueue = queue.LifoQueue(maxsize=size)
        self._lock = threading.Lock()
        self._closed = False

    def _open(self):
        return self._connect(**self.config.connect_kwargs())

    def _take(self):
        while True:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                return self._open()
            try:
                conn.ping()
                return conn
            except pymysql.Error:
                _close_quietly(conn)

    def _give(self, conn) -> None:
        if self._closed:
            _close_quietly(conn)
            return
        try:
            self._idle.put_nowait(conn)
        except queue.Full:
            _close_quietly(conn)

    @contextmanager
    def connection(self) -> Iterator["pymysql.connections.Connection"]:
        conn = self._take()
        try:
            yield conn
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except Exception:
                # 연결이 끊긴 경우. 풀에 돌려놓지 않는다.
                _close_quietly(conn)
                conn = None
            raise
        finally:
            if conn is not None:
                self._give(conn)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        while True:
            try:
                _close_quietly(self._idle.get_nowait())
            except queue.Empty:
                return


def _close_quietly(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def is_duplicate_entry(error: Exception, key: str | None = None) -> bool:
    """UNIQUE 위반(1062)인지. key를 주면 그 인덱스 이름의 위반인지까지 본다.

    MySQL 8 메시지: "Duplicate entry 'x' for key 'users.uq_users_email'"
    """
    if not (isinstance(error, pymysql.err.IntegrityError) and error.args and error.args[0] == DUPLICATE_ENTRY):
        return False
    if key is None:
        return True
    message = str(error.args[1]) if len(error.args) > 1 else ""
    return message.endswith(f".{key}'") or message.endswith(f"'{key}'")


def to_db(value: datetime | None) -> datetime | None:
    """KST의 시간대 없는 datetime으로 바꾼다. DATETIME은 초 단위라 마이크로초는 버린다 (MySQL은 반올림한다)."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(KST).replace(tzinfo=None)
    return value.replace(microsecond=0)


def from_db(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=KST) if value is not None else None
