"""카카오 상세 응답과 기존 출발시각 엔진을 연결한다. 경로별 응답을 섞지 않는다."""
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.departure import (
    KST,
    Coordinate,
    DepartureError,
    DepartureResult,
    DepartureSolver,
    NoFeasibleDepartureError,
    RouteNotFoundError,
    RouteOption,
    RouteSummary,
    SolverConfig,
    TravelMode,
)
from app.departure.errors import RouteProviderError
from app.departure.providers import RouteProvider

logger = logging.getLogger("app.routing")


def parse_detailed_route(route: dict) -> dict:
    """sections 순서 → roads 순서 → vertexes의 [경도, 위도] 순서를 유지한다."""
    try:
        summary = route["summary"]
        duration = summary["duration"]
        distance = summary["distance"]
        for value in (duration, distance):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError("잘못된 경로 지표")
        path = []
        for section in route["sections"]:
            if not section["roads"]:
                raise ValueError("도로 없음")
            for road in section["roads"]:
                vertices = road["vertexes"]
                if not vertices or len(vertices) % 2:
                    raise ValueError("좌표 쌍 오류")
                for i in range(0, len(vertices), 2):
                    lng, lat = vertices[i:i + 2]
                    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in (lng, lat)):
                        raise ValueError("좌표 형식 오류")
                    Coordinate(lat, lng)
                    point = {"lat": lat, "lng": lng}
                    if not path or path[-1] != point:
                        path.append(point)
        if len(path) < 2:
            raise ValueError("상세 좌표 부족")
        toll = summary.get("fare", {}).get("toll")
        if toll is not None and (isinstance(toll, bool) or not isinstance(toll, (int, float)) or not math.isfinite(toll) or toll < 0):
            raise ValueError("요금 형식 오류")
    except (KeyError, TypeError, ValueError, IndexError):
        raise RouteProviderError("상세 도로 좌표 또는 경로 지표가 올바르지 않습니다.") from None
    return {"path": path, "durationSec": duration, "distanceKm": round(distance / 1000, 3), "toll": toll}


class RouteResultCache:
    """검증을 마친 전체 응답만 저장한다. 실패는 저장하지 않고 TTL/개수로 제한한다."""
    def __init__(self, ttl=600, max_entries=64, monotonic=None):
        import time
        from collections import OrderedDict
        from threading import Lock
        self.ttl, self.max_entries = ttl, max_entries
        self.monotonic = monotonic or time.monotonic
        self.items, self.lock = OrderedDict(), Lock()

    def get(self, key, now):
        from copy import deepcopy
        from datetime import datetime
        with self.lock:
            item = self.items.get(key)
            if item is None:
                return None
            routes, expiry = item
            if self.monotonic() >= expiry or any(datetime.fromisoformat(route["departTime"]) <= now for route in routes):
                del self.items[key]
                return None
            self.items.move_to_end(key)
            return deepcopy(routes)

    def put(self, key, routes):
        from copy import deepcopy
        if self.ttl <= 0 or sum(len(route["path"]) for route in routes) > 20000:
            return
        with self.lock:
            self.items[key] = (deepcopy(routes), self.monotonic() + self.ttl)
            self.items.move_to_end(key)
            while len(self.items) > self.max_entries:
                self.items.popitem(last=False)


# --- 경로 비교 서비스 (F5) ---------------------------------------------------------------
# 옵션(추천·최단시간·최단거리·무료도로)마다 출발시각 역산 엔진을 돌리고, 확정된 출발시각에 상세 경로를 한 번 받아
# 카드를 만든다. GET /api/routes(api/routes.py)가 쓴다.

NO_FREE_ROUTE_MESSAGE = "통행료 없이 갈 수 있는 경로를 찾지 못했습니다."
NOT_IN_TIME_MESSAGE = "지금 출발해도 도착 희망 시각까지 도착할 수 없습니다."


