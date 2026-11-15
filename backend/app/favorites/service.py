"""즐겨찾기 서비스. 검증된 입력을 받아 좌표를 확정하고 저장소에 맡긴다.

좌표가 없으면 locate(검색어)로 찾는다. 웹 앱은 경로 API의 resolve_place(장소 검색 결과가 정확히 하나일 때만)를 넣는다.
locate가 None을 돌려주면(못 찾음, 여러 개, mock 모드) 400이다. 길찾기 API 자체의 장애(시간 초과 등)는 그대로 올려
공통 오류 처리(502·503·504)에 맡긴다.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.departure import KST
from app.favorites.errors import (
    LIMIT_REACHED,
    NAME_TAKEN,
    NOT_FOUND,
    PLACE_NOT_FOUND,
    FavoriteError,
    FavoriteLimitError,
    FavoriteNameTakenError,
    FavoriteOwnerMissingError,
)
from app.auth.errors import LOGIN_REQUIRED
from app.favorites.stores import MAX_FAVORITES, Favorite, FavoriteDraft, FavoriteStore
from app.favorites.validation import Coordinates, validate_changes, validate_new

Locate = Callable[[str], Coordinates | None]


def _no_locate(query: str) -> Coordinates | None:
    return None


class FavoriteService:
    def __init__(
        self,
        store: FavoriteStore,
        locate: Locate | None = None,
        clock: Callable[[], datetime] | None = None,
        limit: int = MAX_FAVORITES,
    ) -> None:
        self.store = store
        self._locate = locate or _no_locate
        self._clock = clock or (lambda: datetime.now(KST))
        self.limit = limit

    def list(self, user_id: int) -> list[Favorite]:
        return self.store.list(user_id)

    def add(self, user_id: int, payload: dict[str, Any]) -> Favorite:
        data = validate_new(payload)
        coordinates = data.coordinates or self._locate(data.address or data.name)
        if coordinates is None:
            raise FavoriteError(400, PLACE_NOT_FOUND)
        draft = FavoriteDraft(name=data.name, type=data.type, address=data.address, coordinates=coordinates)
        try:
            return self.store.add(user_id, draft, self._clock(), limit=self.limit)
        except FavoriteNameTakenError:
            raise FavoriteError(409, NAME_TAKEN) from None
        except FavoriteLimitError:
            raise FavoriteError(409, LIMIT_REACHED) from None
        except FavoriteOwnerMissingError:
            raise FavoriteError(401, LOGIN_REQUIRED) from None

    def update(self, user_id: int, favorite_id: int | None, payload: dict[str, Any]) -> Favorite:
        if favorite_id is None:
            raise FavoriteError(404, NOT_FOUND)
        changes = validate_changes(payload)
        try:
            updated = self.store.update(user_id, favorite_id, name=changes.name, type=changes.type, place=changes.place)
        except FavoriteNameTakenError:
            raise FavoriteError(409, NAME_TAKEN) from None
        if updated is None:
            raise FavoriteError(404, NOT_FOUND)
        return updated

    def delete(self, user_id: int, favorite_id: int | None) -> None:
        if favorite_id is None or not self.store.delete(user_id, favorite_id):
            raise FavoriteError(404, NOT_FOUND)


def create_favorite_store(store: str, pool=None) -> FavoriteStore | None:
    """AUTH_STORE에 맞는 즐겨찾기 저장소. mysql은 factory가 만든 연결 풀(회원 저장소와 같은 풀)을 쓴다.

    None을 돌려주면 즐겨찾기 API는 503이다 (알 수 없는 저장소 이름 등. 설정 검사에서 먼저 막힌다).
    """
    if store == "memory":
        from app.favorites.stores import MemoryFavoriteStore

        return MemoryFavoriteStore()
    if store == "mysql":
        if pool is None:
            raise ValueError("AUTH_STORE=mysql 즐겨찾기 저장소에는 연결 풀이 필요합니다.")
        from app.favorites.mysql_stores import MySQLFavoriteStore

        return MySQLFavoriteStore(pool)
    return None
