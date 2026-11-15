"""검색 기록 API (docs/api-spec.md "검색 기록"). 모두 로그인 필요 (require_user, 없으면 401).

저장은 이 API가 아니라 경로 검색이 성공했을 때 서버가 한다 (4단계에서 GET /api/routes에 연결). POST /api/history는 없다.
삭제는 행을 지우지 않고 사용자에게서 분리한다 (통계 보존). id가 숫자가 아니거나, 없거나, 남의 것·이미 지운 것이면 404다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.auth import require_user
from app.api.schemas import ErrorResponse, HistoryResponse
from app.auth import CurrentUser
from app.departure import KST
from app.history import HistoryEntry, HistoryError, HistoryService
from app.history.errors import STORE_UNAVAILABLE
from app.history.service import parse_history_id, parse_limit

router = APIRouter(prefix="/api/history", tags=["검색 기록"])

ERROR_400 = {"model": ErrorResponse, "description": "limit이 1~50 정수가 아님"}
ERROR_401 = {"model": ErrorResponse, "description": "로그인이 필요합니다."}
ERROR_404 = {"model": ErrorResponse, "description": "없는 id, 남의 기록, 이미 지운 기록, 숫자가 아닌 id"}


def get_history(request: Request) -> HistoryService:
    service = request.app.state.history
    if service is None:
        raise HistoryError(503, STORE_UNAVAILABLE)
    return service


def _iso(value) -> str | None:
    return value.astimezone(KST).isoformat() if value is not None else None


def history_response(entry: HistoryEntry) -> HistoryResponse:
    return HistoryResponse(
        id=str(entry.id),
        from_=entry.origin_name,
        to=entry.dest_name,
        arriveTime=_iso(entry.arrive_at),
        buffer=entry.buffer_min,
        departTime=_iso(entry.recommended_depart_at),
        fromLat=entry.origin_lat,
        fromLng=entry.origin_lng,
        toLat=entry.dest_lat,
        toLng=entry.dest_lng,
    )


@router.get(
    "",
    summary="내 검색 기록",
    response_model=list[HistoryResponse],
    response_model_by_alias=True,
    responses={400: ERROR_400, 401: ERROR_401},
)
def list_history(
    request: Request,
    current: Annotated[CurrentUser, Depends(require_user)],
    service: Annotated[HistoryService, Depends(get_history)],
) -> list[HistoryResponse]:
    """최신순. 같은 검색(출발지, 목적지, 도착 시각의 시:분)은 가장 최근 것 하나로 묶는다. `limit`은 묶은 뒤 개수 (기본 20, 최대 50)."""
    # 쿼리는 직접 읽는다. limit 오류를 공통 변환 문구가 아니라 정해 둔 문구로 알린다.
    limit = parse_limit(request.query_params.get("limit"))
    return [history_response(entry) for entry in service.list(current.id, limit)]


@router.delete("", status_code=204, summary="검색 기록 삭제 (한 건 또는 전체)", responses={401: ERROR_401, 404: ERROR_404})
def delete_history(
    request: Request,
    current: Annotated[CurrentUser, Depends(require_user)],
    service: Annotated[HistoryService, Depends(get_history)],
) -> Response:
    """`?id=`가 있으면 그 카드(같은 검색 묶음)를, 없으면 내 기록 전체를 지운다. 통계용 행은 남고 나에게서만 분리된다."""
    if "id" in request.query_params:
        service.delete_one(current.id, parse_history_id(request.query_params.get("id")))
    else:
        service.delete_all(current.id)
    return Response(status_code=204)
