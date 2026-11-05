from fastapi import APIRouter

router = APIRouter(tags=["상태"])


@router.get("/health", summary="서버 상태 확인")
def health() -> dict[str, str]:
    """로드밸런서·배포 확인용. 외부 API는 부르지 않는다."""
    return {"status": "ok"}
