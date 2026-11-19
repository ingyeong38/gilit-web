"""API 요청·응답 모델. 필드 설명과 예시는 /docs(Swagger)에 그대로 나온다."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.departure import KST, ROUTE_OPTIONS, Coordinate, TravelMode

BUFFER_CHOICES = (0, 5, 10, 15)  # 프론트 검색 화면의 여유시간 버튼과 같다


class ErrorResponse(BaseModel):
    message: str = Field(description="사용자에게 그대로 보여 줄 수 있는 한국어 문장")


class FavoriteResponse(BaseModel):
    """즐겨찾기 하나 (docs/api-spec.md "즐겨찾기"). 프론트 목업(favorites.json)의 필드에 좌표를 더했다."""

    id: str = Field(description="즐겨찾기 id. DB BIGINT를 문자열로", examples=["1"])
    name: str = Field(description="별칭 (place_name)", examples=["집"])
    address: str | None = Field(description="주소. 없을 수 있다", examples=["경상남도 김해시 내외중앙로 47"])
    type: Literal["집", "학교", "회사", "기타"] = Field(description="분류 (label)")
    lat: float = Field(description="위도", examples=[35.2285])
    lng: float = Field(description="경도", examples=[128.8894])


class HistoryResponse(BaseModel):
    """검색 기록 카드 하나 (docs/api-spec.md "검색 기록"). 목업(history.json)의 필드에 다시 검색용 값을 더했다.

    같은 검색(출발지, 목적지, 도착 시각의 시:분)은 가장 최근 것 하나로 묶여 있다. id는 그 대표 행의 id다.
    """

    id: str = Field(description="기록 id (대표 행). DELETE /api/history?id=에 쓴다", examples=["12"])
    from_: str | None = Field(alias="from", description="출발지 이름", examples=["김해시청"])
    to: str | None = Field(description="목적지 이름", examples=["동의대학교"])
    arriveTime: str = Field(description="도착 희망 시각 (ISO 8601, KST)", examples=["2026-11-02T09:00:00+09:00"])
    buffer: int = Field(description="여유시간(분)", examples=[10])
    departTime: str | None = Field(description="추천 경로의 권장 출발 시각. 없을 수 있다", examples=["2026-11-02T08:12:00+09:00"])
    fromLat: float | None = Field(description="출발지 위도. 없을 수 있다")
    fromLng: float | None = Field(description="출발지 경도")
    toLat: float | None = Field(description="목적지 위도")
    toLng: float | None = Field(description="목적지 경도")

    model_config = ConfigDict(populate_by_name=True)


class DailySearchCount(BaseModel):
    date: str = Field(description="날짜 (YYYY-MM-DD, KST)", examples=["2026-11-19"])
    count: int = Field(description="그날 검색 횟수. 없으면 0", examples=[3])


class MyStatsResponse(BaseModel):
    """내 이용 통계 (docs/api-spec.md "내 이용 통계"). 검색 기록(search_history)으로 센다."""

    range: Literal["week"] = Field(description="기간. 지금은 week(최근 7일, 오늘 포함)만 있다")
    from_: str = Field(alias="from", description="첫날 (YYYY-MM-DD, KST)", examples=["2026-11-13"])
    to: str = Field(description="마지막 날 = 오늘 (YYYY-MM-DD, KST)", examples=["2026-11-19"])
    daily: list[DailySearchCount] = Field(description="날짜별 검색 횟수 7개, 오래된 날 → 오늘. 검색이 없는 날은 0")
    total: int = Field(description="7일 합계 (daily의 count 합)", examples=[12])
    topPlace: str | None = Field(
        description="가장 많이 간 곳 (목적지 이름 기준 최다, 동률이면 가장 최근 검색). 없으면 null", examples=["동의대학교"]
    )

    model_config = ConfigDict(populate_by_name=True)


class NicknameErrorResponse(BaseModel):
    message: str = Field(description="사용자에게 그대로 보여 줄 수 있는 한국어 문장")
    code: Literal["empty", "length", "chars", "spaces", "required"] = Field(
        description="닉네임 규칙 실패 코드. 프론트는 이 값으로 문구를 고른다 (frontend/js/mypage.js NICKNAME_MESSAGES)"
    )


class UserResponse(BaseModel):
    """회원 API가 돌려주는 사용자 객체 (docs/api-spec.md "사용자 객체")."""

    id: str = Field(description="사용자 id. DB BIGINT를 문자열로 내려준다", examples=["1"])
    name: str = Field(description="닉네임 (users.nickname)", examples=["길잇"])
    email: str | None = Field(description="소문자 이메일. 카카오 가입자는 없을 수 있다", examples=["user@example.com"])
    provider: Literal["email", "google", "kakao"] = Field(description="이번 세션의 로그인 방식")


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


# --- GET /api/routes/graph (소요시간 그래프) ---

GRAPH_CARD_LIMIT = 4  # GET /api/routes 카드 수 상한과 같다
GRAPH_CARD_WINDOW = timedelta(hours=24)  # card 출발시각은 arrive 전 24시간 안
CARD_FORMAT_MESSAGE = "card는 <경로 id>@<출발시각> 형식이어야 합니다 (예: recommend@2026-11-06T08:12:00+09:00)."
CARD_COUNT_MESSAGE = f"card는 1~{GRAPH_CARD_LIMIT}개 보내 주세요."
CARD_DUPLICATE_MESSAGE = "같은 경로 id의 card가 두 번 있습니다."
CARD_TIME_MESSAGE = "card의 출발시각은 시간대가 있는 ISO 8601 형식이어야 합니다 (예: recommend@2026-11-06T08:12:00+09:00)."
CARD_RANGE_MESSAGE = "card의 출발시각은 도착 희망 시각 전 24시간 안이어야 합니다."


def card_option_message(keys) -> str:
    # 사용자가 보낸 id는 문장에 넣지 않는다 (화면에 그대로 나올 수 있다).
    return f"card의 경로 id는 {', '.join(keys)} 중 하나여야 합니다."


@dataclass(frozen=True)
class CardParam:
    id: str
    depart_at: datetime


class GraphQuery(RouteQuery):
    """GET /api/routes/graph 쿼리. from·to·arrive·좌표 검증은 RouteQuery와 같다 (좌표는 위도·경도를 함께).

    buffer는 프론트가 같은 검색 조건을 그대로 보내므로 받기만 하고 쓰지 않는다 (어떤 값이어도 오류를 내지 않는다).
    card는 /api/routes 카드의 id와 departTime을 `<id>@<departTime>`로 이어 1~4개 반복해 보낸다.
    """

    buffer: str | None = Field(default=None, description="받지만 쓰지 않는다. 어떤 값이어도 오류가 아니다")
    card: list[Annotated[str, StringConstraints(max_length=64)]] = Field(
        default_factory=list,
        description="`<경로 id>@<권장 출발시각>`, 1~4개 반복. id는 recommend·time·distance·free, 시각은 시간대 포함 ISO 8601 "
        "(`+`는 `%2B`). 마지막 @ 기준으로 나눈다",
        examples=[["recommend@2026-11-06T08:12:00+09:00"]],
    )
    _cards: list[CardParam] = PrivateAttr(default_factory=list)

    @field_validator("buffer")
    @classmethod
    def check_buffer(cls, value):  # RouteQuery.check_buffer를 덮어쓴다: 그래프는 buffer를 쓰지 않는다
        return value

    @model_validator(mode="after")
    def check_cards(self) -> "GraphQuery":
        # 여기서 던지는 문장은 그대로 400 message가 된다 (errors.validation_message).
        if not 1 <= len(self.card) <= GRAPH_CARD_LIMIT:
            raise ValueError(CARD_COUNT_MESSAGE)
        cards = [self._parse_card(value) for value in self.card]
        if len({card.id for card in cards}) != len(cards):
            raise ValueError(CARD_DUPLICATE_MESSAGE)
        self._cards = cards
        return self

    def _parse_card(self, value: str) -> CardParam:
        card_id, separator, text = value.rpartition("@")
        if not separator or not card_id:
            raise ValueError(CARD_FORMAT_MESSAGE)
        if card_id not in ROUTE_OPTIONS:
            raise ValueError(card_option_message(ROUTE_OPTIONS))
        try:
            depart_at = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError(CARD_TIME_MESSAGE) from None
        if depart_at.tzinfo is None:
            raise ValueError(CARD_TIME_MESSAGE)
        # 지난 출발시각은 거절하지 않는다 (지난 슬롯만 서버가 뺀다).
        if not self.arrive - GRAPH_CARD_WINDOW <= depart_at < self.arrive:
            raise ValueError(CARD_RANGE_MESSAGE)
        return CardParam(card_id, depart_at.astimezone(KST))

    def cards(self) -> list[CardParam]:
        """검증을 마친 card. 요청 순서대로."""
        return list(self._cards)


class GraphPointResponse(BaseModel):
    departTime: datetime = Field(description="슬롯 출발시각 (한국 시간 +09:00, 분 단위)")
    durationMin: int = Field(ge=0, description="그 시각에 출발했을 때의 예상 소요시간(분, 올림)")


class RouteGraphResponse(BaseModel):
    routeId: str = Field(description="요청한 card의 id 그대로 (= GET /api/routes 카드 id)")
    points: list[GraphPointResponse] = Field(description="시간순. 실패·지난 슬롯은 빠진다")


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