@dataclass
class RouteCard:
    """경로 비교 카드 하나. 소요시간·거리·통행료·경로·이름은 모두 같은 상세 응답 하나에서 가져온다."""

    option: RouteOption  # 카드를 만든 옵션 (id)
    options: list[str]  # 이 카드에 합쳐진 옵션 키. 같은 길이면 ["recommend", "time"]
    name: str
    depart_at: datetime  # 권장 출발시각
    duration_sec: int  # 상세 응답의 소요시간
    distance_km: float
    toll: int | None
    path: list[dict]
    buffer_applied: bool
    converged: bool
    data_source: str
    detail_depart_at: datetime  # 상세 응답을 받은 출발시각. 소요시간이 어긋나 출발시각을 앞당기면 depart_at과 다르다
    first_summary: tuple[datetime, RouteSummary]  # 엔진의 첫 조회. 다음 옵션의 중복 조기 감지에 쓴다

    @property
    def arrive_at(self) -> datetime:
        return self.depart_at + timedelta(seconds=self.duration_sec)

    @property
    def path_signature(self) -> tuple[tuple[float, float], ...]:
        return _path_signature(self.path)

    def to_dict(self) -> dict:
        """GET /api/routes 카드 (docs/api-spec.md, camelCase)."""
        return {
            "id": self.option.key,
            "options": list(self.options),
            "label": self.option.label,
            "name": self.name,
            "departTime": self.depart_at.astimezone(KST).isoformat(),
            "arriveTime": self.arrive_at.astimezone(KST).isoformat(),
            "durationMin": math.ceil(self.duration_sec / 60),
            "distanceKm": self.distance_km,
            "toll": self.toll,
            "fuel": None,
            "bufferApplied": self.buffer_applied,
            "converged": self.converged,
            "dataSource": self.data_source,
            "path": self.path,
            "aiSummary": {
                "title": f"{self.option.label} 경로",
                "text": "소요시간·거리·통행료·경로선은 같은 상세 길찾기 응답 기준입니다.",
            },
        }


@dataclass
class CompareResult:
    cards: list[RouteCard]
    excluded: dict[str, str] = field(default_factory=dict)  # 카드에서 뺀 옵션 키 -> 이유 (사용자용 문장)
    lookups: int = 0  # 길찾기 조회 횟수 (요약 + 상세, Provider 캐시 적중 포함)


class OptionRouteProvider(RouteProvider):
    """엔진(DepartureSolver)의 소요시간 조회를 한 경로 옵션의 요약 조회로 바꾼다. 엔진은 그대로 쓴다.

    같은 출발시각은 다시 조회하지 않는다. 첫 조회가 이미 만든 카드의 첫 조회와 같으면(같은 출발시각에 같은
    소요시간·거리·통행료) _SameFirstSummary로 탐색을 멈춰, 같은 길일 가능성이 큰 옵션에 호출을 쓰지 않는다.
    """

    def __init__(self, provider: RouteProvider, option: RouteOption, known_cards: list["RouteCard"] = ()) -> None:
        self.provider = provider
        self.option = option
        self.known_cards = list(known_cards)
        self.summaries: dict[datetime, RouteSummary] = {}
        self.first: tuple[datetime, RouteSummary] | None = None

    def get_duration(self, origin, dest, depart_at, travel_mode=TravelMode.CAR) -> int:
        if depart_at not in self.summaries:
            summary = self.provider.get_route_summary(origin, dest, depart_at, self.option)
            self.summaries[depart_at] = summary
            if self.first is None:
                self.first = (depart_at, summary)
                for card in self.known_cards:
                    if card.first_summary == self.first:
                        raise _SameFirstSummary(card)
        return self.summaries[depart_at].duration_sec


class _SameFirstSummary(Exception):
    def __init__(self, card: RouteCard) -> None:
        super().__init__(card.option.key)
        self.card = card


def compare_routes(
    provider: RouteProvider,
    options: tuple[RouteOption, ...] | list[RouteOption],
    solver_config: SolverConfig,
    origin: Coordinate,
    destination: Coordinate,
    arrive_at: datetime,
    buffer_min: int = 0,
    *,
    clock: Callable[[], datetime] | None = None,
    data_source: str = "mock",
) -> CompareResult:
    """옵션별 경로 카드. 카드 순서는 options 순서이고, 같은 길로 확인된 옵션은 앞 카드의 options에 합친다.

    - 한 옵션이 DepartureError(경로 없음, 제시간 도착 불가 등)로 실패하면 그 카드만 뺀다 (excluded).
    - 모든 옵션이 실패하면 options의 첫 옵션(기본 recommend)의 오류를 그대로 던진다 (API 4xx).
    - RouteProviderError(인증, 한도, 타임아웃 등)는 다른 옵션도 같은 결과일 것이므로 바로 던진다 (API 5xx).
    - 조회 수: 옵션마다 요약 최대 solver_config.max_calls회 + 상세 1회 (중복 확인이 빗나가면 상세 1회 더).
    """
    if not options:
        raise ValueError("경로 옵션이 하나 이상 있어야 합니다.")
    clock = clock or (lambda: datetime.now(KST))
    result = CompareResult(cards=[])
    failures: list[DepartureError] = []

    for option in options:
        adapter = OptionRouteProvider(provider, option, result.cards)
        try:
            same_route = _compare_option(provider, adapter, solver_config, clock, origin, destination,
                                         arrive_at, buffer_min, data_source, result)
        except DepartureError as error:
            failures.append(error)
            result.excluded[option.key] = str(error)  # 로그는 호출한 쪽(api/routes.py)이 남긴다
            continue
        finally:
            result.lookups += len(adapter.summaries)
        if same_route is not None:
            same_route.options.append(option.key)

    if not result.cards:
        raise failures[0]
    return result


