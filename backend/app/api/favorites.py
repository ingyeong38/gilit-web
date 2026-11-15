"""즐겨찾기 API (docs/api-spec.md "즐겨찾기"). 모두 로그인 필요 (require_user, 없으면 401).

프론트(frontend/js/api.js)가 쓰는 ?id= 방식을 그대로 쓴다. id가 숫자가 아니거나, 없거나, 남의 것이면 모두 404다.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request, Response

from app.api.auth import require_user
from app.api.schemas import ErrorResponse, FavoriteResponse
from app.auth import CurrentUser
from app.favorites import Favorite, FavoriteError, FavoriteService
from app.favorites.errors import STORE_UNAVAILABLE
from app.favorites.validation import parse_favorite_id

logger = logging.getLogger("app.api.favorites")

router = APIRouter(prefix="/api/favorites", tags=["즐겨찾기"])

ADD_EXAMPLE = {"name": "집", "address": "경상남도 김해시 내외중앙로 47", "type": "집", "lat": 35.2285, "lng": 128.8894}
PATCH_EXAMPLE = {"name": "우리 집", "type": "집"}
ERROR_400 = {"model": ErrorResponse, "description": "입력 검증 실패, 장소 위치를 찾을 수 없음"}
ERROR_401 = {"model": ErrorResponse, "description": "로그인이 필요합니다."}
ERROR_404 = {"model": ErrorResponse, "description": "없는 id, 남의 즐겨찾기, 숫자가 아닌 id"}
ERROR_409 = {"model": ErrorResponse, "description": "같은 이름이 있음, 20개 초과"}


def get_favorites(request: Request) -> FavoriteService:
    service = request.app.state.favorites
    if service is None:
        # AUTH_STORE=mysql인데 MySQL 즐겨찾기 저장소가 아직 없는 경우 (2단계 전). 인증은 그대로 동작한다.
        raise FavoriteError(503, STORE_UNAVAILABLE)
    return service


def favorite_response(favorite: Favorite) -> FavoriteResponse:
    return FavoriteResponse(
        id=str(favorite.id),
        name=favorite.name,
        address=favorite.address,
        type=favorite.type,
        lat=favorite.lat,
        lng=favorite.lng,
    )


def query_id(request: Request) -> int | None:
    # 쿼리는 직접 읽는다. 잘못된 id를 FastAPI 검증 오류(400)가 아니라 "없음"(404)으로 다룬다.
    return parse_favorite_id(request.query_params.get("id"))


@router.get("", summary="즐겨찾기 목록", response_model=list[FavoriteResponse], responses={401: ERROR_401})
def list_favorites(
    current: Annotated[CurrentUser, Depends(require_user)],
    service: Annotated[FavoriteService, Depends(get_favorites)],
) -> list[FavoriteResponse]:
    """추가한 순서대로 (오래된 것이 먼저). 사용자당 최대 20개."""
    return [favorite_response(f) for f in service.list(current.id)]


@router.post(
    "",
    status_code=201,
    summary="즐겨찾기 추가",
    response_model=FavoriteResponse,
    responses={400: ERROR_400, 401: ERROR_401, 409: ERROR_409},
)
def add_favorite(
    current: Annotated[CurrentUser, Depends(require_user)],
    service: Annotated[FavoriteService, Depends(get_favorites)],
    payload: Annotated[dict[str, Any], Body(openapi_examples={"기본": {"value": ADD_EXAMPLE}})],
) -> FavoriteResponse:
    """`lat`·`lng`를 보내면 그대로 쓴다. 없으면 `address`(없으면 `name`)로 장소를 찾고, 결과가 정확히 하나일 때만 쓴다."""
    return favorite_response(service.add(current.id, payload))


@router.patch(
    "",
    summary="즐겨찾기 수정",
    response_model=FavoriteResponse,
    responses={400: ERROR_400, 401: ERROR_401, 404: ERROR_404, 409: ERROR_409},
)
def update_favorite(
    request: Request,
    current: Annotated[CurrentUser, Depends(require_user)],
    service: Annotated[FavoriteService, Depends(get_favorites)],
    payload: Annotated[dict[str, Any], Body(openapi_examples={"이름·분류": {"value": PATCH_EXAMPLE}})],
) -> FavoriteResponse:
    """보낸 필드만 바꾼다 (`name`, `type`). 장소를 바꿀 때는 `address`, `lat`, `lng`를 함께 보낸다."""
    return favorite_response(service.update(current.id, query_id(request), payload))


@router.delete("", status_code=204, summary="즐겨찾기 삭제", responses={401: ERROR_401, 404: ERROR_404})
def delete_favorite(
    request: Request,
    current: Annotated[CurrentUser, Depends(require_user)],
    service: Annotated[FavoriteService, Depends(get_favorites)],
) -> Response:
    service.delete(current.id, query_id(request))
    return Response(status_code=204)
