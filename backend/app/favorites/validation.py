"""즐겨찾기 입력 검증 (설계 3-6). Pydantic 기본 검증에 맡기지 않고 직접 검사해 400 + 명세 문구로 알린다.

공통 오류 변환(app/api/errors.py)의 "name" 문구와 섞이지 않게 하고, 문자열 "35.1"·불리언 같은 값의 자동 변환도 막는다.
"""

import math
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.favorites.errors import (
    ADDRESS_INVALID,
    COORDINATES_INVALID,
    NAME_INVALID,
    NOTHING_TO_UPDATE,
    PLACE_FIELDS_TOGETHER,
    TYPE_INVALID,
    FavoriteError,
)

FAVORITE_TYPES = ("집", "학교", "회사", "기타")
DEFAULT_TYPE = "기타"
NAME_MAX = 100  # favorite_places.place_name VARCHAR(100)
ADDRESS_MAX = 255  # favorite_places.address VARCHAR(255)
PLACE_FIELDS = ("address", "lat", "lng")
COORDINATE_DECIMALS = 7  # favorite_places.lat·lng DECIMAL(10,7)

_MISSING = object()


@dataclass(frozen=True)
class Coordinates:
    lat: float
    lng: float


@dataclass(frozen=True)
class NewFavorite:
    name: str
    type: str
    address: str | None
    coordinates: Coordinates | None  # None이면 서버가 장소를 찾는다


@dataclass(frozen=True)
class FavoriteChanges:
    """PATCH로 바꿀 값. None은 바꾸지 않음. 장소(address·좌표)는 셋을 함께 바꾼다."""

    name: str | None = None
    type: str | None = None
    place: tuple[str | None, Coordinates] | None = None  # (address, 좌표)


def _invalid(message: str) -> FavoriteError:
    return FavoriteError(400, message)


def clean_text(value: Any, max_length: int, message: str, required: bool) -> str | None:
    """NFC로 맞추고 앞뒤 공백을 지우고 연속 공백을 하나로 줄인다. 제어·서식 문자(줄바꿈, 제로폭 등)는 거부한다."""
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise _invalid(message)
    text = unicodedata.normalize("NFC", value)
    if any(unicodedata.category(ch).startswith("C") for ch in text if ch not in " \t"):
        raise _invalid(message)
    text = " ".join(text.split())
    if not text:
        if required:
            raise _invalid(message)
        return None
    if len(text) > max_length:
        raise _invalid(message)
    return text


def clean_name(value: Any) -> str:
    return clean_text(value, NAME_MAX, NAME_INVALID, required=True)


def clean_type(value: Any) -> str:
    if value is None:
        return DEFAULT_TYPE
    if not isinstance(value, str) or value.strip() not in FAVORITE_TYPES:
        raise _invalid(TYPE_INVALID)
    return value.strip()


def clean_address(value: Any) -> str | None:
    return clean_text(value, ADDRESS_MAX, ADDRESS_INVALID, required=False)


def _number(value: Any, low: float, high: float) -> float:
    # bool은 int의 하위 클래스라 따로 막는다. 문자열 숫자도 받지 않는다.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(COORDINATES_INVALID)
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise _invalid(COORDINATES_INVALID)
    # DB 열이 DECIMAL(10,7)이다 (약 1cm). 미리 맞춰 두어 추가 응답과 나중 조회 값, 메모리·MySQL 저장소가 같게 한다.
    return round(number, COORDINATE_DECIMALS)


def clean_coordinates(lat: Any, lng: Any) -> Coordinates | None:
    """둘 다 없으면 None. 하나만 있거나 범위를 벗어나면 400."""
    if lat is None and lng is None:
        return None
    if lat is None or lng is None:
        raise _invalid(COORDINATES_INVALID)
    return Coordinates(_number(lat, -90, 90), _number(lng, -180, 180))


def validate_new(payload: dict[str, Any]) -> NewFavorite:
    """POST 본문. 이름 → 분류 → 주소 → 좌표 순서로 검사하고 첫 오류를 돌려준다."""
    return NewFavorite(
        name=clean_name(payload.get("name")),
        type=clean_type(payload.get("type")),
        address=clean_address(payload.get("address")),
        coordinates=clean_coordinates(payload.get("lat"), payload.get("lng")),
    )


def validate_changes(payload: dict[str, Any]) -> FavoriteChanges:
    """PATCH 본문. 보낸 필드만 바꾼다. 장소를 바꿀 때는 address·lat·lng를 모두 보낸다 (address는 null 가능)."""
    name = payload.get("name", _MISSING)
    type_ = payload.get("type", _MISSING)
    place_keys = [key for key in PLACE_FIELDS if key in payload]
    if place_keys and len(place_keys) != len(PLACE_FIELDS):
        raise _invalid(PLACE_FIELDS_TOGETHER)

    place = None
    if place_keys:
        coordinates = clean_coordinates(payload["lat"], payload["lng"])
        if coordinates is None:  # 장소를 바꾸면서 좌표를 비울 수는 없다 (DB에서 필수)
            raise _invalid(COORDINATES_INVALID)
        place = (clean_address(payload["address"]), coordinates)
    changes = FavoriteChanges(
        name=None if name is _MISSING else clean_name(name),
        type=None if type_ is _MISSING else clean_type_strict(type_),
        place=place,
    )
    if changes.name is None and changes.type is None and changes.place is None:
        raise _invalid(NOTHING_TO_UPDATE)
    return changes


def clean_type_strict(value: Any) -> str:
    """PATCH에서는 type을 보냈으면 반드시 4가지 중 하나여야 한다 (null로 기본값을 쓰지 않는다)."""
    if value is None:
        raise _invalid(TYPE_INVALID)
    return clean_type(value)


def parse_favorite_id(value: str | None) -> int | None:
    """?id= 값. 양의 정수가 아니거나 BIGINT를 넘으면 None (= 없는 것과 같은 404)."""
    if value is None or not value.isascii() or not value.isdigit():
        return None
    number = int(value)
    if number <= 0 or number > 2**63 - 1:
        return None
    return number


# NFKC·악센트 제거로도 풀리지 않지만 utf8mb4_0900_ai_ci가 같은 글자로 보는 것 (MySQL 8.0.46에서 확인):
# 합자(æ, œ)와 획이 그어진 글자(ø, đ, ł). casefold 뒤에 적용하므로 소문자만 둔다.
_LIGATURES = str.maketrans({"æ": "ae", "œ": "oe", "ø": "o", "đ": "d", "ł": "l"})


def name_key(name: str) -> str:
    """중복 판단용 이름 (메모리 저장소). MySQL utf8mb4_0900_ai_ci와 같은 결과를 내도록 맞춘다.

    - NFKC: 전각 문자(Ａ=A, ２=2), 원문자(①=1), 합자(ﬁ=fi)를 일반 글자로
    - casefold: 대소문자 (ß=ss 포함)
    - NFD 후 결합 부호 제거: 악센트 (é=e). 한글 자모는 결합 부호가 아니라 그대로 남는다
    MySQL 쪽은 UNIQUE(user_id, place_name)가 최종 판정이다. 여기서 놓친 경우도 DB가 409로 막는다.
    """
    folded = unicodedata.normalize("NFKC", name).casefold().translate(_LIGATURES)
    decomposed = unicodedata.normalize("NFD", folded)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", stripped)