def _compare_option(provider, adapter: OptionRouteProvider, solver_config, clock, origin, destination,
                    arrive_at, buffer_min, data_source, result: CompareResult) -> RouteCard | None:
    """옵션 하나를 계산해 새 카드를 result.cards에 넣는다. 같은 길인 기존 카드가 있으면 그 카드를 돌려준다."""
    option = adapter.option
    solver = DepartureSolver(adapter, solver_config, clock=clock)
    try:
        solved = solver.solve(origin, destination, arrive_at, buffer_min)
    except _SameFirstSummary as same:
        card = same.card
        # 통행료가 있는 카드에 무료도로를 합치지 않는다.
        if _avoids_toll(option) and card.toll:
            raise RouteNotFoundError(NO_FREE_ROUTE_MESSAGE) from None
        # 첫 조회가 같아도 길이 다를 수 있으므로, 그 카드와 같은 출발시각의 상세 좌표로 확인한다.
        result.lookups += 1
        detailed = parse_detailed_route(provider.get_detailed_route(
            origin, destination, card.detail_depart_at, option.priority, option.avoid))
        if _path_signature(detailed["path"]) == card.path_signature:
            return card
        logger.info("경로 옵션 %s: 첫 조회는 %s와 같지만 경로가 달라 따로 계산합니다.", option.key, card.option.key)
        adapter.known_cards = []
        solved = solver.solve(origin, destination, arrive_at, buffer_min)  # 이미 받은 조회는 다시 하지 않는다

    result.lookups += 1
    card = _build_card(provider, adapter, solved, clock, arrive_at, buffer_min, data_source, origin, destination)
    same_path = next((existing for existing in result.cards if existing.path_signature == card.path_signature), None)
    if same_path is not None:
        return same_path
    result.cards.append(card)
    return None


def _build_card(provider, adapter: OptionRouteProvider, solved: DepartureResult, clock, arrive_at, buffer_min,
                data_source, origin, destination) -> RouteCard:
    """확정된 출발시각에 상세 경로를 한 번 받아 카드를 만든다."""
    option = adapter.option
    raw = provider.get_detailed_route(origin, destination, solved.depart_at, option.priority, option.avoid)
    detailed = parse_detailed_route(raw)
    if _avoids_toll(option) and detailed["toll"]:
        raise RouteNotFoundError(NO_FREE_ROUTE_MESSAGE)

    duration_sec = math.ceil(detailed["durationSec"])
    depart_at = solved.depart_at
    summary_sec = adapter.summaries[solved.depart_at].duration_sec
    if duration_sec != summary_sec:
        logger.warning("상세 소요시간이 요약과 다릅니다: 옵션=%s 출발=%s 요약=%d초 상세=%d초",
                       option.key, depart_at.isoformat(), summary_sec, duration_sec)
        # 상세 값으로도 늦지 않게 출발시각을 앞당긴다. 더 빨라진 경우는 확인하지 않은 시각이므로 늦추지 않는다.
        target = arrive_at - timedelta(minutes=buffer_min) if solved.buffer_applied else arrive_at
        if depart_at + timedelta(seconds=duration_sec) > target:
            depart_at = (target - timedelta(seconds=duration_sec)).replace(second=0, microsecond=0)
            if depart_at < clock():
                raise NoFeasibleDepartureError(NOT_IN_TIME_MESSAGE)

    return RouteCard(
        option=option,
        options=[option.key],
        name=_route_name(raw, option.label),
        depart_at=depart_at,
        duration_sec=duration_sec,
        distance_km=detailed["distanceKm"],
        toll=None if detailed["toll"] is None else int(detailed["toll"]),
        path=detailed["path"],
        buffer_applied=solved.buffer_applied,
        converged=solved.converged,
        data_source=data_source,
        detail_depart_at=solved.depart_at,
        first_summary=adapter.first,
    )


def _route_name(route: dict, fallback: str) -> str:
    """도로 이름별 거리를 더해 가장 긴 도로 + " 경유". 이름이 하나도 없으면 옵션 이름(label)."""
    lengths: dict[str, float] = {}
    for section in route.get("sections") or ():
        for road in section.get("roads") or ():
            name, distance = road.get("name"), road.get("distance")
            if isinstance(name, str) and name.strip() and isinstance(distance, int | float) and not isinstance(distance, bool):
                lengths[name.strip()] = lengths.get(name.strip(), 0) + distance
    if not lengths:
        return fallback
    return f"{max(lengths, key=lengths.get)} 경유"


def _avoids_toll(option: RouteOption) -> bool:
    return "toll" in option.avoid


def _path_signature(path: list[dict]) -> tuple[tuple[float, float], ...]:
    return tuple((point["lat"], point["lng"]) for point in path)
