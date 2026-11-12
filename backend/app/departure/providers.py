import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, time

from app.departure.errors import RouteNotFoundError
from app.departure.models import DEFAULT_ROUTE_OPTION, KST, Coordinate, RouteOption, RouteSummary, TravelMode

EARTH_RADIUS_KM = 6371.0
MINUTES_PER_DAY = 24 * 60
SAME_POINT_KM = 0.005  # 카카오는 출발지와 도착지가 5m 이내면 경로를 주지 않는다 (result_code=104)
MOCK_PATH_POINTS = 13  # 가짜 경로선의 좌표 개수


class RouteProvider(ABC):
    """출발시각에 따른 소요시간을 알려 주는 길찾기 데이터 출처.

    실제 API 어댑터(KakaoRouteProvider 등)는 이 클래스를 상속해 get_duration만 구현한다.
    DepartureSolver는 이 인터페이스에만 의존하므로 구현을 바꿔도 엔진 코드는 그대로 둔다.

    구현은 FIFO(먼저 출발하면 늦게 도착하지 않는다)를 따른다고 가정한다.
    실제 교통 데이터는 대체로 이를 만족하고, 이 가정이 있어야 이분탐색으로 가장 늦은 출발시각을 찾을 수 있다.

    경로 비교(GET /api/routes)를 지원하는 Provider는 get_route_summary와 get_detailed_route도 구현한다.
    출발시각 역산만 하는 Provider는 구현하지 않아도 된다.
    """

    @abstractmethod
    def get_duration(
        self,
        origin: Coordinate,
        dest: Coordinate,
        depart_at: datetime,
        travel_mode: TravelMode = TravelMode.CAR,
    ) -> int:
        """depart_at에 출발했을 때 예상 소요시간(초, 0 이상)."""

    def get_route_summary(
        self,
        origin: Coordinate,
        dest: Coordinate,
        depart_at: datetime,
        option: RouteOption = DEFAULT_ROUTE_OPTION,
    ) -> RouteSummary:
        """경로 옵션(우선순위·회피)별 자동차 경로의 소요시간·거리·통행료."""
        raise NotImplementedError(f"{type(self).__name__}는 경로 옵션별 요약을 지원하지 않습니다.")

    def get_detailed_route(
        self,
        origin: Coordinate,
        dest: Coordinate,
        depart_at: datetime,
        priority: str,
        avoid: tuple[str, ...] = (),
    ) -> dict:
        """카카오 routes[0] 형식(summary, sections[].roads[].vertexes)의 상세 경로."""
        raise NotImplementedError(f"{type(self).__name__}는 상세 경로를 지원하지 않습니다.")

    def search_places(self, query: str) -> list[dict]:
        """장소 검색 [{id, name, address, lat, lng}]. 좌표 없이 이름만 온 경로 비교 요청에 쓴다."""
        raise NotImplementedError(f"{type(self).__name__}는 장소 검색을 지원하지 않습니다.")


@dataclass(frozen=True)
class CongestionPeak:
    center: time  # 혼잡이 가장 심한 시각
    spread_min: float  # 혼잡이 퍼지는 정도(분, 정규분포의 표준편차)
    extra_ratio: float  # 가장 심할 때 늘어나는 소요시간 비율 (0.6이면 60% 증가)


COMMUTE_PEAKS = (
    CongestionPeak(center=time(8, 0), spread_min=45, extra_ratio=0.6),
    CongestionPeak(center=time(18, 30), spread_min=60, extra_ratio=0.5),
)


@dataclass(frozen=True)
class MockRouteProfile:
    """MockRouteProvider의 경로 옵션별 가짜 특성. 계수가 모두 1이면 get_duration과 같은 값이 나온다."""

    road_name: str  # 상세 경로에서 가장 긴 도로의 이름
    detour_factor: float = 1.0  # 기본 우회 비율에 곱한다 (거리)
    speed_factor: float = 1.0  # 평균 속도에 곱한다
    congestion_factor: float = 1.0  # 혼잡 지연에 곱한다. 1.2 이하면 FIFO가 유지된다 (tests/test_providers_and_config.py)
    toll_per_km: int = 0  # km당 통행료(원)
    bend: float = 0.0  # 경로선이 직선에서 휘는 정도 (출발~도착 거리 대비, 부호는 방향)


