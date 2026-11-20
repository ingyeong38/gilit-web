"""AI 경로 요약 (POST /api/routes/summary). 로그인 불필요. 저장소·검색 기록·캐시를 쓰지 않는다."""

from typing import Annotated

from fastapi import APIRouter, Body, Request, Response

from app.ai_summary import SummaryInput, SummaryRoute, summarize
from app.api.schemas import ErrorResponse, RouteSummaryRequest, RouteSummaryResponse
from app.departure import KST

router = APIRouter(prefix="/api", tags=["장소·경로"])


@router.post(
    "/routes/summary",
    summary="AI 경로 요약",
    response_model=RouteSummaryResponse,
    responses={400: {"model": ErrorResponse, "description": "입력 오류 (message, code)"}},
)
def post_route_summary(
    request: Request,
    response: Response,
    body: Annotated[RouteSummaryRequest, Body()],
) -> dict:
    """같은 검색의 `GET /api/routes` 카드 값으로 추천 경로와 짧은 요약을 돌려준다.

    Gemini는 추천 카드 id, headline, keywords만 만든다. 숫자(slackMin, comparison 등)와 label은 서버가 요청 값으로
    계산한다. Gemini를 쓸 수 없거나(설정 없음, 시간 초과, 오류, 형식 위반) 출력이 규칙에 맞지 않으면 `200` +
    `source: "rule"`이다. 장소 이름·좌표는 받지 않고, 요약과 입력은 어디에도 저장하지 않는다.
    """
    response.headers["Cache-Control"] = "no-store"
    data = SummaryInput(
        arrive=body.arrive.astimezone(KST),
        buffer_min=body.buffer,
        routes=tuple(
            SummaryRoute(
                id=route.id,
                depart_at=route.departTime.astimezone(KST),
                arrive_at=route.arriveTime.astimezone(KST),
                duration_min=route.durationMin,
                distance_km=route.distanceKm,
                toll=route.toll,
            )
            for route in body.routes
        ),
    )
    now = request.app.state.solver.clock()
    return summarize(data, now, request.app.state.summary_client)
