"""즐겨찾기 오류와 사용자에게 보여 줄 문구 (docs/api-spec.md "즐겨찾기").

FavoriteError의 message는 그대로 응답 본문 { "message": ... }이 된다. 내부 정보를 넣지 않는다.
"""

NAME_INVALID = "장소 이름은 1~100자로 입력해 주세요."
TYPE_INVALID = "분류는 집, 학교, 회사, 기타 중 하나여야 합니다."
ADDRESS_INVALID = "주소는 255자 이하로 입력해 주세요."
COORDINATES_INVALID = "위도와 경도는 함께, 올바른 범위의 숫자로 보내 주세요."
PLACE_FIELDS_TOGETHER = "장소를 바꿀 때는 address, lat, lng를 함께 보내 주세요."
NOTHING_TO_UPDATE = "바꿀 내용이 없습니다."
PLACE_NOT_FOUND = "장소 위치를 찾을 수 없습니다. 장소를 검색해서 선택해 주세요."
NAME_TAKEN = "이미 같은 이름의 즐겨찾기가 있습니다."
LIMIT_REACHED = "즐겨찾기는 최대 20개까지 저장할 수 있습니다."
NOT_FOUND = "찾을 수 없습니다."
STORE_UNAVAILABLE = "즐겨찾기를 지금 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."


class FavoriteError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class FavoriteNameTakenError(Exception):
    """같은 사용자에게 같은 별칭이 있다 (대소문자·악센트 무시). MySQL은 UNIQUE(user_id, place_name) 위반."""


class FavoriteLimitError(Exception):
    """사용자당 최대 개수에 닿았다."""


class FavoriteOwnerMissingError(Exception):
    """세션 확인 뒤 사용자가 지워졌다 (탈퇴와 추가가 겹친 경우). 로그인이 필요한 상태로 본다."""
