"""사이트 전체 이용 통계와 로그인 사용자 개인 통계 API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.auth import require_user
from app.api.history import ERROR_401, get_history
from app.api.schemas import DailySearchCount, ErrorResponse, MyStatsResponse
from app.auth import CurrentUser
from app.history import HistoryService
from app.history.service import parse_range
from app.site_stats import site_stats

router = APIRouter(prefix="/api/stats", tags=["이용 통계"])


@router.get("", summary="사이트 전체 이용 통계", responses={401: ERROR_401})
def overall_stats(
    request: Request,
    response: Response,
    current: Annotated[CurrentUser, Depends(require_user)],
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    state = request.app.state
    store = state.history.store if state.history else None
    return site_stats(state.ga4_reports, store, state.stats_clock())


ERROR_400 = {"model": ErrorResponse, "description": "range가 week가 아님"}


@router.get(
    "/me",
    summary="내 이용 통계 (최근 7일)",
    response_model=MyStatsResponse,
    response_model_by_alias=True,
    responses={400: ERROR_400, 401: ERROR_401},
)
def my_stats(
    request: Request,
    current: Annotated[CurrentUser, Depends(require_user)],
    service: Annotated[HistoryService, Depends(get_history)],
) -> MyStatsResponse:
    """오늘을 포함한 최근 7일(KST)의 날짜별 검색 횟수, 합계, 가장 많이 간 곳. `range`는 week만 (없으면 week)."""
    # 쿼리는 직접 읽는다. 잘못된 range를 공통 변환 문구가 아니라 정해 둔 문구로 알린다 (history의 limit과 같다).
    range_ = parse_range(request.query_params.get("range"))
    stats = service.weekly_stats(current.id)
    return MyStatsResponse(
        range=range_,
        from_=stats.start_date.isoformat(),
        to=stats.end_date.isoformat(),
        daily=[DailySearchCount(date=item.date.isoformat(), count=item.count) for item in stats.daily],
        total=stats.total,
        topPlace=stats.top_place,
    )
