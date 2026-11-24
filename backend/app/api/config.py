"""프론트 공개 설정 (GET /api/config).

브라우저에 어차피 노출되는 값만 내려 준다: 카카오 지도 JavaScript 키, GA4 측정 ID.
Settings를 통째로 직렬화하지 않는다. 응답 필드는 PublicConfigResponse에 적은 두 개뿐이고(화이트리스트),
새 값을 추가하려면 공개해도 되는 값인지 먼저 확인한다 (docs/api-spec.md "공개 설정").
값은 로그에 남기지 않는다.
"""

from fastapi import APIRouter, Request, Response

from app.api.schemas import PublicConfigResponse
from app.config import valid_ga4_measurement_id

router = APIRouter(prefix="/api", tags=["설정"])


@router.get("/config", summary="프론트 공개 설정", response_model=PublicConfigResponse)
def public_config(request: Request, response: Response) -> PublicConfigResponse:
    """로그인 불필요. 미설정 값은 빈 문자열. 키를 바꾸면 바로 반영되도록 캐시하지 않는다."""
    settings = request.app.state.settings
    response.headers["Cache-Control"] = "no-store"
    return PublicConfigResponse(
        kakaoJsKey=settings.kakao_js_key or "",
        ga4MeasurementId=valid_ga4_measurement_id(settings.ga4_measurement_id),
    )
