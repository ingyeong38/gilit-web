"""검색 기록 저장소. 프로토콜과 메모리 구현 (MySQL은 mysql_stores.py, 테이블 search_history).

- 개인 기록 메서드의 첫 인자는 로그인 사용자의 user_id(양의 정수)다. add에 None을 주면 ValueError (비로그인 기록은 없다).
- list·delete는 그 사용자의 행만 본다. 남의 id·이미 지운 id는 없는 것과 같다.
- 삭제는 행을 지운다.
"""

# 클래스 안에 list 메서드가 있어서, 그 뒤의 list[...] 타입 표기가 메서드를 가리키지 않게 표기 평가를 미룬다.
from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from app.history.models import MAX_ATTACHED_ROWS, HistoryDraft, HistoryEntry, entry_key, group_latest, newest_first


class HistoryStore(Protocol):
    def add(self, user_id: int, draft: HistoryDraft, now: datetime) -> HistoryEntry:
        """한 행을 쌓는다. 그 사용자의 행이 MAX_ATTACHED_ROWS를 넘으면 오래된 것부터 지운다."""
        ...

    def list(self, user_id: int, limit: int) -> list[HistoryEntry]:
        """최신순으로, 같은 검색은 가장 최근 행 하나로 묶어 limit개까지."""
        ...

    def list_created_between(self, user_id: int, start: datetime, end: datetime) -> list[HistoryEntry]:
        """created_at이 start 이상 end 이하인 그 사용자의 행 (묶지 않은 행 그대로, 순서 없음). 이용 통계가 쓴다."""
        ...

    def site_search_stats(self, start: datetime, end: datetime) -> tuple[int, list[dict], list[dict]]:
        """start 이상 end 이하의 보관 행 수와 두 순위를 반환한다."""
        ...

    def delete_one(self, user_id: int, entry_id: int) -> bool:
        """그 행과 같은 검색 묶음의 행을 모두 지운다 (화면의 카드 한 장). 없거나 남의 것·이미 지운 것이면 False."""
        ...

    def delete_all(self, user_id: int) -> int:
        """그 사용자의 기록을 모두 지우고 지운 행 수를 돌려준다."""
        ...


def require_user_id(user_id) -> int:
    """기록은 로그인 사용자에게만 있다. None·bool·0 이하는 프로그래밍 오류로 본다."""
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("검색 기록에는 로그인 사용자의 user_id가 필요합니다.")
    return user_id


def rank_places(names: Iterable[str | None]) -> list[dict]:
    counts = Counter(name.strip(" ") for name in names if name and name.strip(" "))
    return [{"name": name, "count": count}
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]]


class MemoryHistoryStore:
    """개발·테스트용. 서버를 다시 시작하면 사라진다."""

    def __init__(self, max_attached: int = MAX_ATTACHED_ROWS) -> None:
        self._lock = threading.Lock()
        self._rows: dict[int, HistoryEntry] = {}
        self._next_id = 1
        self.max_attached = max_attached

    def _attached(self, user_id: int) -> list[HistoryEntry]:
        return [row for row in self._rows.values() if row.user_id == user_id]

    def _delete(self, rows) -> int:
        for row in rows:
            del self._rows[row.id]
        return len(rows)

    def add(self, user_id: int, draft: HistoryDraft, now: datetime) -> HistoryEntry:
        require_user_id(user_id)
        with self._lock:
            entry = HistoryEntry.from_draft(self._next_id, user_id, draft, now)
            self._next_id += 1
            self._rows[entry.id] = entry
            self._delete(newest_first(self._attached(user_id))[self.max_attached :])
            return entry

    def list(self, user_id: int, limit: int) -> list[HistoryEntry]:
        with self._lock:
            return group_latest(self._attached(user_id), limit)

    def list_created_between(self, user_id: int, start: datetime, end: datetime) -> list[HistoryEntry]:
        with self._lock:
            return [row for row in self._attached(user_id) if start <= row.created_at <= end]

    def delete_one(self, user_id: int, entry_id: int) -> bool:
        with self._lock:
            target = self._rows.get(entry_id)
            if target is None or target.user_id != user_id:
                return False
            key = entry_key(target)
            self._delete([row for row in self._attached(user_id) if entry_key(row) == key])
            return True

    def delete_all(self, user_id: int) -> int:
        with self._lock:
            return self._delete(self._attached(user_id))

    def site_search_stats(self, start: datetime, end: datetime) -> tuple[int, list[dict], list[dict]]:
        with self._lock:
            recent = [row for row in self._rows.values() if start <= row.created_at <= end]
        return len(recent), rank_places(row.origin_name for row in recent), rank_places(row.dest_name for row in recent)

    def rows(self) -> list[HistoryEntry]:
        """테스트용: 모든 행 (id 순)."""
        with self._lock:
            return sorted(self._rows.values(), key=lambda r: r.id)
