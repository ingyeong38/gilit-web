"""내 이용 통계 API (docs/api-spec.md "내 이용 통계"). 로그인 필요 (require_user, 없으면 401).

사이트 전체 통계(GET /api/stats, 방문자·인기 장소, 통계 화면 stats.js)와는 응답이 다른 별도 경로다.
집계는 검색 기록 표(search_history)로만 한다 (app/history/stats.py). 새 표나 따로 보관하는 값은 없다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.auth import require_user
from app.api.history import ERROR_401, get_history
from app.api.schemas import DailySearchCount, ErrorResponse, MyStatsResponse
from app.auth import CurrentUser
from app.history import HistoryService
from app.history.service import parse_range

router = APIRouter(prefix="/api/stats", tags=["이용 통계"])

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
