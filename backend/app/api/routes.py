"""장소명 검색과 경로 비교(F5). 실데이터 실패를 목업으로 대체하지 않는다."""
import logging
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.api.schemas import ErrorResponse, RouteCardResponse, RouteQuery
from app.departure import KST, ArrivalTimePassedError, Coordinate, RouteProvider
from app.departure.errors import DepartureError, ProviderUnavailableError
from app.routing import NO_FREE_ROUTE_MESSAGE, compare_routes

router = APIRouter(prefix="/api", tags=["장소·경로"])
logger = logging.getLogger("app.api")

PLACE_NOT_RESOLVED_MESSAGE = "장소를 하나로 확인할 수 없어요. 정확한 장소명이나 주소로 다시 검색해 주세요."


def live_provider(request):
    if request.app.state.settings.route_provider != "kakao":
        raise ProviderUnavailableError("실제 경로 조회에는 서버의 카카오 모드가 필요합니다.")
    return request.app.state.provider


@router.get("/places")
def search_places(request: Request, q: Annotated[str, Query(min_length=1, max_length=255)]):
    return live_provider(request).search_places(q)


def resolve_place(provider: RouteProvider, name: str) -> Coordinate:
    """좌표 없이 이름만 온 요청(좌표가 생기기 전 공유 링크)의 장소를 장소 검색으로 하나로 확정한다."""
    name = name.strip()
    try:
        places = provider.search_places(name)
    except NotImplementedError:
        # Mock 데이터에는 장소 검색이 없다. 프론트는 검색 결과의 좌표를 함께 보낸다.
        raise DepartureError(PLACE_NOT_RESOLVED_MESSAGE) from None
    exact = [p for p in places if p["name"] == name or p["address"] == name]
    matches = exact or places
    if len(matches) != 1:
        raise DepartureError(PLACE_NOT_RESOLVED_MESSAGE)
    return Coordinate(matches[0]["lat"], matches[0]["lng"])


@router.get(
    "/routes",
    summary="경로 비교",
    response_model=list[RouteCardResponse],
    responses={
        400: {"model": ErrorResponse, "description": "입력 오류, 도착 희망 시각이 지남"},
        422: {"model": ErrorResponse, "description": "장소를 확정할 수 없음, 모든 옵션에서 경로 없음·제시간 도착 불가"},
        502: {"model": ErrorResponse, "description": "길찾기 API 오류"},
        503: {"model": ErrorResponse, "description": "길찾기 API 호출 한도 초과"},
        504: {"model": ErrorResponse, "description": "길찾기 API 응답 시간 초과"},
    },
)
def get_routes(request: Request, response: Response, query: Annotated[RouteQuery, Query()]) -> list[dict]:
    """경로 옵션(ROUTE_COMPARE_OPTIONS: 추천·최단시간·최단거리·무료도로)마다 권장 출발시각을 계산해 카드로 돌려준다.

    같은 길로 확인된 옵션은 한 카드의 `options`에 합친다. 일부 옵션이 실패하면 그 카드만 빠지고(서버 로그에 남긴다),
    모두 실패하면 첫 옵션의 오류를 돌려준다. 로그인 없이 쓸 수 있다.
    """
    settings = request.app.state.settings
    provider = request.app.state.provider
    clock = request.app.state.solver.clock
    cache = request.app.state.route_cache
    response.headers["Cache-Control"] = "no-store"

    # 장소 검색을 시작하기 전에 지난 시각을 거른다.
    if query.arrive <= clock():
        raise ArrivalTimePassedError("도착 희망 시각이 이미 지났습니다.")
    cache_key = (query.from_, query.to, query.arrive.astimezone(KST), query.buffer,
                 query.fromLat, query.fromLng, query.toLat, query.toLng)
    cached = cache.get(cache_key, clock())
    if cached is not None:
        response.headers["X-Gilit-Route-Cache"] = "HIT"
        return cached

    origin = query.origin() or resolve_place(provider, query.from_)
    destination = query.destination() or resolve_place(provider, query.to)
    result = compare_routes(
        provider,
        settings.route_options(),
        settings.compare_solver_config(),
        origin,
        destination,
        query.arrive,
        query.buffer,
        clock=clock,
        data_source=settings.route_provider,
    )
    # 빠진 옵션은 응답에 넣지 않고 로그에만 남긴다. 통행료 없는 길이 없는 것은 흔한 일이라 INFO다.
    for key, reason in result.excluded.items():
        level = logging.INFO if reason == NO_FREE_ROUTE_MESSAGE else logging.WARNING
        logger.log(level, "경로 비교 옵션 제외: %s: %s", key, reason)
    logger.info("경로 비교: 카드 %d개, 길찾기 조회 %d회", len(result.cards), result.lookups)

    cards = [card.to_dict() for card in result.cards]
    cache.put(cache_key, cards)
    response.headers["X-Gilit-Route-Cache"] = "MISS"
    return cards
