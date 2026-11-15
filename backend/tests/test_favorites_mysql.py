"""즐겨찾기 MySQL 저장소 전용 테스트 (마이그레이션 003의 제약, 외래키, 콜레이션 대조).

계약 테스트(test_favorites.py)는 favorites_backend로 메모리·MySQL 양쪽에서 돈다. 여기는 DB에만 있는 동작이다.
이름 비교 대조 표(COLLATION_PAIRS)는 메모리 쪽 name_key를 기본 실행에서도 검사한다.
"""

from datetime import timedelta

import pymysql
import pytest

from app.favorites import Coordinates, FavoriteDraft
from app.favorites.errors import FavoriteNameTakenError, FavoriteOwnerMissingError
from app.favorites.validation import name_key
from tests.auth_backends import make_backend, mysql_live
from tests.conftest import NOW

# (a, b, MySQL utf8mb4_0900_ai_ci가 같다고 보는지). MySQL 8.0.46에서 확인한 결과다.
COLLATION_PAIRS = [
    ("Home", "home", True),
    ("HOME", "home", True),
    ("Café", "cafe", True),
    ("café", "CAFÉ", True),
    ("Straße", "strasse", True),
    ("Ａ", "A", True),  # 전각
    ("Ｈｏｍｅ", "home", True),
    ("２", "2", True),
    ("집1", "집１", True),
    ("①", "1", True),  # 원문자
    ("ﬁ", "fi", True),  # 합자
    ("æ", "ae", True),
    ("Æ", "ae", True),
    ("œ", "oe", True),
    ("ø", "o", True),  # 획이 그어진 글자
    ("Ø", "o", True),
    ("Đ", "d", True),
    ("Ł", "l", True),
    ("ä", "a", True),
    ("İ", "i", True),
    ("Ⅳ", "iv", True),
    ("㎞", "km", True),
    ("ｶ", "カ", True),
    ("Ω", "ω", True),
    ("Ω", "Ω", True),  # 옴 기호와 그리스 문자
    ("집", "집", True),  # 조합형 자모로 쓴 '집'
    ("집", "짚", False),
    ("집", "팁", False),
    ("ı", "i", False),
    ("회사", "회 사", False),
    ("우리집", "우리 집", False),
    ("a b", "a  b", False),
    ("O'Neil", "oneil", False),
    ("학교", "學校", False),
]


@pytest.mark.parametrize(("a", "b", "same"), COLLATION_PAIRS)
def test_memory_name_key_matches_recorded_mysql_collation(a, b, same):
    """메모리 저장소의 중복 판단이 MySQL과 같은 결과를 낸다 (기본 실행에서도 돈다)."""
    assert (name_key(a) == name_key(b)) is same


@pytest.fixture
def mysql_backend():
    backend = make_backend("mysql", favorites=True)
    yield backend
    backend.close()


def mysql_test(func):
    """mysql_live 마커와 'DB 설정 없으면 건너뛰기'를 붙인다 (기본 pytest에서는 빠진다)."""
    for mark in mysql_live:
        func = mark(func)
    return func


@mysql_test
@pytest.mark.parametrize(("a", "b", "same"), COLLATION_PAIRS)
def test_recorded_pairs_still_match_live_collation(mysql_backend, a, b, same):
    """MySQL 버전이 바뀌어 콜레이션 결과가 달라지면 여기서 알 수 있다."""
    (row,) = mysql_backend.execute(
        "SELECT (%s COLLATE utf8mb4_0900_ai_ci) = (%s COLLATE utf8mb4_0900_ai_ci) AS same", (a, b)
    )
    assert bool(row["same"]) is same


def user(backend, email="owner@example.com"):
    return backend.users.create_email_user(email, "$2b$04$" + "x" * 53, "주인", NOW)


def draft(name="집", type_="집", lat=35.2285, lng=128.8894):
    return FavoriteDraft(name=name, type=type_, address="주소", coordinates=Coordinates(lat, lng))


