import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.departure.errors import (
    ArrivalTimePassedError,
    NoFeasibleDepartureError,
    RouteProviderError,
    SearchBudgetExceededError,
)
from app.departure.models import KST, Coordinate, DepartureResult, TravelMode
from app.departure.providers import RouteProvider

MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class SolverConfig:
    max_calls: int = 8  # 요청 하나당 RouteProvider.get_duration 최대 호출 횟수 (실제 API의 요금·지연을 고려)
    search_window: timedelta = timedelta(hours=6)  # 도착 희망 시각보다 이만큼 앞까지만 출발시각을 찾는다
    tolerance: timedelta = MINUTE  # 이 간격 안으로 좁혀지면 탐색을 멈춘다 (분 단위)

    def __post_init__(self) -> None:
        if self.max_calls < 2:
            raise ValueError("max_calls는 2 이상이어야 합니다 (기준 소요시간 조회 + 후보 확인).")
        if self.tolerance < MINUTE or self.tolerance % MINUTE:
            raise ValueError("tolerance는 1분 이상, 분 단위여야 합니다.")
        if self.search_window <= self.tolerance:
            raise ValueError("search_window는 tolerance보다 길어야 합니다.")


class DepartureSolver:
    """도착 희망 시각까지 도착하는 가장 늦은 출발시각을 찾는다.

    목표 도착시각 T = 도착 희망 시각 - 여유시간. 출발시각 t의 도착시각 arrival(t) = t + 소요시간(t).
    arrival(t) <= T를 만족하는 가장 늦은 t를 분 단위로 찾는다.

    1. 1차 추정: T에 출발할 때의 소요시간을 기준으로 t0 = T - 기준 소요시간
    2. 후보의 도착시각을 확인해 [제시간 도착하는 출발시각 lo, 늦는 출발시각 hi] 구간을 잡는다
    3. 구간이 tolerance 이하가 될 때까지 좁힌다 (추정값이 구간 밖이면 이분탐색)
    돌려주는 출발시각은 항상 실제로 조회해 제시간 도착을 확인한 값이다.
    호출 한도에 걸리면 그때까지 확인한 lo(답보다 이르거나 같은, 안전한 값)를 돌려준다.
    """

    def __init__(
        self,
        provider: RouteProvider,
        config: SolverConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider = provider
        self.config = config or SolverConfig()
        self.clock = clock or (lambda: datetime.now(KST))

    def solve(
        self,
        origin: Coordinate,
        dest: Coordinate,
        arrive_by: datetime,
        buffer_min: int = 0,
        travel_mode: TravelMode | str = TravelMode.CAR,
    ) -> DepartureResult:
        if arrive_by.tzinfo is None:
            raise ValueError("arrive_by에는 시간대 정보가 있어야 합니다.")
        if isinstance(buffer_min, bool) or not isinstance(buffer_min, int) or buffer_min < 0:
            raise ValueError("여유시간은 0 이상의 정수(분)여야 합니다.")
        travel_mode = TravelMode(travel_mode)

        now = self.clock()
        if arrive_by <= now:
            raise ArrivalTimePassedError("도착 희망 시각이 이미 지났습니다.")

        # 지금보다 이른 출발은 불가능하고, 탐색 구간보다 이른 출발은 찾지 않는다.
        now_bound = _ceil_minute(now)
        earliest = max(now_bound, _ceil_minute(arrive_by - self.config.search_window))
        search = _Search(self.provider, origin, dest, travel_mode, self.config.max_calls)

        # 여유시간을 둘 수 없으면(지금 출발해도 빠듯하면) 여유 없이 다시 찾는다. 앞선 조회 결과는 재사용한다.
        targets = [(arrive_by - timedelta(minutes=buffer_min), True)] if buffer_min else []
        targets.append((arrive_by, False))
        for target, buffer_applied in targets:
            try:
                depart_at, converged = self._latest_departure(search, target, earliest)
            except _Infeasible:
                continue
            duration_sec = search.duration(depart_at)
            return DepartureResult(
                depart_at=depart_at,
                arrive_at=depart_at + timedelta(seconds=duration_sec),
                duration_sec=duration_sec,
                target_arrive_at=arrive_by,
                buffer_min=buffer_min,
                buffer_applied=buffer_applied,
                provider_calls=search.calls,
                converged=converged,
            )

        if earliest == now_bound:
            raise NoFeasibleDepartureError("지금 출발해도 도착 희망 시각까지 도착할 수 없습니다.")
        raise NoFeasibleDepartureError(
            f"도착 희망 시각 {_format_duration(self.config.search_window)} 전에 출발해도 제시간에 도착할 수 없습니다."
        )

    def _latest_departure(self, search: "_Search", target: datetime, earliest: datetime) -> tuple[datetime, bool]:
        """[earliest, target]에서 arrival(t) <= target인 가장 늦은 t와 수렴 여부를 돌려준다."""
        tolerance = self.config.tolerance
        latest = _floor_minute(target)
        if latest < earliest:
            raise _Infeasible
        lo: datetime | None = None  # 제시간에 도착함을 확인한 출발시각
        hi = latest + MINUTE  # 소요시간이 0 이상이므로 target보다 늦게 도착함이 확실한 출발시각

        try:
            # 1. 1차 추정. 기준 소요시간 조회도 latest의 도착 여부 확인을 겸한다.
            base_arrival = search.arrival(latest)
            if base_arrival <= target:
                return latest, True
            hi = latest
            if hi == earliest:
                raise _Infeasible
            candidate = _floor_minute(target - (base_arrival - latest))
            candidate = min(max(candidate, earliest), hi - MINUTE)

            # 2~3. [lo, hi] 구간을 좁힌다. 다음 후보는 도착시각이 목표와 어긋난 만큼 옮긴 추정값이고,
            # 추정값이 구간 밖이면 이분(중간값)한다. 소요시간은 출발시각에 따라 천천히 변하므로
            # 대개 추정값이 답 근처에 떨어져, 순수 이분탐색보다 적은 호출로 1분 안에 들어온다.
            while lo is None or hi - lo > tolerance:
                arrival = search.arrival(candidate)
                if arrival <= target:
                    lo = candidate
                    estimate = candidate + max(_floor_delta(target - arrival), tolerance)
                else:
                    hi = candidate
                    if hi == earliest:
                        raise _Infeasible
                    estimate = candidate - max(_ceil_delta(arrival - target), tolerance)
                if lo is None:
                    candidate = max(estimate, earliest)
                elif lo < estimate < hi:
                    candidate = estimate
                else:
                    candidate = lo + _floor_delta((hi - lo) / 2)
            return lo, True
        except _BudgetExhausted:
            if lo is None:
                raise SearchBudgetExceededError("출발시각을 계산하지 못했습니다. 잠시 후 다시 시도해 주세요.") from None
            return lo, False


class _Infeasible(Exception):
    pass


class _BudgetExhausted(Exception):
    pass


class _Search:
    """요청 하나의 조회 상태. 호출 횟수를 세고, 같은 출발시각은 다시 조회하지 않는다."""

    def __init__(
        self,
        provider: RouteProvider,
        origin: Coordinate,
        dest: Coordinate,
        travel_mode: TravelMode,
        max_calls: int,
    ) -> None:
        self.provider = provider
        self.origin = origin
        self.dest = dest
        self.travel_mode = travel_mode
        self.max_calls = max_calls
        self.calls = 0
        self._durations: dict[datetime, int] = {}

    def arrival(self, depart_at: datetime) -> datetime:
        return depart_at + timedelta(seconds=self.duration(depart_at))

    def duration(self, depart_at: datetime) -> int:
        if depart_at not in self._durations:
            if self.calls >= self.max_calls:
                raise _BudgetExhausted
            self.calls += 1
            seconds = self.provider.get_duration(self.origin, self.dest, depart_at, self.travel_mode)
            if seconds < 0:
                raise RouteProviderError(f"소요시간이 음수입니다: {seconds}")
            self._durations[depart_at] = math.ceil(seconds)
        return self._durations[depart_at]


def _floor_minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def _ceil_minute(value: datetime) -> datetime:
    floored = _floor_minute(value)
    return floored if floored == value else floored + MINUTE


def _floor_delta(delta: timedelta) -> timedelta:
    return (delta // MINUTE) * MINUTE


def _ceil_delta(delta: timedelta) -> timedelta:
    return -((-delta) // MINUTE) * MINUTE


def _format_duration(delta: timedelta) -> str:
    minutes = int(delta / MINUTE)
    if minutes % 60 == 0:
        return f"{minutes // 60}시간"
    return f"{minutes}분"
