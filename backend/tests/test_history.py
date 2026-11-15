"""검색 기록 API·저장소 계약 테스트 (F9 3단계). history_backend fixture로 메모리와 MySQL(mysql_live)에서 같은 테스트를 돈다.

기록 저장은 4단계에서 GET /api/routes에 연결한다. 여기서는 저장소의 add로 직접 넣는다.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.factory import create_app
from app.auth import AuthService, PasswordHasher
from app.config import Settings
from app.departure import KST, MockRouteProvider
from app.history import MAX_ATTACHED_ROWS, HistoryDraft, HistoryService
from tests.auth_backends import mysql_live
from tests.conftest import NOW

BASE_URL = "https://testserver"
PASSWORD = "gilit1234"


def logged_in(app, email: str) -> tuple[TestClient, int]:
    client = TestClient(app, base_url=BASE_URL)
    body = {"name": email.split("@")[0], "email": email, "password": PASSWORD, "agreeTerms": True, "agreePrivacy": True}
    user_id = int(client.post("/api/auth/signup", json=body).json()["id"])
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return client, user_id


class Env:
    def __init__(self, backend) -> None:
        self.backend = backend
        auth = AuthService(backend.users, backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)
        self.service = HistoryService(backend.history, clock=lambda: NOW)
        self.app = create_app(Settings(), MockRouteProvider(), clock=lambda: NOW, auth=auth, history=self.service)
        self.alice, self.alice_id = logged_in(self.app, "alice@example.com")
        self.bob, self.bob_id = logged_in(self.app, "bob@example.com")
        self._tick = 0

    def add(self, user_id, origin="김해시청", dest="동의대학교", arrive=None, **extra):
        """한 행을 넣는다. 넣을 때마다 created_at을 1분씩 늦춘다 (순서를 분명히)."""
        self._tick += 1
        draft = HistoryDraft(
            origin_name=origin,
            dest_name=dest,
            arrive_at=arrive or datetime(2026, 11, 5, 9, 0, tzinfo=KST),
            **extra,
        )
        return self.backend.history.add(user_id, draft, NOW + timedelta(minutes=self._tick))

    def anonymous(self) -> TestClient:
        return TestClient(self.app, base_url=BASE_URL)


@pytest.fixture
def env(history_backend) -> Env:
    return Env(history_backend)


def cards(client: TestClient, **params) -> list[dict]:
    response = client.get("/api/history", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def routes(client: TestClient, **params) -> list[tuple[str, str]]:
    return [(card["from"], card["to"]) for card in cards(client, **params)]


def arrive(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=KST)


# --- 조회 ---


def test_empty_history(env):
    assert cards(env.alice) == []


def test_card_fields_and_mapping(env):
    entry = env.add(
        env.alice_id,
        origin="김해시청",
        dest="동의대학교",
        arrive=arrive(5, 9),
        origin_lat=35.2285,
        origin_lng=128.8894,
        dest_lat=35.1441,
        dest_lng=129.0336,
        buffer_min=10,
        recommended_depart_at=arrive(5, 8, 12),
        ai_summary="남해고속도로 경유가 가장 안정적이에요",
    )

    assert cards(env.alice) == [
        {
            "id": str(entry.id),
            "from": "김해시청",
            "to": "동의대학교",
            "arriveTime": "2026-11-05T09:00:00+09:00",
            "buffer": 10,
            "departTime": "2026-11-05T08:12:00+09:00",
            "fromLat": 35.2285,
            "fromLng": 128.8894,
            "toLat": 35.1441,
            "toLng": 129.0336,
        }
    ]


def test_optional_values_are_null(env):
    env.add(env.alice_id)

    card = cards(env.alice)[0]
    assert card["departTime"] is None
    assert (card["fromLat"], card["fromLng"], card["toLat"], card["toLng"]) == (None, None, None, None)
    assert card["buffer"] == 0


def test_newest_first(env):
    env.add(env.alice_id, dest="부산역")
    env.add(env.alice_id, dest="센텀시티")
    env.add(env.alice_id, dest="해운대")

    assert routes(env.alice) == [("김해시청", "해운대"), ("김해시청", "센텀시티"), ("김해시청", "부산역")]


# --- 같은 검색 묶기 ---


def test_same_search_on_different_days_is_one_card_showing_latest(env):
    env.add(env.alice_id, arrive=arrive(5, 9), buffer_min=5)
    env.add(env.alice_id, dest="부산역")
    latest = env.add(env.alice_id, arrive=arrive(9, 9), buffer_min=15)

    result = cards(env.alice)

    assert [(c["to"], c["arriveTime"]) for c in result] == [
        ("동의대학교", "2026-11-09T09:00:00+09:00"),  # 가장 최근 검색이 대표, 맨 앞
        ("부산역", "2026-11-05T09:00:00+09:00"),
    ]
    assert result[0]["id"] == str(latest.id)
    assert result[0]["buffer"] == 15


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"arrive": arrive(5, 9, 0)}, {"arrive": arrive(5, 9, 1)}),  # 분이 다름
        ({"arrive": arrive(5, 9)}, {"arrive": arrive(5, 21)}),  # 오전·오후
        ({"dest": "동의대학교"}, {"dest": "부산역"}),  # 목적지가 다름
        ({"origin": "김해시청"}, {"origin": "김해공항"}),  # 출발지가 다름
        ({"dest": "Busan Station"}, {"dest": "busan station"}),  # 이름은 대소문자를 구분한다 (화면에 보이는 그대로)
        ({"origin": "김해시청", "dest": "부산역"}, {"origin": "부산역", "dest": "김해시청"}),  # 방향이 반대
    ],
)
def test_different_searches_are_separate_cards(env, first, second):
    env.add(env.alice_id, **first)
    env.add(env.alice_id, **second)

    assert len(cards(env.alice)) == 2


def test_grouping_uses_korean_wall_clock(env):
    """같은 순간을 다른 시간대로 저장해도 한국 시각 기준 시:분이 같으면 같은 검색이다."""
    env.add(env.alice_id, arrive=arrive(5, 9))
    env.add(env.alice_id, arrive=datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc))  # = 11/6 09:00 KST

    result = cards(env.alice)
    assert len(result) == 1
    assert result[0]["arriveTime"] == "2026-11-06T09:00:00+09:00"  # 응답은 항상 KST


def test_buffer_does_not_split_cards(env):
    env.add(env.alice_id, buffer_min=0)
    env.add(env.alice_id, buffer_min=15)

    assert [c["buffer"] for c in cards(env.alice)] == [15]


# --- limit ---


def add_distinct(env, user_id, count):
    for i in range(count):
        env.add(user_id, dest=f"목적지{i:02d}")


def test_default_limit_is_20(env):
    add_distinct(env, env.alice_id, 25)

    result = cards(env.alice)
    assert len(result) == 20
    assert result[0]["to"] == "목적지24"


@pytest.mark.parametrize(("limit", "expected"), [("1", 1), ("50", 50), ("49", 49)])
def test_limit_boundaries(env, limit, expected):
    add_distinct(env, env.alice_id, 55)

    assert len(cards(env.alice, limit=limit)) == expected


def test_limit_counts_cards_after_grouping(env):
    for day in range(1, 11):  # 같은 검색 10번 + 다른 검색 2개
        env.add(env.alice_id, arrive=arrive(day, 9))
    env.add(env.alice_id, dest="부산역")
    env.add(env.alice_id, dest="해운대")

    assert routes(env.alice, limit="2") == [("김해시청", "해운대"), ("김해시청", "부산역")]
    assert len(cards(env.alice, limit="3")) == 3


@pytest.mark.parametrize("limit", ["0", "51", "abc", "-1", "1.5", "", " 5", "٣", "99999999999999999999"])
def test_invalid_limit_is_400(env, limit):
    env.add(env.alice_id)

    response = env.alice.get("/api/history", params={"limit": limit})

    assert response.status_code == 400
    assert response.json() == {"message": "개수는 1~50 사이의 정수여야 합니다."}


# --- 삭제 (분리) ---


def test_delete_one_removes_card_but_keeps_rows_detached(env):
    a1 = env.add(env.alice_id, arrive=arrive(5, 9))
    other = env.add(env.alice_id, dest="부산역")
    a2 = env.add(env.alice_id, arrive=arrive(6, 9))  # a1과 같은 검색 → 카드 하나 (대표는 a2)

    response = env.alice.delete("/api/history", params={"id": cards(env.alice)[0]["id"]})

    assert response.status_code == 204
    assert response.content == b""
    assert routes(env.alice) == [("김해시청", "부산역")]  # 묶음 전체가 사라지고 다른 카드는 남는다
    rows = dict(env.backend.history_rows())
    assert rows[a1.id] is None and rows[a2.id] is None  # 행은 남고 사용자에게서만 분리됐다 (통계 보존)
    assert rows[other.id] == env.alice_id


def test_delete_by_older_row_id_of_group_also_removes_card(env):
    older = env.add(env.alice_id, arrive=arrive(5, 9))
    env.add(env.alice_id, arrive=arrive(6, 9))

    assert env.alice.delete("/api/history", params={"id": str(older.id)}).status_code == 204
    assert cards(env.alice) == []


def test_deleted_card_id_is_404_afterwards(env):
    entry = env.add(env.alice_id)
    assert env.alice.delete("/api/history", params={"id": str(entry.id)}).status_code == 204

    again = env.alice.delete("/api/history", params={"id": str(entry.id)})

    assert again.status_code == 404
    assert again.json() == {"message": "찾을 수 없습니다."}


def test_delete_all_detaches_everything_and_is_idempotent(env):
    mine = [env.add(env.alice_id, dest=f"목적지{i}") for i in range(3)]
    bobs = env.add(env.bob_id)

    first = env.alice.delete("/api/history")
    second = env.alice.delete("/api/history")

    assert (first.status_code, second.status_code) == (204, 204)
    assert cards(env.alice) == []
    rows = dict(env.backend.history_rows())
    assert all(rows[entry.id] is None for entry in mine)  # 분리됐지만 남아 있다
    assert rows[bobs.id] == env.bob_id  # 다른 사용자 것은 그대로
    assert len(cards(env.bob)) == 1


def test_new_search_after_delete_appears_again(env):
    env.add(env.alice_id)
    env.alice.delete("/api/history")

    env.add(env.alice_id)

    assert len(cards(env.alice)) == 1


# --- 본인 데이터만 ---

NOT_FOUND = {"message": "찾을 수 없습니다."}


def test_other_users_history_is_invisible_and_untouchable(env):
    entry = env.add(env.alice_id)

    response = env.bob.delete("/api/history", params={"id": str(entry.id)})

    assert cards(env.bob) == []
    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert [c["id"] for c in cards(env.alice)] == [str(entry.id)]  # 원래 데이터 그대로
    assert dict(env.backend.history_rows())[entry.id] == env.alice_id


def test_bob_delete_all_does_not_touch_alice(env):
    entry = env.add(env.alice_id)

    assert env.bob.delete("/api/history").status_code == 204

    assert dict(env.backend.history_rows())[entry.id] == env.alice_id


@pytest.mark.parametrize("bad_id", ["", "abc", "0", "-1", "1.0", "١", "99999999999999999999", "1 OR 1=1"])
def test_invalid_id_is_404_and_does_not_delete_all(env, bad_id):
    """?id=가 잘못돼도 '전체 삭제'로 넘어가지 않는다."""
    env.add(env.alice_id)

    response = env.alice.delete("/api/history", params={"id": bad_id})

    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert len(cards(env.alice)) == 1


# --- 비로그인 ---


@pytest.mark.parametrize(
    ("method", "params"),
    [("get", {}), ("get", {"limit": "5"}), ("delete", {"id": "1"}), ("delete", {})],
)
def test_anonymous_is_401(env, method, params):
    entry = env.add(env.alice_id)

    response = getattr(env.anonymous(), method)("/api/history", params=params)

    assert response.status_code == 401
    assert response.json() == {"message": "로그인이 필요합니다."}
    assert dict(env.backend.history_rows())[entry.id] == env.alice_id


def test_anonymous_searches_are_stored_for_stats_but_never_listed(env):
    anonymous_row = env.add(None, dest="부산역")
    env.add(env.alice_id)

    assert routes(env.alice) == [("김해시청", "동의대학교")]
    assert cards(env.bob) == []
    env.alice.delete("/api/history")
    assert dict(env.backend.history_rows())[anonymous_row.id] is None  # 처음부터 연결 없음, 그대로


# --- 보관 상한 ---


def test_attached_rows_are_capped_and_oldest_detached(env):
    total = MAX_ATTACHED_ROWS + 5
    for i in range(total):
        env.add(env.alice_id, arrive=arrive(5, 9))  # 같은 검색을 계속 반복

    rows = env.backend.history_rows()
    attached = [row_id for row_id, user_id in rows if user_id == env.alice_id]
    assert len(rows) == total  # 지우지 않는다 (통계)
    assert len(attached) == MAX_ATTACHED_ROWS
    assert attached == [row_id for row_id, _ in rows][5:]  # 가장 오래된 5개가 분리됐다
    assert len(cards(env.alice)) == 1


# --- 기타 ---


def test_service_add_uses_clock(env):
    entry = env.service.add(env.alice_id, HistoryDraft(origin_name="a", dest_name="b", arrive_at=arrive(5, 9)))

    assert entry.created_at == NOW
    assert entry.user_id == env.alice_id


def test_other_origin_delete_is_403(env):
    env.add(env.alice_id)

    response = env.alice.delete("/api/history", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert len(cards(env.alice)) == 1


def test_history_api_is_503_when_store_is_unavailable(env):
    env.app.state.history = None

    response = env.alice.get("/api/history")

    assert response.status_code == 503
    assert response.json() == {"message": "검색 기록을 지금 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."}


def test_memory_store_is_default_and_mysql_shares_pool():
    from app.history import MemoryHistoryStore
    from app.history.mysql_stores import MySQLHistoryStore

    assert isinstance(create_app(Settings(), MockRouteProvider()).state.history.store, MemoryHistoryStore)
    settings = Settings.from_env(
        {"AUTH_STORE": "mysql", "DB_HOST": "db.invalid", "DB_NAME": "gilit", "DB_USER": "gilit_app", "DB_PASSWORD": "pw"}
    )
    app = create_app(settings, MockRouteProvider())
    assert isinstance(app.state.history.store, MySQLHistoryStore)
    assert app.state.history.store.pool is app.state.db_pool is app.state.auth.users.pool


# --- MySQL 전용: 탈퇴 시 FK 동작 ---


def mysql_only(func):
    for mark in mysql_live:
        func = mark(func)
    return func


@pytest.fixture
def mysql_env():
    from tests.auth_backends import make_backend

    backend = make_backend("mysql")
    yield Env(backend)
    backend.close()


@mysql_only
def test_user_deletion_keeps_history_rows_with_null_user(mysql_env):
    """탈퇴(users 행 삭제) 시 기록은 남고 user_id만 NULL이 된다 (fk_history_user ON DELETE SET NULL)."""
    env = mysql_env
    mine = [env.add(env.alice_id, dest=f"목적지{i}") for i in range(3)]
    bobs = env.add(env.bob_id)

    env.backend.execute("DELETE FROM users WHERE id = %s", (env.alice_id,))

    rows = dict(env.backend.history_rows())
    assert all(rows[entry.id] is None for entry in mine)
    assert rows[bobs.id] == env.bob_id
    (row,) = env.backend.execute(
        "SELECT COUNT(*) AS n FROM search_history WHERE dest_name LIKE %s", ("목적지%",)
    )
    assert row["n"] == 3  # 인기 목적지 통계에 계속 쓰인다


@mysql_only
def test_detached_rows_keep_all_columns(mysql_env):
    """분리는 user_id만 바꾼다. 통계에 쓰는 값은 그대로다."""
    env = mysql_env
    entry = env.add(env.alice_id, origin_lat=35.2285, origin_lng=128.8894, buffer_min=10, ai_summary="요약")

    env.alice.delete("/api/history", params={"id": str(entry.id)})

    (row,) = env.backend.execute(
        "SELECT user_id, origin_name, dest_name, CAST(arrive_at AS CHAR) AS arrive, buffer_min, origin_lat, ai_summary, "
        "travel_mode FROM search_history WHERE id = %s",
        (entry.id,),
    )
    assert row["user_id"] is None
    assert (row["origin_name"], row["dest_name"], row["arrive"]) == ("김해시청", "동의대학교", "2026-11-05 09:00:00")
    assert (row["buffer_min"], float(row["origin_lat"]), row["ai_summary"], row["travel_mode"]) == (10, 35.2285, "요약", "car")
