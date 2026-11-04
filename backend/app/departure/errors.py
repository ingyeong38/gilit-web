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
