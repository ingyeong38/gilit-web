"""FavoriteStore의 MySQL 구현 (AUTH_STORE=mysql). 테이블은 db/schema.sql의 favorite_places (마이그레이션 003 필요).

- 모든 쿼리에 user_id 조건을 넣는다 (WHERE id = %s AND user_id = %s). 남의 id는 없는 id와 같다.
- 추가: 한 트랜잭션에서 users 행을 SELECT ... FOR UPDATE로 잠근 뒤 중복·개수를 확인하고 INSERT한다.
  같은 사용자의 추가 요청은 이 잠금에서 한 줄로 서므로 동시에 와도 20개를 넘지 않는다. 다른 사용자끼리는 막지 않는다.
- 이름 중복은 DB 콜레이션(utf8mb4_0900_ai_ci)으로 비교한다 (UNIQUE와 같은 규칙). UNIQUE 위반(1062)도 409로 바꾼다.
- 좌표는 DECIMAL(10,7)이다. 검증 단계에서 소수 7자리로 맞추므로 저장한 값과 응답 값이 같다.
"""

from datetime import datetime

from app.db import ConnectionPool, from_db, is_duplicate_entry, to_db
from app.favorites.errors import FavoriteLimitError, FavoriteNameTakenError, FavoriteOwnerMissingError
from app.favorites.stores import MAX_FAVORITES, Favorite, FavoriteDraft
from app.favorites.validation import Coordinates

COLUMNS = "id, user_id, place_name, label, address, lat, lng, created_at"
UNIQUE_NAME_KEY = "uq_favorite_user_name"


def _favorite(row: dict | None) -> Favorite | None:
    if row is None:
        return None
    return Favorite(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        name=row["place_name"],
        type=row["label"],
        address=row["address"],
        lat=float(row["lat"]),
        lng=float(row["lng"]),
        created_at=from_db(row["created_at"]),
    )


class MySQLFavoriteStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def list(self, user_id: int) -> list[Favorite]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {COLUMNS} FROM favorite_places WHERE user_id = %s ORDER BY created_at, id", (user_id,))
            return [_favorite(row) for row in cur.fetchall()]

    def add(self, user_id: int, draft: FavoriteDraft, now: datetime, limit: int = MAX_FAVORITES) -> Favorite:
        at = to_db(now)
        try:
            with self.pool.connection() as conn, conn.cursor() as cur:
                # 이 사용자의 추가를 한 줄로 세운다 (트랜잭션이 끝날 때 풀린다).
                cur.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
                if cur.fetchone() is None:
                    raise FavoriteOwnerMissingError(user_id)
                cur.execute(
                    "SELECT COUNT(*) AS total, COALESCE(SUM(place_name = %s), 0) AS same_name "
                    "FROM favorite_places WHERE user_id = %s",
                    (draft.name, user_id),
                )
                counts = cur.fetchone()
                if int(counts["same_name"]) > 0:
                    raise FavoriteNameTakenError(draft.name)
                if int(counts["total"]) >= limit:
                    raise FavoriteLimitError(limit)
                cur.execute(
                    "INSERT INTO favorite_places (user_id, label, place_name, address, lat, lng, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (user_id, draft.type, draft.name, draft.address, draft.coordinates.lat, draft.coordinates.lng, at),
                )
                favorite_id = cur.lastrowid
        except Exception as error:
            if is_duplicate_entry(error, UNIQUE_NAME_KEY):  # 이중 안전망 (잠금을 거치지 않은 쓰기 등)
                raise FavoriteNameTakenError(draft.name) from None
            raise
        return Favorite(
            id=int(favorite_id),
            user_id=user_id,
            name=draft.name,
            type=draft.type,
            address=draft.address,
            lat=draft.coordinates.lat,
            lng=draft.coordinates.lng,
            created_at=from_db(at),
        )

    def update(
        self,
        user_id: int,
        favorite_id: int,
        name: str | None = None,
        type: str | None = None,
        place: tuple[str | None, Coordinates] | None = None,
    ) -> Favorite | None:
        # 열 이름은 코드에 고정된 것만 쓴다. 값은 모두 바인딩한다.
        assignments: list[str] = []
        values: list = []
        if name is not None:
            assignments.append("place_name = %s")
            values.append(name)
        if type is not None:
            assignments.append("label = %s")
            values.append(type)
        if place is not None:
            address, coordinates = place
            assignments += ["address = %s", "lat = %s", "lng = %s"]
            values += [address, coordinates.lat, coordinates.lng]
        try:
            with self.pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    f"SELECT {COLUMNS} FROM favorite_places WHERE id = %s AND user_id = %s FOR UPDATE", (favorite_id, user_id)
                )
                if cur.fetchone() is None:
                    return None
                if assignments:
                    cur.execute(
                        f"UPDATE favorite_places SET {', '.join(assignments)} WHERE id = %s AND user_id = %s",
                        (*values, favorite_id, user_id),
                    )
                cur.execute(f"SELECT {COLUMNS} FROM favorite_places WHERE id = %s AND user_id = %s", (favorite_id, user_id))
                return _favorite(cur.fetchone())
        except Exception as error:
            # 다른 즐겨찾기와 같은 이름 (자기 자신의 대소문자만 바꾸는 것은 같은 행이라 위반이 아니다)
            if is_duplicate_entry(error, UNIQUE_NAME_KEY):
                raise FavoriteNameTakenError(name) from None
            raise

    def delete(self, user_id: int, favorite_id: int) -> bool:
        with self.pool.connection() as conn, conn.cursor() as cur:
            return cur.execute("DELETE FROM favorite_places WHERE id = %s AND user_id = %s", (favorite_id, user_id)) > 0
