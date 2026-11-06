"""카카오 상세 응답과 기존 출발시각 엔진을 연결한다. 경로별 응답을 섞지 않는다."""
import math
from datetime import timedelta

from app.departure import Coordinate, DepartureSolver, TravelMode
from app.departure.errors import RouteProviderError
from app.departure.providers import RouteProvider


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


class DetailedRouteProvider(RouteProvider):
    """요청 안에서 최종 계산에 쓰인 상세 응답을 보관한다. 다른 조회 결과를 재결합하지 않는다."""
    def __init__(self, provider, priority):
        self.provider = provider
        self.priority = priority
        self.snapshots = {}

    def get_duration(self, origin, dest, depart_at, travel_mode=TravelMode.CAR):
        key = (origin, dest, depart_at)
        if key not in self.snapshots:
            self.snapshots[key] = parse_detailed_route(self.provider.get_detailed_route(origin, dest, depart_at, self.priority))
        return math.ceil(self.snapshots[key]["durationSec"])


def find_routes(provider, solver_config, clock, origin, destination, arrive, buffer):
    routes, seen = [], set()
    for priority, label in [("RECOMMEND", "추천"), ("TIME", "최단시간"), ("DISTANCE", "최단거리")]:
        detailed = DetailedRouteProvider(provider, priority)
        result = DepartureSolver(detailed, solver_config, clock=clock).solve(origin, destination, arrive, buffer)
        snapshot = detailed.snapshots[(origin, destination, result.depart_at)]
        signature = tuple((p["lat"], p["lng"]) for p in snapshot["path"])
        if signature in seen:
            continue
        seen.add(signature)
        routes.append({
            "id": f"kakao-{priority.lower()}", "label": label, "name": f"카카오 {label} 경로",
            "departTime": result.depart_at.isoformat(),
            "arriveTime": (result.depart_at + timedelta(seconds=snapshot["durationSec"])).isoformat(),
            "durationMin": math.ceil(snapshot["durationSec"] / 60),
            "distanceKm": snapshot["distanceKm"], "toll": snapshot["toll"], "fuel": None,
            "path": snapshot["path"], "dataSource": "kakao", "bufferApplied": result.buffer_applied,
            "converged": result.converged,
            "aiSummary": {"title": f"카카오 {label} 경로", "text": "거리·소요시간·경로선은 같은 상세 길찾기 응답 기준입니다."},
        })
    return routes


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
