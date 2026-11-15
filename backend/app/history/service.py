"""검색 기록 서비스. 조회·분리 API가 쓴다. 저장(경로 검색 성공 때 자동)은 4단계에서 연결한다."""

from collections.abc import Callable
from datetime import datetime

from app.departure import KST
from app.history.errors import LIMIT_INVALID, NOT_FOUND, HistoryError
from app.history.models import DEFAULT_LIMIT, MAX_LIMIT, HistoryDraft, HistoryEntry
from app.history.stores import HistoryStore


def parse_limit(value: str | None) -> int:
    """?limit= 값. 없으면 20. 1~50의 ASCII 정수가 아니면 400."""
    if value is None:
        return DEFAULT_LIMIT
    if not value.isascii() or not value.isdigit():
        raise HistoryError(400, LIMIT_INVALID)
    number = int(value)
    if not 1 <= number <= MAX_LIMIT:
        raise HistoryError(400, LIMIT_INVALID)
    return number


def parse_history_id(value: str | None) -> int | None:
    """?id= 값. 양의 정수가 아니거나 BIGINT를 넘으면 None (= 없는 것과 같은 404)."""
    if value is None or not value.isascii() or not value.isdigit():
        return None
    number = int(value)
    return number if 0 < number <= 2**63 - 1 else None


class HistoryService:
    def __init__(self, store: HistoryStore, clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self._clock = clock or (lambda: datetime.now(KST))

    def list(self, user_id: int, limit: int) -> list[HistoryEntry]:
        return self.store.list(user_id, limit)

    def delete_one(self, user_id: int, entry_id: int | None) -> None:
        if entry_id is None or not self.store.delete_one(user_id, entry_id):
            raise HistoryError(404, NOT_FOUND)

    def delete_all(self, user_id: int) -> int:
        return self.store.delete_all(user_id)

    def add(self, user_id: int | None, draft: HistoryDraft) -> HistoryEntry:
        """한 행 저장 (4단계에서 GET /api/routes가 부른다. 지금은 테스트·스크립트용)."""
        return self.store.add(user_id, draft, self._clock())


def create_history_store(store: str, pool=None) -> HistoryStore | None:
    """AUTH_STORE에 맞는 검색 기록 저장소. mysql은 factory의 공유 연결 풀을 쓴다."""
    if store == "memory":
        from app.history.stores import MemoryHistoryStore

        return MemoryHistoryStore()
    if store == "mysql":
        if pool is None:
            raise ValueError("AUTH_STORE=mysql 검색 기록 저장소에는 연결 풀이 필요합니다.")
        from app.history.mysql_stores import MySQLHistoryStore

        return MySQLHistoryStore(pool)
    return None
