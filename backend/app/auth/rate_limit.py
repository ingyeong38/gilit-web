"""요청 횟수 제한 (슬라이딩 윈도). 프로세스 메모리에 둔다.

워커가 하나일 때만 정확하다. 워커를 여러 개 띄우거나 서버를 여러 대 두면 공유 저장소(Redis 등)가 필요하다.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, limit: int, window_sec: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_sec = window_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> float | None:
        """요청 한 번을 센다. 허용하면 None, 넘었으면 다시 시도할 수 있을 때까지의 초를 돌려준다.

        거절된 요청은 세지 않는다. 계속 두드려도 제한 시간이 늘어나지 않는다.
        """
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window_sec:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(hits[0] + self.window_sec - now, 0.0)
            hits.append(now)
            self._prune(now)
            return None

    def _prune(self, now: float) -> None:
        # 오래 안 온 키가 쌓여 메모리가 늘지 않게 가끔 정리한다.
        if len(self._hits) < 10_000:
            return
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window_sec]:
            del self._hits[key]


def retry_after_header(seconds: float) -> dict[str, str]:
    return {"Retry-After": str(max(1, math.ceil(seconds)))}
