"""상태를 바꾸는 요청의 출처 검사 (CSRF 2차 방어. 1차는 세션 쿠키의 SameSite=Lax).

/api/* 의 POST·PUT·PATCH·DELETE에서 Origin(없으면 Referer)의 출처가 같은 호스트이거나 CORS_ORIGINS에 있어야 한다.
둘 다 없으면 통과시킨다. 브라우저는 다른 사이트에서 보내는 POST에 Origin을 항상 붙이므로, 헤더가 없는 요청은
curl 같은 브라우저 밖 클라이언트다 (이 경우 피해자의 쿠키가 실리지 않는다).
Content-Type 검사는 쓰지 않는다. 프론트의 로그아웃 요청은 본문과 Content-Type 없이 온다.

배포할 때 프록시가 https를 끝내고 http로 넘기면 같은 호스트 판단(scheme)이 어긋난다. 이때는 운영 출처를
CORS_ORIGINS에 넣는다.
"""

from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.auth.errors import ORIGIN_FORBIDDEN

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PROTECTED_PREFIX = "/api/"


def _origin_of(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def request_origin(request: Request) -> str | None:
    """요청을 보낸 페이지의 출처. Origin 헤더가 우선이고, 없으면 Referer에서 뽑는다. 둘 다 없으면 None.

    Origin이 "null"(샌드박스 iframe, file:// 등)이면 빈 문자열을 돌려줘 거부되게 한다.
    """
    origin = request.headers.get("origin")
    if origin is not None:
        return _origin_of(origin) or ""
    referer = request.headers.get("referer")
    if referer is not None:
        return _origin_of(referer) or ""
    return None


def own_origin(request: Request) -> str | None:
    host = request.headers.get("host")
    return f"{request.url.scheme}://{host}".lower() if host else None


def install_origin_check(app, allowed_origins: Iterable[str]) -> None:
    allowed = frozenset(origin.lower().rstrip("/") for origin in allowed_origins)

    @app.middleware("http")
    async def check_origin(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method in UNSAFE_METHODS and request.url.path.startswith(PROTECTED_PREFIX):
            origin = request_origin(request)
            if origin is not None and origin not in allowed and origin != own_origin(request):
                return JSONResponse(status_code=403, content={"message": ORIGIN_FORBIDDEN})
        return await call_next(request)
