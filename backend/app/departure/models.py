import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

# 한국은 서머타임이 없어서 고정 오프셋으로 충분하다. (Windows에는 IANA 시간대 DB가 기본으로 없다)
KST = timezone(timedelta(hours=9), "KST")


class TravelMode(StrEnum):
    """db/schema.sql의 search_history.travel_mode와 같은 값."""

    CAR = "car"
    TRANSIT = "transit"


@dataclass(frozen=True)
class Coordinate:
    """WGS84 십진수 좌표."""

    lat: float
    lng: float

    def __post_init__(self) -> None:
        if not (-90 <= self.lat <= 90 and -180 <= self.lng <= 180):
            raise ValueError(f"좌표 범위를 벗어났습니다: {self.lat}, {self.lng}")

    @classmethod
    def parse(cls, text: str) -> "Coordinate":
        """'35.2285,128.8894' 형식을 읽는다."""
        try:
            lat, lng = (float(part) for part in text.split(","))
        except ValueError:
            raise ValueError(f"좌표는 '위도,경도' 형식이어야 합니다: {text}") from None
        return cls(lat, lng)


@dataclass(frozen=True)
class DepartureResult:
    depart_at: datetime  # 권장 출발시각
    arrive_at: datetime  # 권장 출발시각에 출발했을 때의 예상 도착시각
    duration_sec: int  # 예상 소요시간
    target_arrive_at: datetime  # 도착 희망 시각
    buffer_min: int  # 요청한 여유시간
    buffer_applied: bool  # 여유시간을 반영했는지. 요청이 0분이거나, 지금 출발해도 여유를 둘 수 없으면 False
    provider_calls: int  # 소요시간 조회(RouteProvider.get_duration) 횟수
    converged: bool  # False면 호출 한도에 걸려, 확인된 것 중 가장 늦은(더 이른, 안전한) 시각을 돌려준 것

    @property
    def duration_min(self) -> int:
        return math.ceil(self.duration_sec / 60)

    def to_dict(self) -> dict:
        """API 응답(docs/api-spec.md)과 같은 필드 이름을 쓴다."""
        return {
            "departTime": self.depart_at.isoformat(),
            "arriveTime": self.arrive_at.isoformat(),
            "durationMin": self.duration_min,
            "targetArriveTime": self.target_arrive_at.isoformat(),
            "buffer": self.buffer_min,
            "bufferApplied": self.buffer_applied,
            "providerCalls": self.provider_calls,
            "converged": self.converged,
        }


# 카카오 미래 운행 정보 API의 priority·avoid 값
ROUTE_PRIORITIES = ("RECOMMEND", "TIME", "DISTANCE")
ROUTE_AVOIDS = ("ferries", "toll", "motorway", "schoolzone", "uturn")


@dataclass(frozen=True)
class RouteOption:
    """경로 비교의 경로 옵션. key는 API 카드의 id로 쓴다 (docs/api-spec.md GET /api/routes)."""

    key: str
    label: str
    priority: str = "RECOMMEND"
    avoid: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.priority not in ROUTE_PRIORITIES:
            raise ValueError(f"지원하지 않는 경로 우선순위입니다: {self.priority}")
        unknown = [value for value in self.avoid if value not in ROUTE_AVOIDS]
        if unknown:
            raise ValueError(f"지원하지 않는 회피 옵션입니다: {', '.join(unknown)}")


ROUTE_OPTIONS: dict[str, RouteOption] = {
    option.key: option
    for option in (
        RouteOption("recommend", "추천", "RECOMMEND"),
        RouteOption("time", "최단시간", "TIME"),
        RouteOption("distance", "최단거리", "DISTANCE"),
        RouteOption("free", "무료도로", "RECOMMEND", ("toll",)),
    )
}
# 우선순위를 정하지 않은 조회(get_duration, /api/departure)는 추천 경로다. 경로 비교의 recommend와 캐시를 함께 쓴다.
DEFAULT_ROUTE_OPTION = ROUTE_OPTIONS["recommend"]


@dataclass(frozen=True)
class RouteSummary:
    """한 출발시각, 한 경로 옵션의 요약 (카카오 routes[0].summary)."""

    duration_sec: int  # 예상 소요시간
    distance_m: int  # 거리
    toll: int | None  # 통행료(원). 응답에 없으면 None
