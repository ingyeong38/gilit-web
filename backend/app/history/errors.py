"""검색 기록 오류와 사용자에게 보여 줄 문구 (docs/api-spec.md "검색 기록")."""

LIMIT_INVALID = "개수는 1~50 사이의 정수여야 합니다."
NOT_FOUND = "찾을 수 없습니다."
STORE_UNAVAILABLE = "검색 기록을 지금 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."


class HistoryError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
