"""장소명 검색, 경로 비교(F5), 소요시간 그래프(SFR-006). 실데이터 실패를 목업으로 대체하지 않는다."""
import logging
import time
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from fastapi.exceptions import RequestValidationError

from app.api.auth import optional_user
from app.api.schemas import (
    ErrorResponse,
    GraphQuery,
    RouteCardResponse,
    RouteGraphResponse,
    RouteQuery,
    card_option_message,
)
from app.departure import KST, ArrivalTimePassedError, Coordinate, RouteProvider
from app.departure.errors import DepartureError, ProviderUnavailableError
from app.history.recording import draft_from_route_search
from app.route_graph import GraphCard, collect_route_graphs
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
def get_routes(
    request: Request,
    response: Response,
    background: BackgroundTasks,
    query: Annotated[RouteQuery, Query()],
) -> list[dict]:
    """경로 옵션(ROUTE_COMPARE_OPTIONS: 추천·최단시간·최단거리·무료도로)마다 권장 출발시각을 계산해 카드로 돌려준다.

    같은 길로 확인된 옵션은 한 카드의 `options`에 합친다. 일부 옵션이 실패하면 그 카드만 빠지고(서버 로그에 남긴다),
    모두 실패하면 첫 옵션의 오류를 돌려준다. 로그인 없이 쓸 수 있다.

    성공(200)하면 응답을 보낸 뒤 검색 기록을 저장한다 (로그인 사용자는 내 기록, 비로그인은 통계용. docs/api-spec.md).
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
    cached, places = cache.get_with_meta(cache_key, clock())
    if cached is not None:
        response.headers["X-Gilit-Route-Cache"] = "HIT"
        # 캐시 적중도 사용자가 검색한 것이다. 좌표는 처음 계산할 때 확정한 값을 함께 기억해 두었다.
        origin, destination = places or (query.origin(), query.destination())
        background.add_task(record_search, request, query, origin, destination, cached)
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
    cache.put(cache_key, cards, meta=(origin, destination))
    response.headers["X-Gilit-Route-Cache"] = "MISS"
    background.add_task(record_search, request, query, origin, destination, cards)
    return cards


def invalid_query(message: str) -> RequestValidationError:
    """검증 오류 규약(errors.validation_message: 여러 필드를 보는 검사의 문장 그대로 400)으로 보낸다."""
    error = ValueError(message)
    return RequestValidationError([{"type": "value_error", "loc": ("query",), "msg": message, "input": None,
                                    "ctx": {"error": error}}])


@router.get(
    "/routes/graph",
    summary="출발시각별 소요시간 그래프",
    response_model=list[RouteGraphResponse],
    responses={
        400: {"model": ErrorResponse, "description": "입력 오류(card 포함), 도착 희망 시각이 지남"},
        422: {"model": ErrorResponse, "description": "장소를 확정할 수 없음, 모든 슬롯에서 경로 없음"},
        502: {"model": ErrorResponse, "description": "모든 슬롯이 길찾기 API 오류"},
        503: {"model": ErrorResponse, "description": "길찾기 API 호출 한도 초과 또는 그래프 일일 예산 소진"},
        504: {"model": ErrorResponse, "description": "모든 슬롯이 응답 시간 초과 또는 서버 시간 예산 초과"},
    },
)
def get_route_graph(request: Request, response: Response, query: Annotated[GraphQuery, Query()]) -> list[dict]:
    """card(경로 id@권장 출발시각)마다 출발시각 앞뒤 슬롯(기본 15분 간격 -45~+45분)의 소요시간을 돌려준다.

    카카오 약관상 응답을 캐시하지 않는다. 같은 요청도 매번 조회한다. 지난 슬롯은 빼고, 요청당 슬롯은 13개까지다.
    일부 슬롯·카드가 실패하면 그 점·항목만 빼고 200. 로그인 없이 쓸 수 있고 검색 기록은 남기지 않는다.
    """
    started = time.monotonic()
    settings = request.app.state.settings
    provider = request.app.state.provider
    budget = request.app.state.graph_budget
    now = request.app.state.solver.clock()
    response.headers["Cache-Control"] = "no-store"

    if query.arrive <= now:
        raise ArrivalTimePassedError("도착 희망 시각이 이미 지났습니다.")
    options = {option.key: option for option in settings.route_options()}
    cards = []
    for card in query.cards():
        if card.id not in options:  # ROUTE_COMPARE_OPTIONS로 끈 옵션은 /api/routes 카드에도 없다
            raise invalid_query(card_option_message(options))
        cards.append(GraphCard(card.id, options[card.id], card.depart_at))

    # 예산을 다 썼으면 장소 검색을 포함해 카카오를 전혀 부르지 않는다.
    budget.ensure_available(now)
    origin = query.origin() or resolve_place(provider, query.from_)
    destination = query.destination() or resolve_place(provider, query.to)
    return collect_route_graphs(
        provider,
        origin,
        destination,
        cards,
        settings.graph_config(),
        now=now,
        arrive=query.arrive,
        budget=budget,
        deadline=started + settings.graph_time_budget_sec,
        executor=request.app.state.graph_executor,
    )


def record_search(request: Request, query: RouteQuery, origin, destination, cards: list[dict]) -> None:
    """응답을 보낸 뒤(백그라운드) 로그인 사용자의 검색 기록을 저장한다. 세션 확인·저장이 실패해도 로그만 남긴다.

    세션 확인(optional_user)도 여기서 한다. 경로 응답이 회원 DB를 기다리거나 DB 장애로 실패하지 않게 하려는 것이다.
    비로그인 검색은 저장하지 않는다 (기록은 항상 그 사용자의 user_id로만 저장·조회한다).
    """
    history = request.app.state.history
    if history is None:
        return
    try:
        current = optional_user(request, request.app.state.auth)
        if current is None:
            return
        draft = draft_from_route_search(query.from_, query.to, query.arrive, query.buffer, origin, destination, cards)
        history.record_search(current.id, draft)
    except Exception:
        # 장소 이름·좌표는 로그에 남기지 않는다 (개인 검색 내용).
        logger.exception("검색 기록 저장 실패 (경로 응답에는 영향 없음)")
