"""오류를 docs/api-spec.md의 형식 { "message": "..." }으로 바꾼다.

- 입력 검증 실패: 400. 필드별 한국어 문장
- DepartureError(사용자 입력·조건 문제): 4xx. 엔진의 한국어 메시지를 그대로 쓴다
- RouteProviderError(길찾기 API 문제): 5xx. 원래 메시지는 서버 로그에만 남기고, 사용자에게는
  내부 정보(환경변수 이름, HTTP 코드, 카카오 응답 문구)가 없는 문장만 보낸다
- 그 밖의 예외: 500. 내용을 드러내지 않는다
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.departure import (
    ArrivalTimePassedError,
    DepartureError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    RouteProviderError,
    UnsupportedTravelModeError,
)

logger = logging.getLogger("app.api")

INTERNAL_ERROR_MESSAGE = "잠시 후 다시 시도해 주세요."
PROVIDER_ERROR_MESSAGE = "길찾기 정보를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요."

# 입력 자체가 잘못된 경우는 400, 입력은 올바르지만 답을 낼 수 없는 경우(경로 없음, 제시간 도착 불가 등)는 422
DEPARTURE_ERROR_STATUS: dict[type[DepartureError], int] = {
    ArrivalTimePassedError: 400,
    UnsupportedTravelModeError: 400,
}
DEPARTURE_ERROR_DEFAULT_STATUS = 422

# 이 둘은 원래 메시지에 내부 정보가 없어 그대로 보여 준다. 나머지 RouteProviderError는 502 + 일반 문장
PUBLIC_PROVIDER_ERROR_STATUS: dict[type[RouteProviderError], int] = {
    ProviderTimeoutError: 504,
    ProviderQuotaExceededError: 503,
}
PROVIDER_ERROR_DEFAULT_STATUS = 502

HTTP_ERROR_MESSAGES = {
    404: "찾을 수 없습니다.",
    405: "허용되지 않은 요청 방식입니다.",
}

# 입력 검증 오류 문장. loc의 마지막 필드 이름으로 고른다.
FIELD_LABELS = {  # (이름, 조사)
    "origin": ("출발지", "가"),
    "destination": ("목적지", "가"),
    "arrive_at": ("도착 희망 시각", "이"),
    "name": ("장소 이름", "이"),
    "lat": ("위도", "가"),
    "lng": ("경도", "가"),
    # GET /api/routes 쿼리
    "from": ("출발지", "가"),
    "to": ("목적지", "가"),
    "arrive": ("도착 희망 시각", "이"),
}
INVALID_MESSAGES = {
    "from": "출발지는 1~100자로 입력해 주세요.",
    "to": "목적지는 1~100자로 입력해 주세요.",
    "arrive": "도착 희망 시각은 ISO 8601 형식이어야 합니다 (예: 2026-11-06T09:00:00+09:00).",
    "buffer": "여유시간은 0, 5, 10, 15분 중 하나여야 합니다.",
    "fromLat": "출발지 위도는 -90~90 사이의 숫자여야 합니다.",
    "fromLng": "출발지 경도는 -180~180 사이의 숫자여야 합니다.",
    "toLat": "목적지 위도는 -90~90 사이의 숫자여야 합니다.",
    "toLng": "목적지 경도는 -180~180 사이의 숫자여야 합니다.",
    "origin": "출발지는 name, lat, lng가 있는 객체여야 합니다.",
    "destination": "목적지는 name, lat, lng가 있는 객체여야 합니다.",
    "name": "장소 이름은 1~100자로 입력해 주세요.",
    "lat": "위도는 -90~90 사이의 숫자여야 합니다.",
    "lng": "경도는 -180~180 사이의 숫자여야 합니다.",
    "arrive_at": "도착 희망 시각은 ISO 8601 형식이어야 합니다 (예: 2026-11-06T09:00:00+09:00).",
    "buffer_min": "여유시간은 0, 5, 10, 15분 중 하나여야 합니다.",
    "travel_mode": "이동수단은 car 또는 transit이어야 합니다.",
}
PLACE_PREFIX = {"origin": "출발지 ", "destination": "목적지 "}
INVALID_BODY_MESSAGE = "요청 본문은 JSON 객체여야 합니다."


def validation_message(errors: list[dict]) -> str:
    """pydantic 오류 목록의 첫 항목을 한국어 문장으로 바꾼다."""
    if not errors:
        return INVALID_BODY_MESSAGE
    error = errors[0]
    loc = [part for part in error.get("loc", ()) if isinstance(part, str) and part not in ("body", "query")]
    if not loc:
        # 여러 필드를 함께 보는 검사(model_validator)는 우리가 쓴 한국어 문장을 그대로 쓴다.
        cause = (error.get("ctx") or {}).get("error")
        if error.get("type") == "value_error" and cause is not None:
            return str(cause)
        return INVALID_BODY_MESSAGE
    field = loc[-1]
    prefix = PLACE_PREFIX.get(loc[0], "") if len(loc) > 1 else ""
    if error.get("type") == "missing" and field in FIELD_LABELS:
        label, particle = FIELD_LABELS[field]
        return f"{prefix}{label}{particle} 필요합니다."
    if field in INVALID_MESSAGES:
        return f"{prefix}{INVALID_MESSAGES[field]}"
    return f"{'.'.join(loc)} 값이 올바르지 않습니다."


def _status_for(error: Exception, table: dict, default: int) -> int:
    for error_type, status in table.items():
        if isinstance(error, error_type):
            return status
    return default


def _message(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"message": message})


async def handle_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    return _message(400, validation_message(list(error.errors())))


async def handle_departure_error(request: Request, error: DepartureError) -> JSONResponse:
    return _message(_status_for(error, DEPARTURE_ERROR_STATUS, DEPARTURE_ERROR_DEFAULT_STATUS), str(error))


async def handle_route_provider_error(request: Request, error: RouteProviderError) -> JSONResponse:
    # 어댑터가 만든 메시지에는 API 키가 없다 (providers_kakao.py). 원인 파악용으로 로그에만 남긴다.
    logger.warning("길찾기 데이터 조회 실패: %s: %s", type(error).__name__, error)
    for error_type, status in PUBLIC_PROVIDER_ERROR_STATUS.items():
        if isinstance(error, error_type):
            return _message(status, str(error))
    return _message(PROVIDER_ERROR_DEFAULT_STATUS, PROVIDER_ERROR_MESSAGE)


async def handle_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
    message = HTTP_ERROR_MESSAGES.get(error.status_code, INTERNAL_ERROR_MESSAGE)
    return JSONResponse(status_code=error.status_code, content={"message": message}, headers=error.headers)


async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    logger.exception("처리하지 못한 오류: %s %s", request.method, request.url.path)
    return _message(500, INTERNAL_ERROR_MESSAGE)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(DepartureError, handle_departure_error)
    app.add_exception_handler(RouteProviderError, handle_route_provider_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
