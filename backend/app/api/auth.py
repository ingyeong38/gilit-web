"""회원 API (docs/api-spec.md "회원")와 로그인 의존성.

다른 라우터에서 로그인 사용자가 필요하면 의존성을 쓴다:

    def list_favorites(current: Annotated[CurrentUser, Depends(require_user)]): ...   # 없으면 401
    def save_history(current: Annotated[CurrentUser | None, Depends(optional_user)]): ...  # 없으면 None
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request, Response

from app.api.schemas import ErrorResponse, UserResponse
from app.auth import AuthService, CurrentUser, User
from app.auth.errors import LOGIN_REQUIRED, AuthError
from app.auth.service import SESSION_TTL

SESSION_COOKIE = "gilit_session"

router = APIRouter(prefix="/api/auth", tags=["회원"])

SIGNUP_EXAMPLE = {"name": "길잇", "email": "user@example.com", "password": "gilit1234", "agreeTerms": True, "agreePrivacy": True}
LOGIN_EXAMPLE = {"email": "user@example.com", "password": "gilit1234"}
ERROR_400 = {"model": ErrorResponse, "description": "입력 검증 실패"}
ERROR_403 = {"model": ErrorResponse, "description": "허용되지 않은 출처 (Origin 검사)"}
ERROR_429 = {"model": ErrorResponse, "description": "요청 횟수 제한 초과 (Retry-After 헤더)"}


def get_auth(request: Request) -> AuthService:
    return request.app.state.auth


def session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE) or None


def optional_user(request: Request, auth: Annotated[AuthService, Depends(get_auth)]) -> CurrentUser | None:
    return auth.authenticate(session_token(request))


def require_user(current: Annotated[CurrentUser | None, Depends(optional_user)]) -> CurrentUser:
    if current is None:
        raise AuthError(401, LOGIN_REQUIRED)
    return current


def client_ip(request: Request) -> str:
    # 배포 때 프록시 뒤에 두면 X-Forwarded-For를 신뢰할 프록시에서만 읽도록 바꾼다 (uvicorn --proxy-headers).
    return request.client.host if request.client else "unknown"


def user_response(user: User, provider: str) -> UserResponse:
    return UserResponse(id=str(user.id), name=user.nickname, email=user.email, provider=provider)


def cookie_secure(request: Request) -> bool:
    return request.app.state.settings.cookie_secure


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
        secure=cookie_secure(request),
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=cookie_secure(request), httponly=True, samesite="lax")


@router.post(
    "/signup",
    status_code=201,
    summary="이메일 회원가입",
    response_model=UserResponse,
    responses={400: ERROR_400, 403: ERROR_403, 409: {"model": ErrorResponse, "description": "이미 가입된 이메일"}, 429: ERROR_429},
)
def signup(
    request: Request,
    auth: Annotated[AuthService, Depends(get_auth)],
    payload: Annotated[dict[str, Any], Body(openapi_examples={"기본": {"value": SIGNUP_EXAMPLE}})],
) -> UserResponse:
    """가입만 하고 로그인 세션은 만들지 않는다. 프론트는 로그인 화면으로 돌아가 이메일을 채워 둔다."""
    user = auth.signup(payload, client_ip(request))
    return user_response(user, "email")


@router.post(
    "/login",
    summary="이메일 로그인",
    response_model=UserResponse,
    responses={
        400: ERROR_400,
        401: {"model": ErrorResponse, "description": "이메일 또는 비밀번호가 올바르지 않음 (계정 없음·소셜 전용 포함)"},
        403: ERROR_403,
        429: ERROR_429,
    },
)
def login(
    request: Request,
    response: Response,
    auth: Annotated[AuthService, Depends(get_auth)],
    payload: Annotated[dict[str, Any], Body(openapi_examples={"기본": {"value": LOGIN_EXAMPLE}})],
) -> UserResponse:
    """성공하면 gilit_session 쿠키(HttpOnly, SameSite=Lax, 14일)를 내려준다. 이전 세션은 지운다."""
    result = auth.login(payload, client_ip(request), previous_token=session_token(request))
    set_session_cookie(request, response, result.token)
    return user_response(result.current.user, result.current.login_provider)


@router.post("/logout", status_code=204, summary="로그아웃", responses={403: ERROR_403})
def logout(request: Request, auth: Annotated[AuthService, Depends(get_auth)]) -> Response:
    """세션을 지우고 쿠키를 만료시킨다. 세션이 없어도 204."""
    auth.logout(session_token(request))
    response = Response(status_code=204)
    clear_session_cookie(request, response)
    return response


@router.get(
    "/me",
    summary="내 정보",
    response_model=UserResponse,
    responses={401: {"model": ErrorResponse, "description": "로그인이 필요합니다."}},
)
def me(current: Annotated[CurrentUser, Depends(require_user)]) -> UserResponse:
    """서버 세션 기준의 로그인 상태. 비로그인은 항상 401이다 (프론트는 401만 비로그인으로 본다)."""
    return user_response(current.user, current.login_provider)
