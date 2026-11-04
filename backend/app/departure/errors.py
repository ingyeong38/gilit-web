class DepartureError(Exception):
    """출발시각을 정할 수 없는 경우. 메시지는 사용자에게 그대로 보여 줄 수 있는 문장이다 (API 4xx message)."""


class ArrivalTimePassedError(DepartureError):
    """도착 희망 시각이 이미 지났다."""


class NoFeasibleDepartureError(DepartureError):
    """탐색 구간 안의 어떤 출발시각으로도 제시간에 도착할 수 없다."""


class SearchBudgetExceededError(DepartureError):
    """호출 한도 안에서 제시간에 도착하는 출발시각을 하나도 확인하지 못했다."""


class RouteProviderError(Exception):
    """길찾기 데이터 조회 실패. 사용자 입력 문제가 아니므로 DepartureError와 구분한다 (API 5xx)."""


# 길찾기 API 어댑터(KakaoRouteProvider 등)의 오류.
# 메시지에 API 키나 API 응답 원문을 넣지 않는다. 카카오는 인증 오류 응답 본문에 키를 그대로 돌려준다.


class RouteNotFoundError(DepartureError):
    """출발지와 목적지 사이 경로가 없다 (카카오 result_code != 0). 입력 좌표 문제이므로 4xx로 다룬다."""

    def __init__(self, message: str, result_code: int | None = None) -> None:
        super().__init__(message)
        self.result_code = result_code


class UnsupportedTravelModeError(DepartureError):
    """길찾기 데이터 출처가 지원하지 않는 이동수단이다."""


class ProviderAuthError(RouteProviderError):
    """API 키가 없거나 잘못되었다 (HTTP 401/403)."""


class ProviderQuotaExceededError(RouteProviderError):
    """API 호출 한도를 넘었다 (HTTP 429)."""


class ProviderTimeoutError(RouteProviderError):
    """API가 제한 시간 안에 응답하지 않았다."""


class ProviderUnavailableError(RouteProviderError):
    """API 서버 오류(HTTP 5xx)나 네트워크 오류."""


class ProviderBadRequestError(RouteProviderError):
    """API가 요청을 거부했다 (HTTP 400 등). 어댑터가 만든 요청 문제이거나 좌표가 서비스 범위 밖인 경우다."""
