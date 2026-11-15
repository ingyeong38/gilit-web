"""HistoryStore의 MySQL 구현 (AUTH_STORE=mysql). 테이블 search_history (스키마 변경 없음).

- 묶기는 SQL이 아니라 메모리 저장소와 같은 파이썬 함수(models.group_latest, entry_key)로 한다.
  SQL로 묶으면 이름 비교에 콜레이션(대소문자·악센트 무시)이 끼어 두 저장소의 결과가 달라진다.
  사용자에게 연결된 행은 add에서 MAX_ATTACHED_ROWS(200)개로 유지하므로 한 번에 읽어도 가볍다
  (인덱스 idx_history_user_created).
- 분리(삭제)는 UPDATE ... SET user_id = NULL이다. 모든 쿼리에 user_id 조건을 넣는다.
"""

from __future__ import annotations  # 클래스의 list 메서드와 list[...] 타입 표기가 섞이지 않게

from datetime import datetime

from app.db import ConnectionPool, from_db, to_db
from app.history.models import MAX_ATTACHED_ROWS, HistoryDraft, HistoryEntry, entry_key, group_latest

COLUMNS = (
    "id, user_id, origin_name, origin_lat, origin_lng, dest_name, dest_lat, dest_lng, arrive_at, buffer_min, "
    "recommended_depart_at, travel_mode, ai_summary, created_at"
)
NEWEST_FIRST = "ORDER BY created_at DESC, id DESC"
MAX_ROWS = 18446744073709551615  # MySQL에서 OFFSET만 쓸 때의 관용 표기 (LIMIT offset, 최대값)


def _float(value) -> float | None:
    return float(value) if value is not None else None


def _entry(row: dict) -> HistoryEntry:
    return HistoryEntry(
        id=int(row["id"]),
        user_id=int(row["user_id"]) if row["user_id"] is not None else None,
        origin_name=row["origin_name"],
        dest_name=row["dest_name"],
        arrive_at=from_db(row["arrive_at"]),
        origin_lat=_float(row["origin_lat"]),
        origin_lng=_float(row["origin_lng"]),
        dest_lat=_float(row["dest_lat"]),
        dest_lng=_float(row["dest_lng"]),
        buffer_min=int(row["buffer_min"]),
        recommended_depart_at=from_db(row["recommended_depart_at"]),
        travel_mode=row["travel_mode"],
        ai_summary=row["ai_summary"],
        created_at=from_db(row["created_at"]),
    )


def _detach_ids(cur, user_id: int, ids: list[int]) -> int:
    if not ids:
        return 0
    placeholders = ", ".join(["%s"] * len(ids))
    return cur.execute(
        f"UPDATE search_history SET user_id = NULL WHERE user_id = %s AND id IN ({placeholders})", (user_id, *ids)
    )


class MySQLHistoryStore:
    def __init__(self, pool: ConnectionPool, max_attached: int = MAX_ATTACHED_ROWS) -> None:
        self.pool = pool
        self.max_attached = max_attached

    def add(self, user_id: int | None, draft: HistoryDraft, now: datetime) -> HistoryEntry:
        created_at = to_db(now)
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO search_history (user_id, origin_name, origin_lat, origin_lng, dest_name, dest_lat, dest_lng, "
                "arrive_at, buffer_min, recommended_depart_at, travel_mode, ai_summary, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    user_id,
                    draft.origin_name,
                    draft.origin_lat,
                    draft.origin_lng,
                    draft.dest_name,
                    draft.dest_lat,
                    draft.dest_lng,
                    to_db(draft.arrive_at),
                    draft.buffer_min,
                    to_db(draft.recommended_depart_at),
                    draft.travel_mode,
                    draft.ai_summary,
                    created_at,
                ),
            )
            entry_id = cur.lastrowid
            if user_id is not None:
                # 상한을 넘은 오래된 행을 분리한다 (같은 트랜잭션).
                cur.execute(
                    f"SELECT id FROM search_history WHERE user_id = %s {NEWEST_FIRST} LIMIT %s, %s",
                    (user_id, self.max_attached, MAX_ROWS),
                )
                _detach_ids(cur, user_id, [int(row["id"]) for row in cur.fetchall()])
            cur.execute(f"SELECT {COLUMNS} FROM search_history WHERE id = %s", (entry_id,))
            return _entry(cur.fetchone())

    def list(self, user_id: int, limit: int) -> list[HistoryEntry]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {COLUMNS} FROM search_history WHERE user_id = %s {NEWEST_FIRST} LIMIT %s",
                (user_id, self.max_attached),
            )
            return group_latest([_entry(row) for row in cur.fetchall()], limit)

    def delete_one(self, user_id: int, entry_id: int) -> bool:
        with self.pool.connection() as conn, conn.cursor() as cur:
            # 그 사용자의 연결된 행을 잠그고 읽어, 대상과 같은 묶음을 파이썬 규칙으로 고른다.
            cur.execute(
                f"SELECT {COLUMNS} FROM search_history WHERE user_id = %s {NEWEST_FIRST} FOR UPDATE", (user_id,)
            )
            rows = [_entry(row) for row in cur.fetchall()]
            target = next((row for row in rows if row.id == entry_id), None)
            if target is None:
                return False
            key = entry_key(target)
            _detach_ids(cur, user_id, [row.id for row in rows if entry_key(row) == key])
            return True

    def delete_all(self, user_id: int) -> int:
        with self.pool.connection() as conn, conn.cursor() as cur:
            return cur.execute("UPDATE search_history SET user_id = NULL WHERE user_id = %s", (user_id,))
