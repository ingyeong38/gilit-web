"""즐겨찾기 API 계약 테스트 (F9 1단계). favorites_backend fixture로 메모리(지금)와 MySQL(2단계)에서 같은 테스트를 돌린다.

사용자는 실제 회원가입·로그인 API로 만든다. 장소 검색은 가짜 provider로 흉내 내고 외부 API는 부르지 않는다.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE
from app.api.factory import create_app, place_locator
from app.auth import AuthService, PasswordHasher
from app.config import Settings
from app.departure import MockRouteProvider, ProviderTimeoutError
from app.favorites import FavoriteService
from tests.conftest import NOW

BASE_URL = "https://testserver"
PASSWORD = "gilit1234"
HOME = {"name": "집", "address": "경상남도 김해시 내외중앙로 47", "type": "집", "lat": 35.2285, "lng": 128.8894}


class PlacesProvider(MockRouteProvider):
    """장소 검색만 흉내 낸다 (카카오 모드의 search_places). 받은 검색어를 기록한다."""

    def __init__(self, places=None, error=None) -> None:
        super().__init__()
        self.places = places or []
        self.error = error
        self.queries: list[str] = []

    def search_places(self, query: str):
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.places


def place(name, address, lat, lng):
    return {"name": name, "address": address, "lat": lat, "lng": lng}


@dataclass
class FEnv:
    app: object
    backend: object
    provider: PlacesProvider
    alice: TestClient
    bob: TestClient

    def client(self, **kwargs) -> TestClient:
        return TestClient(self.app, base_url=BASE_URL, **kwargs)


def logged_in(app, email: str) -> TestClient:
    client = TestClient(app, base_url=BASE_URL)
    body = {"name": email.split("@")[0], "email": email, "password": PASSWORD, "agreeTerms": True, "agreePrivacy": True}
    assert client.post("/api/auth/signup", json=body).status_code == 201
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return client


def make_env(backend, provider=None) -> FEnv:
    provider = provider or PlacesProvider()
    auth = AuthService(backend.users, backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)
    favorites = FavoriteService(backend.favorites, locate=place_locator(provider), clock=lambda: NOW)
    app = create_app(Settings(), provider, clock=lambda: NOW, auth=auth, favorites=favorites)
    return FEnv(app, backend, provider, logged_in(app, "alice@example.com"), logged_in(app, "bob@example.com"))


@pytest.fixture
def env(favorites_backend) -> FEnv:
    return make_env(favorites_backend)


def add(client: TestClient, **overrides):
    body = {**HOME, **overrides}
    return client.post("/api/favorites", json={k: v for k, v in body.items() if v is not ...})


def names(client: TestClient) -> list[str]:
    response = client.get("/api/favorites")
    assert response.status_code == 200
    return [item["name"] for item in response.json()]


# --- 목록·추가 ---


def test_empty_list(env):
    response = env.alice.get("/api/favorites")

    assert response.status_code == 200
    assert response.json() == []


def test_add_with_coordinates_and_list(env):
    response = add(env.alice)

    assert response.status_code == 201
    body = response.json()
    assert body.pop("id").isdigit()  # DB BIGINT를 문자열로
    assert body == {"name": "집", "address": "경상남도 김해시 내외중앙로 47", "type": "집", "lat": 35.2285, "lng": 128.8894}
    listed = env.alice.get("/api/favorites").json()
    assert listed == [response.json()]
    assert env.provider.queries == []  # 좌표가 있으면 장소 검색을 하지 않는다


def test_list_keeps_insertion_order(env):
    for name in ("집", "학교", "회사"):
        assert add(env.alice, name=name).status_code == 201

    assert names(env.alice) == ["집", "학교", "회사"]


def test_add_defaults_and_cleanup(env):
    response = add(env.alice, name="  우리   집 ", type=..., address=...)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "우리 집"  # 앞뒤 공백 제거, 연속 공백 하나로
    assert body["type"] == "기타"  # 분류를 생략하면 기타
    assert body["address"] is None


def test_blank_address_is_stored_as_null(env):
    assert add(env.alice, address="   ").json()["address"] is None


def test_integer_coordinates_are_accepted(env):
    body = add(env.alice, lat=35, lng=129).json()

    assert (body["lat"], body["lng"]) == (35.0, 129.0)


# --- 좌표 없이 추가 (장소 확정) ---


def test_add_without_coordinates_uses_single_search_result(favorites_backend):
    provider = PlacesProvider([place("동의대학교", "부산광역시 부산진구 엄광로 176", 35.1441, 129.0336)])
    env = make_env(favorites_backend, provider)

    response = add(env.alice, name="학교", address="부산광역시 부산진구 엄광로 176", type="학교", lat=..., lng=...)

    assert response.status_code == 201
    assert (response.json()["lat"], response.json()["lng"]) == (35.1441, 129.0336)
    assert provider.queries == ["부산광역시 부산진구 엄광로 176"]  # 주소로 찾는다


def test_add_without_address_searches_by_name(favorites_backend):
    provider = PlacesProvider([place("부산역", "부산광역시 동구 중앙대로 206", 35.1151, 129.0414)])
    env = make_env(favorites_backend, provider)

    response = add(env.alice, name="부산역", address=..., lat=..., lng=...)

    assert response.status_code == 201
    assert provider.queries == ["부산역"]


def test_exact_match_wins_among_several_results(favorites_backend):
    provider = PlacesProvider(
        [
            place("부산역", "부산광역시 동구 중앙대로 206", 35.1151, 129.0414),
            place("부산역 광장", "부산광역시 동구 초량동", 35.1150, 129.0420),
        ]
    )
    env = make_env(favorites_backend, provider)

    response = add(env.alice, name="부산역", address=..., lat=..., lng=...)

    assert response.status_code == 201
    assert response.json()["lat"] == 35.1151


NOT_FOUND_MESSAGE = {"message": "장소 위치를 찾을 수 없습니다. 장소를 검색해서 선택해 주세요."}


@pytest.mark.parametrize(
    "provider",
    [
        PlacesProvider([]),  # 결과 없음
        PlacesProvider([place("서면역 1번출구", "a", 35.1, 129.0), place("서면역 2번출구", "b", 35.2, 129.1)]),  # 여러 개
    ],
)
def test_add_without_coordinates_fails_when_not_exactly_one(favorites_backend, provider):
    env = make_env(favorites_backend, provider)

    response = add(env.alice, name="서면", address=..., lat=..., lng=...)

    assert response.status_code == 400
    assert response.json() == NOT_FOUND_MESSAGE
    assert names(env.alice) == []


def test_add_without_coordinates_in_mock_mode_is_400(favorites_backend):
    """mock 길찾기에는 장소 검색이 없다."""
    auth = AuthService(favorites_backend.users, favorites_backend.sessions, PasswordHasher(rounds=4), clock=lambda: NOW)
    service = FavoriteService(favorites_backend.favorites, locate=place_locator(MockRouteProvider()), clock=lambda: NOW)
    app = create_app(Settings(), MockRouteProvider(), clock=lambda: NOW, auth=auth, favorites=service)
    client = logged_in(app, "carol@example.com")

    response = add(client, lat=..., lng=...)

    assert response.status_code == 400
    assert response.json() == NOT_FOUND_MESSAGE


def test_place_search_outage_is_not_reported_as_not_found(favorites_backend):
    """길찾기 API 장애는 '못 찾음'(400)이 아니라 공통 오류(504 등)로 알린다."""
    env = make_env(favorites_backend, PlacesProvider(error=ProviderTimeoutError("응답 시간 초과")))

    response = add(env.alice, lat=..., lng=...)

    assert response.status_code == 504
    assert names(env.alice) == []


# --- 이름 중복·개수 제한 ---

NAME_TAKEN = {"message": "이미 같은 이름의 즐겨찾기가 있습니다."}
LIMIT = {"message": "즐겨찾기는 최대 20개까지 저장할 수 있습니다."}


@pytest.mark.parametrize(("first", "second"), [("집", "집"), ("Home", "home"), ("HOME", " home "), ("Café", "cafe")])
def test_same_name_for_same_user_is_409(env, first, second):
    assert add(env.alice, name=first).status_code == 201

    response = add(env.alice, name=second, lat=35.0, lng=129.0)

    assert response.status_code == 409
    assert response.json() == NAME_TAKEN
    assert names(env.alice) == [first]


def test_same_name_is_allowed_for_other_user_and_same_place_other_name(env):
    assert add(env.alice, name="집").status_code == 201
    assert add(env.bob, name="집").status_code == 201
    assert add(env.alice, name="우리집 근처").status_code == 201  # 같은 좌표, 다른 이름은 허용


def test_twenty_first_favorite_is_409(env):
    for i in range(20):
        assert add(env.alice, name=f"장소{i}").status_code == 201

    response = add(env.alice, name="스물한번째")

    assert response.status_code == 409
    assert response.json() == LIMIT
    assert len(names(env.alice)) == 20
    assert add(env.bob, name="밥의 첫 장소").status_code == 201  # 다른 사용자는 따로 센다


def test_limit_frees_up_after_delete(env):
    ids = [add(env.alice, name=f"장소{i}").json()["id"] for i in range(20)]
    assert env.alice.delete("/api/favorites", params={"id": ids[0]}).status_code == 204

    assert add(env.alice, name="새 장소").status_code == 201


def test_concurrent_adds_never_exceed_limit(env):
    token = env.alice.cookies.get(SESSION_COOKIE)
    workers = 30
    barrier = threading.Barrier(workers)

    def attempt(i: int) -> int:
        client = env.client(cookies={SESSION_COOKIE: token})
        barrier.wait()
        return add(client, name=f"동시{i}").status_code

    with ThreadPoolExecutor(workers) as pool:
        statuses = list(pool.map(attempt, range(workers)))

    assert statuses.count(201) == 20
    assert statuses.count(409) == 10
    assert len(names(env.alice)) == 20


def test_concurrent_adds_with_same_name_create_one(env):
    token = env.alice.cookies.get(SESSION_COOKIE)
    workers = 10
    barrier = threading.Barrier(workers)

    def attempt(_):
        client = env.client(cookies={SESSION_COOKIE: token})
        barrier.wait()
        return add(client, name="집").status_code

    with ThreadPoolExecutor(workers) as pool:
        statuses = list(pool.map(attempt, range(workers)))

    assert sorted(statuses) == [201] + [409] * (workers - 1)
    assert names(env.alice) == ["집"]


# --- 수정 ---


def test_patch_name_and_type(env):
    favorite_id = add(env.alice).json()["id"]

    response = env.alice.patch("/api/favorites", params={"id": favorite_id}, json={"name": "우리 집", "type": "기타"})

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["name"], body["type"]) == (favorite_id, "우리 집", "기타")
    assert (body["address"], body["lat"], body["lng"]) == (HOME["address"], HOME["lat"], HOME["lng"])  # 나머지는 그대로
    assert env.alice.get("/api/favorites").json() == [body]


def test_patch_place_requires_address_and_coordinates_together(env):
    favorite_id = add(env.alice).json()["id"]

    moved = env.alice.patch(
        "/api/favorites", params={"id": favorite_id}, json={"address": "부산광역시 동구 중앙대로 206", "lat": 35.1151, "lng": 129.0414}
    )
    cleared = env.alice.patch("/api/favorites", params={"id": favorite_id}, json={"address": None, "lat": 35.0, "lng": 129.0})
    partial = env.alice.patch("/api/favorites", params={"id": favorite_id}, json={"lat": 35.0, "lng": 129.0})

    assert moved.status_code == 200
    assert (moved.json()["address"], moved.json()["lat"]) == ("부산광역시 동구 중앙대로 206", 35.1151)
    assert cleared.status_code == 200 and cleared.json()["address"] is None
    assert partial.status_code == 400
    assert partial.json() == {"message": "장소를 바꿀 때는 address, lat, lng를 함께 보내 주세요."}


def test_patch_rename_to_other_favorite_name_is_409(env):
    add(env.alice, name="집")
    school = add(env.alice, name="학교").json()["id"]

    response = env.alice.patch("/api/favorites", params={"id": school}, json={"name": "집"})

    assert response.status_code == 409
    assert response.json() == NAME_TAKEN
    assert names(env.alice) == ["집", "학교"]


def test_patch_same_name_with_different_case_is_allowed(env):
    favorite_id = add(env.alice, name="home").json()["id"]

    response = env.alice.patch("/api/favorites", params={"id": favorite_id}, json={"name": "Home"})

    assert response.status_code == 200
    assert response.json()["name"] == "Home"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({}, "바꿀 내용이 없습니다."),
        ({"unknown": 1}, "바꿀 내용이 없습니다."),
        ({"name": ""}, "장소 이름은 1~100자로 입력해 주세요."),
        ({"type": None}, "분류는 집, 학교, 회사, 기타 중 하나여야 합니다."),
        ({"type": "공원"}, "분류는 집, 학교, 회사, 기타 중 하나여야 합니다."),
        ({"address": "x", "lat": None, "lng": None}, "위도와 경도는 함께, 올바른 범위의 숫자로 보내 주세요."),
    ],
)
def test_patch_validation(env, body, message):
    favorite_id = add(env.alice).json()["id"]

    response = env.alice.patch("/api/favorites", params={"id": favorite_id}, json=body)

    assert response.status_code == 400
    assert response.json() == {"message": message}


# --- 삭제 ---


def test_delete_then_gone(env):
    favorite_id = add(env.alice).json()["id"]

    first = env.alice.delete("/api/favorites", params={"id": favorite_id})
    second = env.alice.delete("/api/favorites", params={"id": favorite_id})

    assert first.status_code == 204
    assert first.content == b""
    assert second.status_code == 404
    assert names(env.alice) == []


# --- 본인 데이터만 ---

NOT_FOUND = {"message": "찾을 수 없습니다."}


def test_other_users_favorites_are_invisible_and_untouchable(env):
    mine = add(env.alice).json()

    listed = env.bob.get("/api/favorites").json()
    patched = env.bob.patch("/api/favorites", params={"id": mine["id"]}, json={"name": "가로채기"})
    deleted = env.bob.delete("/api/favorites", params={"id": mine["id"]})

    assert listed == []
    assert (patched.status_code, patched.json()) == (404, NOT_FOUND)
    assert (deleted.status_code, deleted.json()) == (404, NOT_FOUND)
    assert env.alice.get("/api/favorites").json() == [mine]  # 원래 데이터 그대로


@pytest.mark.parametrize("bad_id", [None, "", "abc", "1.0", "-1", "0", "١", "99999999999999999999", "1 OR 1=1"])
def test_invalid_or_missing_id_is_404(env, bad_id):
    add(env.alice)
    params = {} if bad_id is None else {"id": bad_id}

    patched = env.alice.patch("/api/favorites", params=params, json={"name": "새이름"})
    deleted = env.alice.delete("/api/favorites", params=params)

    assert (patched.status_code, patched.json()) == (404, NOT_FOUND)
    assert (deleted.status_code, deleted.json()) == (404, NOT_FOUND)
    assert names(env.alice) == ["집"]


def test_unknown_numeric_id_is_404(env):
    assert env.alice.delete("/api/favorites", params={"id": "123456"}).status_code == 404


# --- 비로그인 ---


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("get", {}),
        ("post", {"json": HOME}),
        ("patch", {"params": {"id": "1"}, "json": {"name": "x"}}),
        ("delete", {"params": {"id": "1"}}),
    ],
)
def test_anonymous_requests_are_401(env, method, kwargs):
    add(env.alice)
    anonymous = env.client()

    response = getattr(anonymous, method)("/api/favorites", **kwargs)

    assert response.status_code == 401
    assert response.json() == {"message": "로그인이 필요합니다."}
    assert names(env.alice) == ["집"]


def test_logged_out_session_is_401(env):
    add(env.alice)
    env.alice.post("/api/auth/logout")

    assert env.alice.get("/api/favorites").status_code == 401


# --- 입력 검증 ---

NAME_MSG = "장소 이름은 1~100자로 입력해 주세요."
TYPE_MSG = "분류는 집, 학교, 회사, 기타 중 하나여야 합니다."
ADDRESS_MSG = "주소는 255자 이하로 입력해 주세요."
COORD_MSG = "위도와 경도는 함께, 올바른 범위의 숫자로 보내 주세요."


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": ...}, NAME_MSG),
        ({"name": ""}, NAME_MSG),
        ({"name": "   "}, NAME_MSG),
        ({"name": "가" * 101}, NAME_MSG),
        ({"name": 123}, NAME_MSG),
        ({"name": "집\n앞"}, NAME_MSG),  # 제어 문자
        ({"name": "집​"}, NAME_MSG),  # 제로폭 공백
        ({"type": "공원"}, TYPE_MSG),
        ({"type": 1}, TYPE_MSG),
        ({"address": "가" * 256}, ADDRESS_MSG),
        ({"address": 47}, ADDRESS_MSG),
        ({"lat": ...}, COORD_MSG),  # 하나만
        ({"lng": None}, COORD_MSG),
        ({"lat": 90.1}, COORD_MSG),
        ({"lng": -180.5}, COORD_MSG),
        ({"lat": "35.2"}, COORD_MSG),  # 문자열 숫자는 받지 않는다
        ({"lat": True}, COORD_MSG),
    ],
)
def test_add_validation_messages(env, overrides, message):
    response = add(env.alice, **overrides)

    assert response.status_code == 400
    assert response.json() == {"message": message}
    assert names(env.alice) == []


def test_name_error_is_not_route_place_message(env):
    """공통 오류 변환의 '장소 이름은 1~100자' 문구와 같은 문장이지만 즐겨찾기 검증에서 나온다 (Pydantic을 거치지 않음)."""
    response = env.alice.post("/api/favorites", json={"type": "집"})

    assert response.json() == {"message": NAME_MSG}


def test_nan_coordinate_is_rejected(env):
    response = env.alice.post(
        "/api/favorites", content=b'{"name": "x", "lat": NaN, "lng": 129.0}', headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json() == {"message": COORD_MSG}


def test_boundary_values_are_accepted(env):
    assert add(env.alice, name="가" * 100, address="나" * 255, lat=90, lng=-180).status_code == 201
    assert add(env.alice, name="남극", lat=-90.0, lng=180.0).status_code == 201


@pytest.mark.parametrize("content", [b"[1, 2]", b'"text"', b"{not json"])
def test_body_must_be_json_object(env, content):
    response = env.alice.post("/api/favorites", content=content, headers={"Content-Type": "application/json"})

    assert response.status_code == 400
    assert response.json() == {"message": "요청 본문은 JSON 객체여야 합니다."}


def test_other_origin_post_is_403(env):
    response = env.alice.post("/api/favorites", json=HOME, headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert names(env.alice) == []


# --- 앱 구성 ---


def test_memory_store_is_default():
    from app.favorites import MemoryFavoriteStore

    app = create_app(Settings(), MockRouteProvider())

    assert isinstance(app.state.favorites.store, MemoryFavoriteStore)
    assert app.state.db_pool is None


def test_mysql_settings_share_one_pool_and_favorites_wait_for_stage_2():
    """AUTH_STORE=mysql이면 factory가 연결 풀 하나를 만들어 회원 저장소들이 함께 쓴다 (연결은 처음 쓸 때)."""
    settings = Settings.from_env(
        {"AUTH_STORE": "mysql", "DB_HOST": "db.invalid", "DB_NAME": "gilit", "DB_USER": "gilit_app", "DB_PASSWORD": "pw"}
    )

    app = create_app(settings, MockRouteProvider())

    assert app.state.db_pool is not None
    assert app.state.auth.users.pool is app.state.db_pool
    assert app.state.auth.sessions.pool is app.state.db_pool
    assert app.state.favorites is None  # MySQL 즐겨찾기 저장소는 2단계


def test_favorites_api_is_503_when_store_is_unavailable(env):
    env.app.state.favorites = None

    response = env.alice.get("/api/favorites")

    assert response.status_code == 503
    assert response.json() == {"message": "즐겨찾기를 지금 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."}
    assert env.alice.get("/api/auth/me").status_code == 200  # 인증은 그대로 동작한다