MOCK_ROUTE_PROFILES = {
    "recommend": MockRouteProfile("가상 고속도로", toll_per_km=50, bend=0.08),
    "time": MockRouteProfile(
        "가상 도시고속도로", detour_factor=1.08, speed_factor=1.2, congestion_factor=0.8, toll_per_km=70, bend=-0.12
    ),
    "distance": MockRouteProfile(
        "가상 간선도로", detour_factor=0.88, speed_factor=0.8, congestion_factor=1.1, toll_per_km=20, bend=0.03
    ),
    "free": MockRouteProfile("가상 국도", detour_factor=1.04, speed_factor=0.85, congestion_factor=1.2, bend=-0.05),
}


def mock_profile(priority: str, avoid: tuple[str, ...] = ()) -> MockRouteProfile:
    """카카오 요청 값(priority, avoid)에 맞는 가짜 특성. 통행료 회피가 우선이다."""
    if "toll" in avoid:
        return MOCK_ROUTE_PROFILES["free"]
    return MOCK_ROUTE_PROFILES.get(priority.lower(), MOCK_ROUTE_PROFILES["recommend"])


class MockRouteProvider(RouteProvider):
    """직선거리와 출발 시간대로 소요시간을 흉내 내는 가짜 구현. 실제 교통 정보와 무관하다.

    소요시간 = 기본 소요시간 + 혼잡 지연
    - 기본 소요시간: 직선거리 x 우회 비율 / 평균 속도 (대중교통은 대기 시간을 더한다)
    - 혼잡 지연: 출퇴근 시각 근처에서 늘어난다. 장거리라도 혼잡 구간에 머무는 시간은 한정되므로
      congestion_cap_min 분량까지만 늘린다. 덕분에 FIFO 가정도 깨지지 않는다.

    경로 비교용으로 옵션마다 거리·속도·혼잡·통행료를 다르게 둔다(MOCK_ROUTE_PROFILES). 카카오 없이
    비교 화면을 만들 수 있게 하려는 것이다. 상세 경로의 좌표는 출발지와 목적지를 잇는 가짜 곡선이다.
    """

    SPEED_KMH = {TravelMode.CAR: 40.0, TravelMode.TRANSIT: 25.0}
    TRANSIT_CONGESTION_FACTOR = 0.5  # 대중교통은 도로 혼잡의 영향을 덜 받는다

    def __init__(
        self,
        peaks: tuple[CongestionPeak, ...] = COMMUTE_PEAKS,
        detour_ratio: float = 1.3,
        transit_wait_min: float = 10,
        congestion_cap_min: float = 60,
        min_duration_sec: int = 60,
    ) -> None:
        self.peaks = peaks
        self.detour_ratio = detour_ratio
        self.transit_wait_min = transit_wait_min
        self.congestion_cap_min = congestion_cap_min
        self.min_duration_sec = min_duration_sec

    def road_km(
        self, origin: Coordinate, dest: Coordinate, profile: MockRouteProfile = MOCK_ROUTE_PROFILES["recommend"]
    ) -> float:
        return haversine_km(origin, dest) * self.detour_ratio * profile.detour_factor

    def base_duration(
        self,
        origin: Coordinate,
        dest: Coordinate,
        travel_mode: TravelMode,
        profile: MockRouteProfile = MOCK_ROUTE_PROFILES["recommend"],
    ) -> float:
        """혼잡이 없을 때의 소요시간(초)."""
        seconds = self.road_km(origin, dest, profile) / (self.SPEED_KMH[travel_mode] * profile.speed_factor) * 3600
        if travel_mode is TravelMode.TRANSIT:
            seconds += self.transit_wait_min * 60
        return max(seconds, self.min_duration_sec)

    def congestion_ratio(self, depart_at: datetime) -> float:
        local = depart_at.astimezone(KST)
        minute_of_day = local.hour * 60 + local.minute + local.second / 60
        ratio = 0.0
        for peak in self.peaks:
            center = peak.center.hour * 60 + peak.center.minute
            distance = abs(minute_of_day - center)
            distance = min(distance, MINUTES_PER_DAY - distance)  # 자정을 넘는 혼잡도 이어지게 한다
            ratio += peak.extra_ratio * math.exp(-(distance**2) / (2 * peak.spread_min**2))
        return ratio

    def get_duration(
        self,
        origin: Coordinate,
        dest: Coordinate,
        depart_at: datetime,
        travel_mode: TravelMode = TravelMode.CAR,
    ) -> int:
        return self._duration(origin, dest, depart_at, travel_mode, MOCK_ROUTE_PROFILES["recommend"])

    def get_route_summary(
        self,
        origin: Coordinate,
        dest: Coordinate,
        depart_at: datetime,
        option: RouteOption = DEFAULT_ROUTE_OPTION,
    ) -> RouteSummary:
        return self._summary(origin, dest, depart_at, mock_profile(option.priority, option.avoid))

    def get_detailed_route(
        self,
        origin: Coordinate,
        dest: Coordinate,
        depart_at: datetime,
        priority: str,
        avoid: tuple[str, ...] = (),
    ) -> dict:
        """카카오 상세 응답과 같은 모양. summary는 같은 옵션·출발시각의 get_route_summary와 같다."""
        profile = mock_profile(priority, tuple(avoid))
        summary = self._summary(origin, dest, depart_at, profile)
        points = _mock_path(origin, dest, profile.bend)
        # 앞뒤 짧은 연결도로와 가운데 긴 본선으로 나눈다. 경계 좌표는 카카오처럼 양쪽 도로에 모두 들어간다.
        cut1, cut2 = MOCK_PATH_POINTS // 4, MOCK_PATH_POINTS - 1 - MOCK_PATH_POINTS // 4
        pieces = [
            ("가상 연결도로", points[: cut1 + 1]),
            (profile.road_name, points[cut1 : cut2 + 1]),
            ("가상 연결도로", points[cut2:]),
        ]
        segments = MOCK_PATH_POINTS - 1
        roads = [
            {
                "name": name,
                "distance": round(summary.distance_m * (len(piece) - 1) / segments),
                "duration": round(summary.duration_sec * (len(piece) - 1) / segments),
                "vertexes": [value for point in piece for value in (point.lng, point.lat)],
            }
            for name, piece in pieces
        ]
        return {
            "result_code": 0,
            "result_msg": "길찾기 성공",
            "summary": {"duration": summary.duration_sec, "distance": summary.distance_m, "fare": {"toll": summary.toll}},
            "sections": [{"distance": summary.distance_m, "duration": summary.duration_sec, "roads": roads}],
        }

    def _duration(
        self,
        origin: Coordinate,
        dest: Coordinate,
        depart_at: datetime,
        travel_mode: TravelMode,
        profile: MockRouteProfile,
    ) -> int:
        base = self.base_duration(origin, dest, travel_mode, profile)
        ratio = self.congestion_ratio(depart_at) * profile.congestion_factor
        if travel_mode is TravelMode.TRANSIT:
            ratio *= self.TRANSIT_CONGESTION_FACTOR
        delay = min(base, self.congestion_cap_min * 60) * ratio
        return math.ceil(base + delay)

    def _summary(self, origin: Coordinate, dest: Coordinate, depart_at: datetime, profile: MockRouteProfile) -> RouteSummary:
        """경로 비교용 요약 (자동차). 카카오처럼 출발지와 도착지가 5m 이내면 경로가 없다."""
        if haversine_km(origin, dest) < SAME_POINT_KM:
            raise RouteNotFoundError("경로를 찾을 수 없습니다: 출발지와 도착지가 5 m 이내입니다 (result_code=104)", 104)
        road_km = self.road_km(origin, dest, profile)
        return RouteSummary(
            duration_sec=self._duration(origin, dest, depart_at, TravelMode.CAR, profile),
            distance_m=round(road_km * 1000),
            toll=round(road_km * profile.toll_per_km / 100) * 100,  # 100원 단위
        )


def haversine_km(a: Coordinate, b: Coordinate) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    d_lat = lat2 - lat1
    d_lng = math.radians(b.lng - a.lng)
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _mock_path(origin: Coordinate, dest: Coordinate, bend: float) -> list[Coordinate]:
    """출발지에서 목적지까지 직선을 bend만큼 옆으로 휜 곡선. 양 끝은 출발지·목적지 그대로다. 실제 도로와 무관하다."""
    d_lat, d_lng = dest.lat - origin.lat, dest.lng - origin.lng
    points = []
    for i in range(MOCK_PATH_POINTS):
        t = i / (MOCK_PATH_POINTS - 1)
        offset = bend * math.sin(math.pi * t)
        points.append(
            Coordinate(round(origin.lat + d_lat * t + d_lng * offset, 7), round(origin.lng + d_lng * t - d_lat * offset, 7))
        )
    return points
