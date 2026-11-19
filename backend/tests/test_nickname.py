"""닉네임 변경 (PATCH /api/auth/me) 테스트.

- 규칙: app/auth/nickname.py. 프론트(frontend/js/mypage.js)와 결과가 같은지는 공용 사례 파일
  frontend/tests/fixtures/nickname-cases.json으로 확인한다 (프론트 테스트도 같은 파일을 읽는다).
- API 테스트는 store_backend fixture로 메모리와 MySQL(mysql_live)에서 같은 테스트를 돈다.
"""

import json
import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE
from app.auth.nickname import NICKNAME_MAX, NICKNAME_MESSAGES, NICKNAME_MIN, TRIM_CHARS, normalize_nickname
from app.auth.errors import AuthError
from app.auth.oauth import OAuthProfile
from tests.test_auth import BASE_URL, PASSWORD, login, make_env, signup

CASES_FILE = Path(__file__).resolve().parents[2] / "frontend" / "tests" / "fixtures" / "nickname-cases.json"
CASES = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]


# --- 규칙 (프론트와 같은 공용 사례) ---


@pytest.mark.parametrize("case", CASES, ids=[repr(case["input"])[:30] for case in CASES])
def test_rules_match_shared_cases(case):
    if case["ok"]:
        assert normalize_nickname(case["input"]) == case["value"]
    else:
        with pytest.raises(AuthError) as caught:
            normalize_nickname(case["input"])
        assert (caught.value.status, caught.value.code, caught.value.message) == (400, case["code"], NICKNAME_MESSAGES[case["code"]])


def test_rule_constants():
    assert (NICKNAME_MIN, NICKNAME_MAX) == (2, 20)
    # 프론트 String.prototype.trim()과 같은 집합: 파이썬 str.strip()과 다른 두 경우를 확인
    assert "﻿" in TRIM_CHARS and "\x1c" not in TRIM_CHARS
    assert set(NICKNAME_MESSAGES) == {"empty", "length", "chars", "spaces", "required"}


@pytest.mark.parametrize("value", [None, 12, ["길잇"], {"name": "길잇"}, True])
def test_non_string_is_empty(value):
    with pytest.raises(AuthError) as caught:
        normalize_nickname(value)
    assert caught.value.code == "empty"


# --- API ---


@pytest.fixture
def env(store_backend):
    return make_env(backend=store_backend)


def email_user(env, email: str = "user@example.com", name: str = "길잇") -> tuple[TestClient, str]:
    assert signup(env.client, email=email, name=name).status_code == 201
    client = env.new_client()
    response = login(client, email=email)
    assert response.status_code == 200, response.text
    return client, response.json()["id"]


def social_login(env, provider: str = "kakao", subject: str = "k-1", name: str | None = "카카오이름") -> tuple[TestClient, str]:
    """소셜 로그인 (콜백이 부르는 AuthService.social_login). 세션 쿠키를 실은 클라이언트."""
    result = env.app.state.auth.social_login(
        OAuthProfile(provider=provider, subject=subject, email=None, email_verified=False, name=name), None
    )
    client = env.new_client(cookies={SESSION_COOKIE: result.token})
    return client, str(result.current.id)


def patch_name(client: TestClient, name):
    return client.patch("/api/auth/me", json={"name": name})


def test_change_nickname_returns_updated_user_and_persists(env):
    client, user_id = email_user(env)

    response = patch_name(client, "길잇_01")

    assert response.status_code == 200
    assert response.json() == {"id": user_id, "name": "길잇_01", "email": "user@example.com", "provider": "email"}
    assert client.get("/api/auth/me").json()["name"] == "길잇_01"
    assert env.users.get_by_id(int(user_id)).nickname == "길잇_01"


def test_change_nickname_requires_login(env):
    response = env.new_client().patch("/api/auth/me", json={"name": "길잇_01"})
    assert response.status_code == 401
    assert response.json() == {"message": "로그인이 필요합니다."}


