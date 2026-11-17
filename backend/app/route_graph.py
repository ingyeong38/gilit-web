"""출발시각별 소요시간 그래프 (SFR-006, GET /api/routes/graph).

경로 카드(id, 권장 출발시각)마다 권장 출발시각 앞뒤의 슬롯(기본 15분 간격 -45~+45분, 7개)을 요약 조회한다.

카카오 약관상 길찾기 응답은 캐시(임시 포함)할 수 없다. 그래서
- 그래프 응답을 저장하지 않는다 (같은 요청이 다시 오면 다시 조회한다).
- 슬롯 조회는 Provider의 메모리 캐시를 거치지 않는다 (RouteProvider.get_route_summary_uncached).
- 한 요청 안에서 같은 (출발지, 목적지, 분, 옵션)이 겹치면 그 요청 안에서만 한 번 조회해 나눠 쓴다.

호출량은 요청당 슬롯 상한(GRAPH_MAX_SLOTS)과 그래프 전용 일일 예산(DailyCallBudget)으로 묶는다.
"""

import logging
import math
import threading
import time
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.departure import (
    KST,
    Coordinate,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    RouteOption,
    RouteSummary,
)
from app.departure.providers import RouteProvider

logger = logging.getLogger("app.route_graph")

GRAPH_MAX_SLOTS = 13  # 요청 하나의 슬롯 조회 상한 (카드 4개 x 7슬롯 = 28을 줄인다)
GRAPH_BUDGET_MESSAGE = "오늘 소요시간 그래프 조회 한도를 모두 사용했습니다. 내일 다시 시도해 주세요."
GRAPH_TIMEOUT_MESSAGE = "소요시간 그래프를 제시간에 계산하지 못했습니다. 잠시 후 다시 시도해 주세요."


class GraphBudgetExceededError(ProviderQuotaExceededError):
    """그래프 전용 일일 호출 예산을 다 썼다. 호출 한도 초과와 같이 503이다 (api/errors.py)."""


@dataclass(frozen=True)
class GraphCard:
    """검증을 마친 card 파라미터 하나. id는 응답의 routeId로 그대로 돌려준다."""

    id: str
    option: RouteOption
    depart_at: datetime


@dataclass(frozen=True)
class GraphConfig:
    slots_before: int = 3
    slots_after: int = 3
    interval_min: int = 15
    max_workers: int = 4  # executor를 넘기지 않았을 때 이 호출에서 만들 작업 스레드 수
    max_slots: int = GRAPH_MAX_SLOTS


class DailyCallBudget:
    """그래프 슬롯 조회의 일일 호출 수. KST 날짜가 바뀌면 0부터 다시 센다.

    프로세스 메모리에 센다. 워커(프로세스)가 여럿이면 워커마다 따로 센다.
    실제로 Provider를 부르기 직전에만 하나씩 쓴다 (합쳐진 조회·건너뛴 슬롯은 세지 않는다).
    """

    def __init__(self, limit: int) -> None:
        if limit < 0:
            raise ValueError("일일 호출 예산은 0 이상이어야 합니다.")
        self.limit = limit
        self._day: date | None = None
        self._used = 0
        self._lock = threading.Lock()

    def _roll(self, now: datetime) -> None:
        day = now.astimezone(KST).date()
        if day != self._day:
            self._day, self._used = day, 0

    def remaining(self, now: datetime) -> int:
        with self._lock:
            self._roll(now)
            return max(0, self.limit - self._used)

    def try_acquire(self, now: datetime) -> bool:
        with self._lock:
            self._roll(now)
            if self._used >= self.limit:
                return False
            self._used += 1
            return True

    def ensure_available(self, now: datetime) -> None:
        if self.remaining(now) <= 0:
            raise GraphBudgetExceededError(GRAPH_BUDGET_MESSAGE)


LookupKey = tuple[Coordinate, Coordinate, datetime, RouteOption]


def plan_lookups(
    origin: Coordinate,
    destination: Coordinate,
    cards: list[GraphCard],
    config: GraphConfig,
    now: datetime,
    arrive: datetime,
) -> dict[LookupKey, list[str]]:
    """조회할 슬롯 -> 그 결과를 쓸 카드 id들. 순서는 조회 우선순위다.

    - 슬롯: 카드 출발시각(분 단위로 내림) + k x 간격, k = -slots_before..slots_after
    - 지금 이전 슬롯과 도착 희망 시각(arrive) 이후(arrive 이상) 슬롯은 뺀다. 뺀 슬롯은 상한·호출 예산에 세지 않는다
      (카드 출발시각 자체가 지났어도 카드는 거절하지 않는다)
    - 같은 (출발지, 목적지, 분, 옵션)은 한 번만 조회한다
    - 상한을 넘으면 권장 출발시각에 가까운 슬롯부터 카드를 번갈아 고른다 (모든 카드가 가운데 점을 갖는다)
    """
    interval = timedelta(minutes=config.interval_min)
    candidates = []
    for index, card in enumerate(cards):
        base = card.depart_at.astimezone(KST).replace(second=0, microsecond=0)
        for step in range(-config.slots_before, config.slots_after + 1):
            slot = base + step * interval
            if slot < now or slot >= arrive:
                continue
            candidates.append(((abs(step), step, index), slot, card))
    candidates.sort(key=lambda candidate: candidate[0])

    lookups: dict[LookupKey, list[str]] = {}
    for _, slot, card in candidates:
        key = (origin, destination, slot, card.option)
        if key in lookups:
            if card.id not in lookups[key]:
                lookups[key].append(card.id)
        elif len(lookups) < config.max_slots:
            lookups[key] = [card.id]
    return lookups


