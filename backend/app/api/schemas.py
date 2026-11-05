"""API 요청·응답 모델. 필드 설명과 예시는 /docs(Swagger)에 그대로 나온다."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from app.departure import KST, TravelMode

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
