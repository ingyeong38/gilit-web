"""검색 기록 (F9). search_history에 쌓기만 하고, 조회할 때 같은 검색을 묶고, 삭제는 user_id를 NULL로 분리한다.

- models.py: HistoryDraft·HistoryEntry, 묶기 규칙 (search_key, group_latest)
- stores.py: HistoryStore 프로토콜과 메모리 구현 / mysql_stores.py: MySQL 구현
- service.py: HistoryService, ?limit=·?id= 해석
웹 API는 app/api/history.py에 있다.
"""

from app.history.errors import HistoryError
from app.history.models import DEFAULT_LIMIT, MAX_ATTACHED_ROWS, MAX_LIMIT, HistoryDraft, HistoryEntry, search_key
from app.history.service import HistoryService, create_history_store
from app.history.stores import HistoryStore, MemoryHistoryStore

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_ATTACHED_ROWS",
    "MAX_LIMIT",
    "HistoryDraft",
    "HistoryEntry",
    "HistoryError",
    "HistoryService",
    "HistoryStore",
    "MemoryHistoryStore",
    "create_history_store",
    "search_key",
]
