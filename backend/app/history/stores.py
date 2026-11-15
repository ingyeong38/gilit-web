"""검색 기록 저장소. 프로토콜과 메모리 구현 (MySQL은 mysql_stores.py, 테이블 search_history).

- add의 user_id는 None일 수 있다 (비로그인 검색, 통계용).
- list·delete는 첫 인자가 항상 user_id이고, 그 사용자에게 연결된 행만 본다. 남의 id·이미 분리한 id는 없는 것과 같다.
- 삭제는 행을 지우지 않고 user_id를 NULL로 분리한다.
"""

# 클래스 안에 list 메서드가 있어서, 그 뒤의 list[...] 타입 표기가 메서드를 가리키지 않게 표기 평가를 미룬다.
from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime
from typing import Protocol

from app.history.models import MAX_ATTACHED_ROWS, HistoryDraft, HistoryEntry, entry_key, group_latest, newest_first


class HistoryStore(Protocol):
    def add(self, user_id: int | None, draft: HistoryDraft, now: datetime) -> HistoryEntry:
        """한 행을 쌓는다. 그 사용자에게 연결된 행이 MAX_ATTACHED_ROWS를 넘으면 오래된 것부터 분리한다."""
        ...

    def list(self, user_id: int, limit: int) -> list[HistoryEntry]:
        """최신순으로, 같은 검색은 가장 최근 행 하나로 묶어 limit개까지."""
        ...

    def delete_one(self, user_id: int, entry_id: int) -> bool:
        """그 행과 같은 검색 묶음의 행을 모두 분리한다 (화면의 카드 한 장). 없거나 남의 것·이미 분리한 것이면 False."""
        ...

    def delete_all(self, user_id: int) -> int:
        """그 사용자의 기록을 모두 분리하고 분리한 행 수를 돌려준다."""
        ...


class MemoryHistoryStore:
    """개발·테스트용. 서버를 다시 시작하면 사라진다."""

    def __init__(self, max_attached: int = MAX_ATTACHED_ROWS) -> None:
        self._lock = threading.Lock()
        self._rows: dict[int, HistoryEntry] = {}
        self._next_id = 1
        self.max_attached = max_attached

    def _attached(self, user_id: int) -> list[HistoryEntry]:
        return [row for row in self._rows.values() if row.user_id == user_id]

    def _detach(self, rows) -> int:
        for row in rows:
            self._rows[row.id] = replace(row, user_id=None)
        return len(rows)

    def add(self, user_id: int | None, draft: HistoryDraft, now: datetime) -> HistoryEntry:
        with self._lock:
            entry = HistoryEntry.from_draft(self._next_id, user_id, draft, now)
            self._next_id += 1
            self._rows[entry.id] = entry
            if user_id is not None:
                self._detach(newest_first(self._attached(user_id))[self.max_attached :])
            return entry

    def list(self, user_id: int, limit: int) -> list[HistoryEntry]:
        with self._lock:
            return group_latest(self._attached(user_id), limit)

    def delete_one(self, user_id: int, entry_id: int) -> bool:
        with self._lock:
            target = self._rows.get(entry_id)
            if target is None or target.user_id != user_id:
                return False
            key = entry_key(target)
            self._detach([row for row in self._attached(user_id) if entry_key(row) == key])
            return True

    def delete_all(self, user_id: int) -> int:
        with self._lock:
            return self._detach(self._attached(user_id))

    def rows(self) -> list[HistoryEntry]:
        """테스트용: 분리된 행을 포함한 모든 행 (id 순)."""
        with self._lock:
            return sorted(self._rows.values(), key=lambda r: r.id)