def test_unknown_session_is_401(env):
    response = env.new_client(cookies={SESSION_COOKIE: "nope"}).patch("/api/auth/me", json={"name": "길잇_01"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "name, code",
    [
        ("가", "length"),
        ("가" * 21, "length"),
        ("길잇.", "chars"),
        ("길잇@", "chars"),
        ("길잇😀", "chars"),
        ("ㅋㅋ", "chars"),
        ("길\t잇", "chars"),
        ("길\n잇", "chars"),
        ("길  잇", "spaces"),
        ("--", "required"),
        ("!#", "required"),
        ("", "empty"),
        ("   ", "empty"),
        (None, "empty"),
    ],
)
def test_rule_violations_are_400_with_code_and_keep_nickname(env, name, code):
    client, user_id = email_user(env)

    response = patch_name(client, name)

    assert response.status_code == 400
    assert response.json() == {"message": NICKNAME_MESSAGES[code], "code": code}
    assert env.users.get_by_id(int(user_id)).nickname == "길잇"


def test_missing_name_and_non_object_body_are_400(env):
    client, _ = email_user(env)
    assert client.patch("/api/auth/me", json={}).json() == {"message": NICKNAME_MESSAGES["empty"], "code": "empty"}
    assert client.patch("/api/auth/me", content=b"[1]", headers={"Content-Type": "application/json"}).status_code == 400


def test_trims_and_stores_nfc(env):
    client, user_id = email_user(env)

    nfd = unicodedata.normalize("NFD", "길잇 사용자")
    assert nfd != "길잇 사용자"
    response = patch_name(client, f"  {nfd}\t")

    assert response.status_code == 200
    assert response.json()["name"] == "길잇 사용자"
    stored = env.users.get_by_id(int(user_id)).nickname
    assert stored == "길잇 사용자" and unicodedata.is_normalized("NFC", stored)


def test_boundary_lengths(env):
    client, _ = email_user(env)
    assert patch_name(client, "가나").status_code == 200
    assert patch_name(client, "가" * 20).json()["name"] == "가" * 20


def test_duplicate_nickname_is_allowed(env):
    alice, _ = email_user(env, "alice@example.com", "앨리스")
    bob, _ = email_user(env, "bob@example.com", "밥밥")

    assert patch_name(alice, "같은이름").status_code == 200
    assert patch_name(bob, "같은이름").status_code == 200
    assert alice.get("/api/auth/me").json()["name"] == bob.get("/api/auth/me").json()["name"] == "같은이름"


def test_same_nickname_is_200_without_change(env, monkeypatch):
    client, user_id = email_user(env, name="길잇러")
    calls = []
    original = env.users.update_nickname
    monkeypatch.setattr(env.users, "update_nickname", lambda *args: calls.append(args) or original(*args))

    response = patch_name(client, " 길잇러 ")

    assert response.status_code == 200
    assert response.json()["name"] == "길잇러"
    assert calls == [], "같은 값이면 저장하지 않는다"


def test_existing_nickname_outside_rules_is_not_checked(env):
    """규칙은 변경 요청 값에만 적용한다. 예전 규칙으로 가입한 닉네임(예: 마침표)도 그대로 조회된다."""
    client, user_id = email_user(env, name="옛.닉네임")
    assert client.get("/api/auth/me").json()["name"] == "옛.닉네임"
    assert patch_name(client, "새닉네임").status_code == 200


def test_other_users_nickname_is_unchanged(env):
    alice, alice_id = email_user(env, "alice@example.com", "앨리스")
    bob, bob_id = email_user(env, "bob@example.com", "밥밥")

    assert patch_name(alice, "새앨리스").status_code == 200

    assert env.users.get_by_id(int(bob_id)).nickname == "밥밥"
    assert bob.get("/api/auth/me").json()["name"] == "밥밥"


def test_social_relogin_keeps_changed_nickname(env):
    """소셜 로그인은 처음 가입할 때만 제공자 이름을 쓴다. 다시 로그인해도 바꾼 닉네임이 유지된다."""
    client, user_id = social_login(env, name="카카오이름")
    assert client.get("/api/auth/me").json() == {"id": user_id, "name": "카카오이름", "email": None, "provider": "kakao"}
    assert patch_name(client, "내가정한이름").json()["provider"] == "kakao"

    again, again_id = social_login(env, name="카카오새이름")  # 제공자 쪽 이름이 바뀐 채로 다시 로그인

    assert again_id == user_id
    assert again.get("/api/auth/me").json()["name"] == "내가정한이름"
    assert env.users.get_by_id(int(user_id)).nickname == "내가정한이름"


def test_change_is_visible_to_other_sessions_of_same_user(env):
    first, _ = email_user(env)
    second = env.new_client()
    assert login(second).status_code == 200

    assert patch_name(first, "다른세션").status_code == 200

    assert second.get("/api/auth/me").json()["name"] == "다른세션"


def test_foreign_origin_is_403(env):
    client, user_id = email_user(env)
    response = client.patch("/api/auth/me", json={"name": "새닉네임"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert env.users.get_by_id(int(user_id)).nickname == "길잇"