@mysql_test
def test_migration_003_structure(mysql_backend):
    indexes = {
        (row["INDEX_NAME"], row["cols"], int(row["NON_UNIQUE"]))
        for row in mysql_backend.execute(
            "SELECT INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS cols, NON_UNIQUE "
            "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'favorite_places' "
            "GROUP BY INDEX_NAME, NON_UNIQUE"
        )
    }

    assert ("uq_favorite_user_name", "user_id,place_name", 0) in indexes
    assert not any(name == "idx_favorite_user" for name, _, _ in indexes)  # UNIQUE가 FK 인덱스를 대신한다


@mysql_test
def test_unique_name_rejects_collation_equal_names_at_db_level(mysql_backend):
    owner = user(mysql_backend)
    mysql_backend.execute(
        "INSERT INTO favorite_places (user_id, label, place_name, lat, lng) VALUES (%s, '집', 'Café', 35, 129)", (owner.id,)
    )

    with pytest.raises(pymysql.err.IntegrityError) as caught:
        mysql_backend.execute(
            "INSERT INTO favorite_places (user_id, label, place_name, lat, lng) VALUES (%s, '집', 'CAFE', 35, 129)", (owner.id,)
        )

    assert caught.value.args[0] == 1062
    assert "uq_favorite_user_name" in caught.value.args[1]


@mysql_test
def test_check_constraint_rejects_unknown_label(mysql_backend):
    owner = user(mysql_backend)

    with pytest.raises(pymysql.err.OperationalError) as caught:  # CHECK 위반은 3819
        mysql_backend.execute(
            "INSERT INTO favorite_places (user_id, label, place_name, lat, lng) VALUES (%s, '공원', 'x', 35, 129)", (owner.id,)
        )

    assert caught.value.args[0] == 3819
    assert "chk_favorite_label" in caught.value.args[1]


@mysql_test
def test_duplicate_entry_on_rename_becomes_name_taken(mysql_backend):
    """UPDATE는 미리 검사하지 않고 UNIQUE 위반(1062)을 409로 바꾼다 (이중 안전망)."""
    owner = user(mysql_backend)
    store = mysql_backend.favorites
    store.add(owner.id, draft("집"), NOW)
    school = store.add(owner.id, draft("학교", "학교"), NOW)

    with pytest.raises(FavoriteNameTakenError):
        store.update(owner.id, school.id, name="집")

    assert [f.name for f in store.list(owner.id)] == ["집", "학교"]


@mysql_test
def test_deleting_user_cascades_favorites(mysql_backend):
    owner = user(mysql_backend)
    other = user(mysql_backend, "other@example.com")
    mysql_backend.favorites.add(owner.id, draft("집"), NOW)
    mysql_backend.favorites.add(other.id, draft("집"), NOW)

    mysql_backend.execute("DELETE FROM users WHERE id = %s", (owner.id,))

    (row,) = mysql_backend.execute("SELECT COUNT(*) AS n FROM favorite_places WHERE user_id = %s", (owner.id,))
    assert row["n"] == 0
    assert [f.name for f in mysql_backend.favorites.list(other.id)] == ["집"]  # 다른 사용자 것은 그대로


@mysql_test
def test_add_for_missing_user_is_owner_missing(mysql_backend):
    with pytest.raises(FavoriteOwnerMissingError):
        mysql_backend.favorites.add(987654321, draft(), NOW)


@mysql_test
def test_values_round_trip_including_kst_time_and_decimal(mysql_backend):
    owner = user(mysql_backend)
    created_at = NOW + timedelta(hours=3, microseconds=999_999)

    added = mysql_backend.favorites.add(owner.id, draft("🏠 우리집", "기타", 35.1234567, -129.7654321), created_at)

    (stored,) = mysql_backend.favorites.list(owner.id)
    assert stored == added
    assert stored.created_at == (NOW + timedelta(hours=3)).replace(microsecond=0)  # 초 단위, KST
    assert (stored.lat, stored.lng) == (35.1234567, -129.7654321)
    (row,) = mysql_backend.execute("SELECT CAST(created_at AS CHAR) AS c FROM favorite_places WHERE id = %s", (added.id,))
    assert row["c"] == "2026-11-04 09:00:00"
