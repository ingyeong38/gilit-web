"""API 요청·응답 모델. 필드 설명과 예시는 /docs(Swagger)에 그대로 나온다."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.departure import KST, Coordinate, TravelMode

BUFFER_CHOICES = (0, 5, 10, 15)  # 프론트 검색 화면의 여유시간 버튼과 같다


class ErrorResponse(BaseModel):
    message: str = Field(description="사용자에게 그대로 보여 줄 수 있는 한국어 문장")


class Place(BaseModel):
    """장소 검색 결과의 이름과 좌표를 그대로 받는다."""

    name: str = Field(min_length=1, max_length=100, description="장소 이름 (search_history에 남길 이름)")
    lat: float = Field(ge=-90, le=90, description="위도 (WGS84 십진수)")
    lng: float = Field(ge=-180, le=180, description="경도 (WGS84 십진수)")

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("빈 이름")
        return value


class DepartureRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "origin": {"name": "김해시청", "lat": 35.2285, "lng": 128.8894},
                    "destination": {"name": "동의대학교", "lat": 35.1441, "lng": 129.0336},
                    "arrive_at": "2026-11-06T09:00:00+09:00",
                    "buffer_min": 10,
                    "travel_mode": "car",
                }
            ]
        }
    )

    origin: Place = Field(description="출발지")
    destination: Place = Field(description="목적지")
    arrive_at: datetime = Field(
        description="도착 희망 시각 (ISO 8601). 시간대가 없으면 한국 시간으로 본다. 카카오 데이터는 내일 이후 시각을 권장한다."
    )
    buffer_min: StrictInt = Field(
        default=0,
        description="여유시간(분). 0, 5, 10, 15 중 하나",
        json_schema_extra={"enum": list(BUFFER_CHOICES)},
    )
    travel_mode: TravelMode = Field(default=TravelMode.CAR, description="이동수단. 카카오 데이터는 car만 된다")

    @field_validator("arrive_at", mode="before")
    @classmethod
    def require_iso_text(cls, value: object) -> object:
        # 숫자를 유닉스 시각으로 해석하는 pydantic 기본 동작을 막는다.
        if not isinstance(value, str):
            raise ValueError("ISO 8601 문자열이 아님")
        return value

    @field_validator("arrive_at")
    @classmethod
    def assume_kst(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=KST)

    @field_validator("buffer_min")
    @classmethod
    def check_buffer(cls, value: int) -> int:
        if value not in BUFFER_CHOICES:
            raise ValueError("허용되지 않은 여유시간")
        return value


class DepartureResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "recommended_depart_at": "2026-11-06T08:07:00+09:00",
                    "duration_min": 43,
                    "expected_arrive_at": "2026-11-06T08:49:40+09:00",
                    "desired_arrive_at": "2026-11-06T09:00:00+09:00",
                    "buffer_min": 10,
                    "buffer_applied": True,
                    "converged": True,
                    "api_calls": 4,
                    "data_source": "kakao",
                }
            ]
        }
    )

    recommended_depart_at: datetime = Field(description="권장 출발시각 (한국 시간, 분 단위)")
    duration_min: int = Field(description="권장 출발시각에 출발했을 때의 예상 소요시간(분, 올림)")
    expected_arrive_at: datetime = Field(description="권장 출발시각에 출발했을 때의 예상 도착시각")
    desired_arrive_at: datetime = Field(description="요청한 도착 희망 시각")
    buffer_min: int = Field(description="요청한 여유시간(분)")
    buffer_applied: bool = Field(
        description="여유시간을 반영했는지. 요청이 0분이거나, 지금 출발해도 여유를 둘 수 없으면 false"
    )
    converged: bool = Field(
        description="false면 조회 한도에 걸려, 확인된 시각 중 가장 늦은(더 이른, 안전한) 시각을 돌려준 것"
    )
    api_calls: int = Field(description="이번 계산의 소요시간 조회 횟수 (캐시 적중 포함)")
    data_source: Literal["mock", "kakao"] = Field(description="소요시간 데이터 출처 (ROUTE_PROVIDER)")


# --- GET /api/routes (경로 비교) ---


class RouteQuery(BaseModel):
    """GET /api/routes 쿼리. 필드 이름은 프론트 URL 쿼리와 같은 camelCase다."""

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from", min_length=1, max_length=100, description="출발지 이름")
    to: str = Field(min_length=1, max_length=100, description="목적지 이름")
    arrive: datetime = Field(description="도착 희망 시각 (ISO 8601). 시간대가 없으면 한국 시간. `+`는 `%2B`로 보낸다")
    buffer: int = Field(default=0, description="여유시간(분). 0, 5, 10, 15 중 하나", json_schema_extra={"enum": list(BUFFER_CHOICES)})
    fromLat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False, description="출발지 위도. fromLng와 함께 보낸다")
    fromLng: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False, description="출발지 경도")
    toLat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False, description="목적지 위도. toLng와 함께 보낸다")
    toLng: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False, description="목적지 경도")

    @field_validator("from_", "to")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("빈 이름")
        return value

    @field_validator("arrive")
    @classmethod
    def assume_kst(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=KST)

    @field_validator("buffer")
    @classmethod
    def check_buffer(cls, value: int) -> int:
        if value not in BUFFER_CHOICES:
            raise ValueError("허용되지 않은 여유시간")
        return value

    @model_validator(mode="after")
    def check_places(self) -> "RouteQuery":
        # 여기서 던지는 문장은 그대로 400 message가 된다 (errors.validation_message).
        if self.from_ == self.to:
            raise ValueError("출발지와 다른 목적지를 입력해 주세요.")
        if (self.fromLat is None) != (self.fromLng is None):
            raise ValueError("출발지 위도와 경도를 함께 보내 주세요.")
        if (self.toLat is None) != (self.toLng is None):
            raise ValueError("목적지 위도와 경도를 함께 보내 주세요.")
        return self

    def origin(self) -> Coordinate | None:
        return None if self.fromLat is None else Coordinate(self.fromLat, self.fromLng)

    def destination(self) -> Coordinate | None:
        return None if self.toLat is None else Coordinate(self.toLat, self.toLng)


class LatLng(BaseModel):
    lat: float
    lng: float


class AiSummary(BaseModel):
    title: str
    text: str


class RouteCardResponse(BaseModel):
    """경로 비교 카드. 필드는 프론트(js/mock/routes.json)와 같은 camelCase다."""

    id: str = Field(description="카드를 만든 경로 옵션: recommend, time, distance, free")
    options: list[str] = Field(description="이 카드에 합쳐진 옵션. 같은 길이면 [\"recommend\", \"time\"]")
    label: str = Field(description="옵션 이름: 추천, 최단시간, 최단거리, 무료도로")
    name: str = Field(description="가장 긴 도로 이름 + ' 경유'. 도로 이름이 없으면 label")
    departTime: datetime = Field(description="권장 출발시각 (한국 시간, 분 단위)")
    arriveTime: datetime = Field(description="예상 도착시각 (권장 출발시각 + 상세 경로 소요시간)")
    durationMin: int = Field(description="예상 소요시간(분, 올림)")
    distanceKm: float = Field(description="거리(km)")
    toll: int | None = Field(description="통행료(원). 카카오가 주지 않으면 null")
    fuel: int | None = Field(description="예상 유류비(원). 아직 제공하지 않아 null")
    bufferApplied: bool = Field(description="여유시간을 반영했는지")
    converged: bool = Field(description="false면 조회 한도에 걸려 확인된 가장 늦은(안전한) 시각")
    dataSource: Literal["mock", "kakao"] = Field(description="데이터 출처 (ROUTE_PROVIDER)")
    path: list[LatLng] = Field(description="지도에 그릴 경로 좌표. 소요시간·거리·통행료와 같은 상세 응답")
    aiSummary: AiSummary = Field(description="화면 호환용 고정 안내 문구")
