"""장소명 검색과 상세 자동차 경로. 실데이터 실패를 목업으로 대체하지 않는다."""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.departure import Coordinate, KST, ArrivalTimePassedError
from app.departure.errors import DepartureError, ProviderUnavailableError
from app.routing import find_routes

router = APIRouter(prefix="/api", tags=["장소·경로"])


def live_provider(request):
    if request.app.state.settings.route_provider != "kakao":
        raise ProviderUnavailableError("실제 경로 조회에는 서버의 카카오 모드가 필요합니다.")
    return request.app.state.provider


@router.get("/places")
def search_places(request: Request, q: Annotated[str, Query(min_length=1, max_length=255)]):
    return live_provider(request).search_places(q)


def resolve_place(provider, name):
    name = name.strip()
    places = provider.search_places(name)
    exact = [p for p in places if p["name"] == name or p["address"] == name]
    matches = exact or places
    if len(matches) != 1:
        raise DepartureError("장소를 하나로 확인할 수 없어요. 정확한 장소명이나 주소로 다시 검색해 주세요.")
    return Coordinate(matches[0]["lat"], matches[0]["lng"])


@router.get("/routes")
def get_routes(
    request: Request,
    from_: Annotated[str, Query(alias="from", min_length=1, max_length=255)],
    to: Annotated[str, Query(min_length=1, max_length=255)],
    arrive: datetime,
    buffer: int = 0,
    fromLat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    fromLng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    toLat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    toLng: Annotated[float | None, Query(ge=-180, le=180)] = None,
):
    if not from_.strip() or not to.strip() or buffer not in (0, 5, 10, 15):
        raise DepartureError("출발지·목적지와 여유시간을 확인해 주세요.")
    if from_.strip() == to.strip():
        raise DepartureError("출발지와 다른 목적지를 입력해 주세요.")
    provider = live_provider(request)
    solver = request.app.state.solver
    arrive = arrive if arrive.tzinfo else arrive.replace(tzinfo=KST)
    # 장소 검색을 시작하기 전에도 지난 시각을 검사한다.
    if arrive <= solver.clock():
        raise ArrivalTimePassedError("도착 희망 시각이 이미 지났습니다.")
    if (fromLat is None) != (fromLng is None) or (toLat is None) != (toLng is None):
        raise DepartureError("장소의 위도와 경도를 함께 전달해 주세요.")
    cache = request.app.state.route_cache
    cache_key = (from_.strip(), to.strip(), arrive.astimezone(KST), buffer, fromLat, fromLng, toLat, toLng)
    cached = cache.get(cache_key, solver.clock())
    if cached is not None:
        return JSONResponse(cached, headers={"X-Gilit-Route-Cache": "HIT", "Cache-Control": "no-store"})
    origin = Coordinate(fromLat, fromLng) if fromLat is not None else resolve_place(provider, from_)
    destination = Coordinate(toLat, toLng) if toLat is not None else resolve_place(provider, to)
    result = find_routes(provider, solver.config, solver.clock, origin, destination, arrive, buffer)
    cache.put(cache_key, result)
    return JSONResponse(result, headers={"X-Gilit-Route-Cache": "MISS", "Cache-Control": "no-store"})
