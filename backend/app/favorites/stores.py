"""즐겨찾기 저장소. 프로토콜과 메모리 구현 (MySQL 구현은 2단계, favorite_places 테이블).

모든 메서드의 첫 인자는 user_id다. 저장소는 항상 "이 사용자의" 행만 찾고 바꾼다 (SQL은 WHERE id = ? AND user_id = ?).
id로 먼저 가져온 뒤 주인을 비교하지 않으므로, 남의 id는 없는 id와 똑같이 None·False가 된다 (API는 404).
"""

import threading
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from app.favorites.errors import FavoriteLimitError, FavoriteNameTakenError
from app.favorites.validation import Coordinates, name_key

MAX_FAVORITES = 20


@dataclass(frozen=True)
class Favorite:
    id: int  # DB BIGINT. API에는 문자열로 내보낸다
    user_id: int
    name: str  # 별칭 (place_name)
    type: str  # 집 | 학교 | 회사 | 기타 (label)
    address: str | None
    lat: float
    lng: float
    created_at: datetime


@dataclass(frozen=True)
class FavoriteDraft:
    """저장할 값. 좌표가 확정된 뒤에 만든다."""

    name: str
    type: str
    address: str | None
    coordinates: Coordinates


class FavoriteStore(Protocol):
    def list(self, user_id: int) -> list[Favorite]:
        """추가한 순서(created_at, id 오름차순)."""
        ...

    def add(self, user_id: int, draft: FavoriteDraft, now: datetime, limit: int = MAX_FAVORITES) -> Favorite:
        """같은 별칭이 있으면 FavoriteNameTakenError, limit개가 이미 있으면 FavoriteLimitError.

        개수 확인과 추가는 원자적이어야 한다 (동시에 추가해도 limit을 넘지 않는다).
        """
        ...

    def update(
        self,
        user_id: int,
        favorite_id: int,
        name: str | None = None,
        type: str | None = None,
        place: tuple[str | None, Coordinates] | None = None,
    ) -> Favorite | None:
        """None인 값은 바꾸지 않는다. 없거나 남의 것이면 None. 별칭이 다른 즐겨찾기와 겹치면 FavoriteNameTakenError."""
        ...

    def delete(self, user_id: int, favorite_id: int) -> bool:
        """지웠으면 True, 없거나 남의 것이면 False."""
        ...


class MemoryFavoriteStore:
    """개발·테스트용. 서버를 다시 시작하면 사라진다. 잠금 하나로 중복 확인·개수 확인·추가를 한 번에 한다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[int, Favorite] = {}
        self._next_id = 1

    def _owned(self, user_id: int) -> list[Favorite]:
        return sorted((row for row in self._rows.values() if row.user_id == user_id), key=lambda r: (r.created_at, r.id))

    def list(self, user_id: int) -> list[Favorite]:
        with self._lock:
            return self._owned(user_id)

    def add(self, user_id: int, draft: FavoriteDraft, now: datetime, limit: int = MAX_FAVORITES) -> Favorite:
        with self._lock:
            owned = self._owned(user_id)
            key = name_key(draft.name)
            if any(name_key(row.name) == key for row in owned):
                raise FavoriteNameTakenError(draft.name)
            if len(owned) >= limit:
                raise FavoriteLimitError(limit)
            favorite = Favorite(
                id=self._next_id,
                user_id=user_id,
                name=draft.name,
                type=draft.type,
                address=draft.address,
                lat=draft.coordinates.lat,
                lng=draft.coordinates.lng,
                created_at=now,
            )
            self._next_id += 1
            self._rows[favorite.id] = favorite
            return favorite

    def update(
        self,
        user_id: int,
        favorite_id: int,
        name: str | None = None,
        type: str | None = None,
        place: tuple[str | None, Coordinates] | None = None,
    ) -> Favorite | None:
        with self._lock:
            current = self._rows.get(favorite_id)
            if current is None or current.user_id != user_id:
                return None
            if name is not None:
                key = name_key(name)
                if any(name_key(r.name) == key and r.id != favorite_id for r in self._owned(user_id)):
                    raise FavoriteNameTakenError(name)
            changed = current
            if name is not None:
                changed = replace(changed, name=name)
            if type is not None:
                changed = replace(changed, type=type)
            if place is not None:
                address, coordinates = place
                changed = replace(changed, address=address, lat=coordinates.lat, lng=coordinates.lng)
            self._rows[favorite_id] = changed
            return changed

    def delete(self, user_id: int, favorite_id: int) -> bool:
        with self._lock:
            current = self._rows.get(favorite_id)
            if current is None or current.user_id != user_id:
                return False
            del self._rows[favorite_id]
            return True

    def count(self) -> int:
        """테스트용: 모든 사용자의 즐겨찾기 수."""
        with self._lock:
            return len(self._rows)