def collect_route_graphs(
    provider: RouteProvider,
    origin: Coordinate,
    destination: Coordinate,
    cards: list[GraphCard],
    config: GraphConfig,
    *,
    now: datetime,
    arrive: datetime,
    budget: DailyCallBudget,
    deadline: float,
    executor: Executor | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[dict]:
    """[{routeId, points: [{departTime, durationMin}]}]. 카드 순서를 따르고 점은 시간순이다.

    - 실패한 슬롯은 그 점만, 점이 하나도 없는 카드는 그 항목만 뺀다.
    - deadline(monotonic 기준)이 지나면 그때까지 받은 점만 돌려준다. 남은 조회는 시작하지 않는다.
    - 슬롯이 모두 빠진 카드(지난 시각·arrive 이후)는 항목에서 뺀다. 조회할 슬롯이 하나도 없으면 [].
    - 슬롯은 있었는데 점이 하나도 없으면 오류를 던진다: 호출 한도(일일 예산 포함) -> 503,
      시간 초과 -> 504, 그 밖에는 첫 실패를 그대로 (api/errors.py의 기존 매핑).
    """
    lookups = plan_lookups(origin, destination, cards, config, now, arrive)
    if not lookups:
        return []

    def run(key: LookupKey) -> RouteSummary:
        if not budget.try_acquire(now):
            raise GraphBudgetExceededError(GRAPH_BUDGET_MESSAGE)
        _, _, slot, option = key
        return provider.get_route_summary_uncached(origin, destination, slot, option)

    # 앱은 공유 executor(app.state.graph_executor)를 넘긴다. 작업 스레드가 요청 사이에 남아 스레드별 HTTP 세션
    # (KakaoRouteProvider)의 연결을 다시 쓰고, 동시 조회 수가 앱 전체에서 max_workers로 묶인다.
    owned = executor is None
    if owned:
        executor = ThreadPoolExecutor(max_workers=config.max_workers, thread_name_prefix="route-graph")
    futures: dict[Future, LookupKey] = {executor.submit(run, key): key for key in lookups}
    done, not_done = wait(futures, timeout=max(0.0, deadline - monotonic()))
    for future in not_done:
        future.cancel()  # 아직 시작하지 않은 조회는 하지 않는다. 이미 시작한 조회는 끝까지 돌지만 결과는 버린다
    if owned:
        executor.shutdown(wait=False, cancel_futures=True)

    points: dict[str, list[tuple[datetime, int]]] = {card.id: [] for card in cards}
    errors: list[BaseException] = []
    for future, key in futures.items():  # 조회 우선순위 순서 (첫 실패를 고정하려고)
        if future not in done:
            continue
        error = future.exception()
        if error is not None:
            errors.append(error)
            continue
        slot = key[2]
        minutes = math.ceil(future.result().duration_sec / 60)
        for card_id in lookups[key]:
            points[card_id].append((slot, minutes))

    if errors or not_done:
        # 장소 이름·좌표는 남기지 않는다 (개인 검색 내용)
        logger.warning("소요시간 그래프: 슬롯 %d개 중 실패 %d개, 시간 초과 %d개 (%s)", len(lookups), len(errors),
                       len(not_done), ", ".join(sorted({type(error).__name__ for error in errors})) or "-")

    graphs = [
        {"routeId": card.id,
         "points": [{"departTime": slot.isoformat(), "durationMin": minutes} for slot, minutes in sorted(points[card.id])]}
        for card in cards if points[card.id]
    ]
    if graphs:
        return graphs
    quota = next((error for error in errors if isinstance(error, ProviderQuotaExceededError)), None)
    if quota is not None:
        raise quota
    timeout = next((error for error in errors if isinstance(error, ProviderTimeoutError)), None)
    if timeout is not None:
        raise timeout  # 카카오 응답 시간 초과 (기존 504 문장)
    if not_done:
        raise ProviderTimeoutError(GRAPH_TIMEOUT_MESSAGE)  # 서버 시간 예산 초과
    raise errors[0]
