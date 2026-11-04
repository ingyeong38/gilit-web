import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, time

from app.departure.models import KST, Coordinate, TravelMode

EARTH_RADIUS_KM = 6371.0
MINUTES_PER_DAY = 24 * 60


class RouteProvider(ABC):
    """출발시각에 따른 소요시간을 알려 주는 길찾기 데이터 출처.

    실제 API 어댑터(KakaoRouteProvider 등)는 이 클래스를 상속해 get_duration만 구현한다.
    DepartureSolver는 이 인터페이스에만 의존하므로 구현을 바꿔도 엔진 코드는 그대로 둔다.

    구현은 FIFO(먼저 출발하면 늦게 도착하지 않는다)를 따른다고 가정한다.
    실제 교통 데이터는 대체로 이를 만족하고, 이 가정이 있어야 이분탐색으로 가장 늦은 출발시각을 찾을 수 있다.
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


@dataclass(frozen=True)
class CongestionPeak:
    center: time  # 혼잡이 가장 심한 시각
    spread_min: float  # 혼잡이 퍼지는 정도(분, 정규분포의 표준편차)
    extra_ratio: float  # 가장 심할 때 늘어나는 소요시간 비율 (0.6이면 60% 증가)


COMMUTE_PEAKS = (
    CongestionPeak(center=time(8, 0), spread_min=45, extra_ratio=0.6),
    CongestionPeak(center=time(18, 30), spread_min=60, extra_ratio=0.5),
)


class MockRouteProvider(RouteProvider):
    """직선거리와 출발 시간대로 소요시간을 흉내 내는 가짜 구현. 실제 교통 정보와 무관하다.

    소요시간 = 기본 소요시간 + 혼잡 지연
    - 기본 소요시간: 직선거리 x 우회 비율 / 평균 속도 (대중교통은 대기 시간을 더한다)
    - 혼잡 지연: 출퇴근 시각 근처에서 늘어난다. 장거리라도 혼잡 구간에 머무는 시간은 한정되므로
      congestion_cap_min 분량까지만 늘린다. 덕분에 FIFO 가정도 깨지지 않는다.
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

    def base_duration(self, origin: Coordinate, dest: Coordinate, travel_mode: TravelMode) -> float:
        """혼잡이 없을 때의 소요시간(초)."""
        road_km = haversine_km(origin, dest) * self.detour_ratio
        seconds = road_km / self.SPEED_KMH[travel_mode] * 3600
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
        base = self.base_duration(origin, dest, travel_mode)
        ratio = self.congestion_ratio(depart_at)
        if travel_mode is TravelMode.TRANSIT:
            ratio *= self.TRANSIT_CONGESTION_FACTOR
        delay = min(base, self.congestion_cap_min * 60) * ratio
        return math.ceil(base + delay)


def haversine_km(a: Coordinate, b: Coordinate) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    d_lat = lat2 - lat1
    d_lng = math.radians(b.lng - a.lng)
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))
