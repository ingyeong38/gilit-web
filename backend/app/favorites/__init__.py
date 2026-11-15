"""즐겨찾기 (F9). 사용자별 장소 별칭과 좌표.

- validation.py: 입력 검증 (400 + 명세 문구)
- stores.py: FavoriteStore 프로토콜과 메모리 구현 (메서드 첫 인자는 항상 user_id)
- service.py: FavoriteService (좌표 확정, 중복·개수 제한 오류 변환)
웹 API는 app/api/favorites.py에 있다.
"""

from app.favorites.errors import FavoriteError
from app.favorites.service import FavoriteService, create_favorite_store
from app.favorites.stores import MAX_FAVORITES, Favorite, FavoriteDraft, FavoriteStore, MemoryFavoriteStore
from app.favorites.validation import FAVORITE_TYPES, Coordinates

__all__ = [
    "FAVORITE_TYPES",
    "MAX_FAVORITES",
    "Coordinates",
    "Favorite",
    "FavoriteDraft",
    "FavoriteError",
    "FavoriteService",
    "FavoriteStore",
    "MemoryFavoriteStore",
    "create_favorite_store",
]
