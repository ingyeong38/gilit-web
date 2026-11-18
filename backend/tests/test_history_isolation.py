"""검색 기록 계정 분리 테스트. 경로 조회(GET /api/routes)로 저장하고 GET /api/history로 확인한다.

- 이메일 회원 2명, 소셜 회원 2명(Google 검증 이메일, 카카오 이메일 없음), 같은 이메일(미검증)로 들어온 카카오 회원이
  서로의 기록을 보지 못한다.
- 비로그인 검색은 경로만 돌려주고 기록을 저장하지 않는다. 비로그인 조회는 401.
- user_id가 NULL인 행(마이그레이션 004 이전 데이터)이 남아 있어도 어떤 사용자에게도 보이지 않는다.

history_backend fixture로 메모리와 MySQL(mysql_live)에서 같은 테스트를 돈다.
"""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE
from app.api.factory import create_app
from app.auth import AuthService, PasswordHasher
from app.auth.oauth import OAuthProfile
from app.config import Settings
from app.history import HistoryService
from tests.conftest import NOW, kst
from tests.test_history import BASE_URL, logged_in
from tests.test_road_routes import RoadProvider


class Env:
    def __init__(self, backend) -> None:
        self.backend = backend
        self.auth = AuthService(backend.users, backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)
        self.app = create_app(
            Settings(route_provider="kakao"),
            RoadProvider(),
            clock=lambda: NOW,
            auth=self.auth,
            history=HistoryService(backend.history, clock=lambda: NOW),
            oauth_clients={},
        )

    def social(self, provider: str, subject: str, email: str | None, verified: bool) -> tuple[TestClient, int]:
        """소셜 로그인 (콜백이 부르는 것과 같은 AuthService.social_login). 세션 쿠키를 실은 클라이언트."""
        login = self.auth.social_login(
            OAuthProfile(provider=provider, subject=subject, email=email, email_verified=verified, name=None), None
        )
        client = TestClient(self.app, base_url=BASE_URL)
        client.cookies.set(SESSION_COOKIE, login.token)
        return client, login.current.id

    def anonymous(self) -> TestClient:
        return TestClient(self.app, base_url=BASE_URL)


@pytest.fixture
def env(history_backend) -> Env:
    return Env(history_backend)


def search(client: TestClient, origin: str, dest: str, hour: int = 9) -> None:
    response = client.get("/api/routes", params={"from": origin, "to": dest, "arrive": kst(5, hour).isoformat(), "buffer": 10})
    assert response.status_code == 200, response.text


def routes(client: TestClient) -> list[tuple[str, str]]:
    response = client.get("/api/history")
    assert response.status_code == 200, response.text
    return [(card["from"], card["to"]) for card in response.json()]


def test_email_users_do_not_see_each_other(env):
    alice, _ = logged_in(env.app, "alice@example.com")
    bob, _ = logged_in(env.app, "bob@example.com")
    search(alice, "앨리스집", "앨리스회사")
    search(bob, "밥집", "밥학교")

    assert routes(alice) == [("앨리스집", "앨리스회사")]
    assert routes(bob) == [("밥집", "밥학교")]


def test_google_and_kakao_without_email_are_separate(env):
    google, google_id = env.social("google", "google-sub-1", "same.person@example.com", verified=True)
    kakao, kakao_id = env.social("kakao", "4000000001", None, verified=False)
    assert google_id != kakao_id
    search(google, "구글출발", "구글도착")
    search(kakao, "카카오출발", "카카오도착")

    assert routes(google) == [("구글출발", "구글도착")]
    assert routes(kakao) == [("카카오출발", "카카오도착")]


def test_kakao_with_same_unverified_email_is_a_separate_account_with_separate_history(env):
    """같은 사람이 같은 이메일로 두 제공자를 쓴 경우. 카카오 이메일이 미검증이면 email NULL의 새 계정이 된다."""
    google, google_id = env.social("google", "google-sub-2", "same@example.com", verified=True)
    kakao, kakao_id = env.social("kakao", "4000000002", "same@example.com", verified=False)
    assert google_id != kakao_id
    search(google, "같은사람구글", "목적지")

    assert routes(kakao) == []
    search(kakao, "같은사람카카오", "목적지")
    assert routes(google) == [("같은사람구글", "목적지")]
    assert routes(kakao) == [("같은사람카카오", "목적지")]


def test_two_social_users_without_email_are_separate(env):
    first, first_id = env.social("kakao", "4000000003", None, verified=False)
    second, second_id = env.social("kakao", "4000000004", None, verified=False)
    assert first_id != second_id
    search(first, "첫째", "도착")

    assert routes(second) == []
    assert routes(first) == [("첫째", "도착")]


def test_same_social_account_logs_into_same_user_and_keeps_history(env):
    client, user_id = env.social("google", "google-sub-3", "again@example.com", verified=True)
    search(client, "다시", "로그인")
    again, again_id = env.social("google", "google-sub-3", "again@example.com", verified=True)

    assert again_id == user_id
    assert routes(again) == [("다시", "로그인")]


def test_anonymous_search_returns_routes_but_stores_nothing(env):
    alice, _ = logged_in(env.app, "alice@example.com")
    before = env.backend.history_rows()
    search(env.anonymous(), "비로그인출발", "비로그인도착")

    assert env.backend.history_rows() == before  # INSERT가 없다
    assert routes(alice) == []


def test_anonymous_history_is_401(env):
    search(env.anonymous(), "비로그인출발", "비로그인도착")

    assert env.anonymous().get("/api/history").status_code == 401
    assert env.anonymous().delete("/api/history").status_code == 401


def test_session_switch_records_under_the_new_user(env):
    """같은 브라우저에서 계정을 바꾸면(이전 세션을 지우고 새 세션) 이후 검색은 새 사용자에게만 쌓인다."""
    client, google_id = env.social("google", "google-sub-4", "switch@example.com", verified=True)
    search(client, "구글때", "검색")
    kakao = env.auth.social_login(
        OAuthProfile(provider="kakao", subject="4000000005", email=None, email_verified=False, name=None),
        client.cookies.get(SESSION_COOKIE),
    )
    client.cookies.set(SESSION_COOKIE, kakao.token)
    search(client, "카카오때", "검색")

    assert routes(client) == [("카카오때", "검색")]
    owners = {owner for _, owner in env.backend.history_rows()}
    assert owners == {google_id, kakao.current.id}


def test_null_user_rows_are_never_listed(history_backend):
    """004 이전에 남은 user_id NULL 행. MySQL은 004 뒤로 NULL을 넣을 수 없으므로 메모리 저장소에서 시험한다."""
    if not hasattr(history_backend.history, "_rows"):
        pytest.skip("MySQL은 NOT NULL 제약으로 NULL 행을 만들 수 없다 (마이그레이션 004)")
    env = Env(history_backend)
    alice, alice_id = logged_in(env.app, "alice@example.com")
    search(alice, "앨리스", "도착")
    store = history_backend.history
    entry = next(iter(store._rows.values()))
    store._rows[999] = replace(entry, id=999, user_id=None, origin_name="NULL행")

    assert routes(alice) == [("앨리스", "도착")]
    bob, _ = logged_in(env.app, "bob@example.com")
    assert routes(bob) == []


def test_store_rejects_missing_user_id(history_backend):
    from app.history import HistoryDraft

    draft = HistoryDraft(origin_name="a", dest_name="b", arrive_at=kst(5, 9))
    with pytest.raises((TypeError, ValueError)):
        history_backend.history.add(None, draft, NOW)
