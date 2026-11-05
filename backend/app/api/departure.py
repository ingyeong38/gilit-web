from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.schemas import DepartureRequest, DepartureResponse, ErrorResponse
from app.config import Settings
from app.departure import KST, Coordinate, DepartureSolver

router = APIRouter(prefix="/api", tags=["출발시각"])


def get_solver(request: Request) -> DepartureSolver:
    """앱을 만들 때 하나 만들어 둔 Solver(와 Provider)를 모든 요청이 함께 쓴다 (factory.create_app)."""
    return request.app.state.solver


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post(
    "/departure",
    summary="권장 출발시각 계산",
    response_model=DepartureResponse,
    responses={
        400: {"model": ErrorResponse, "description": "입력 오류, 도착 희망 시각이 지남, 지원하지 않는 이동수단"},
        422: {"model": ErrorResponse, "description": "경로 없음, 제시간에 도착할 수 있는 출발시각 없음"},
        502: {"model": ErrorResponse, "description": "길찾기 API 오류"},
        503: {"model": ErrorResponse, "description": "길찾기 API 호출 한도 초과"},
        504: {"model": ErrorResponse, "description": "길찾기 API 응답 시간 초과"},
    },
)
def calculate_departure(
    body: DepartureRequest,
    solver: Annotated[DepartureSolver, Depends(get_solver)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DepartureResponse:
    """도착 희망 시각에서 여유시간을 뺀 시각까지 도착하는 가장 늦은 출발시각을 분 단위로 찾는다.

    로그인 없이 쓸 수 있다. 소요시간 조회는 요청 하나당 최대 DEPARTURE_MAX_CALLS(기본 8)회다.
    """
    # 동기 함수로 두어 FastAPI가 스레드 풀에서 실행한다 (Solver와 카카오 어댑터는 블로킹 I/O를 쓴다).
    result = solver.solve(
        Coordinate(body.origin.lat, body.origin.lng),
        Coordinate(body.destination.lat, body.destination.lng),
        body.arrive_at,
        body.buffer_min,
        body.travel_mode,
    )
    return DepartureResponse(
        recommended_depart_at=result.depart_at.astimezone(KST),
        duration_min=result.duration_min,
        expected_arrive_at=result.arrive_at.astimezone(KST),
        desired_arrive_at=result.target_arrive_at.astimezone(KST),
        buffer_min=result.buffer_min,
        buffer_applied=result.buffer_applied,
        converged=result.converged,
        api_calls=result.provider_calls,
        data_source=settings.route_provider,
    )
