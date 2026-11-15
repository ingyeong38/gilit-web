"""소셜 로그인 웹 흐름 (docs/api-spec.md "회원", 설계 3-5).

GET /api/auth/{provider}/start     state·PKCE를 서명 쿠키 gilit_oauth에 담고 제공자 인증 화면으로 302
GET /api/auth/{provider}/callback  검사 → 코드 교환 → 계정 처리 → 세션 → /pages/search.html?auth_result=...로 302

콜백은 브라우저가 이동해 오는 주소라 JSON 오류를 보여 주지 않는다. 어떤 실패든 auth_result로 알린다.
  success | cancelled (사용자가 취소) | email_exists (검증된 이메일이 기존 계정과 겹침) | failed (그 밖의 모든 실패)
실패 사유는 서버 로그에만 남기고, 인가 코드·state·토큰·쿠키 값은 로그에도 남기지 않는다.
gilit_oauth 쿠키는 결과와 상관없이 콜백에서 지운다.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.auth import cookie_secure, get_auth, session_token, set_session_cookie
from app.auth import AuthService
from app.auth.errors import SocialEmailConflictError
from app.auth.oauth import OAuthClient, OAuthError, code_challenge_s256, new_code_verifier
from app.auth.oauth_state import (
    STATE_TTL,
    OAuthState,
    OAuthStateError,
    decode_state_cookie,
    encode_state_cookie,
    new_state,
)
from app.auth.service import LoginResult
from app.auth.stores import SOCIAL_PROVIDERS

logger = logging.getLogger("app.api.oauth")

OAUTH_COOKIE = "gilit_oauth"
OAUTH_COOKIE_PATH = "/api/auth"
AUTH_RESULT_PATH = "/pages/search.html"  # 프론트가 auth_result를 읽고 원래 화면으로 돌려보낸다 (frontend/js/auth.js)

router = APIRouter(prefix="/api/auth", tags=["회원"])


class RedactOAuthCallbackQuery(logging.Filter):
    """uvicorn 접근 로그에서 콜백 쿼리(code, state)를 가린다.

    uvicorn.access 레코드의 args는 (클라이언트, 메서드, 쿼리 포함 경로, HTTP 버전, 상태 코드)다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if path.startswith("/api/auth/") and "/callback?" in path:
                # ASCII로 쓴다. Windows 콘솔(cp949)에서도 깨지지 않는다.
                record.args = (*args[:2], path.split("?", 1)[0] + "?[REDACTED]", *args[3:])
        return True


def install_access_log_redaction() -> None:
    """웹 서버 진입점(app/main.py)에서 부른다. 여러 번 불러도 필터는 하나만 붙는다."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactOAuthCallbackQuery) for f in access.filters):
        access.addFilter(RedactOAuthCallbackQuery())


def result_redirect(outcome: str) -> RedirectResponse:
    response = RedirectResponse(f"{AUTH_RESULT_PATH}?auth_result={outcome}", status_code=302)
    response.headers["Cache-Control"] = "no-store"
    return response


def callback_uri(request: Request, provider: str) -> str:
    """제공자에 보내는 redirect_uri. OAUTH_REDIRECT_BASE가 없으면(Mock·테스트) 같은 서버의 상대 경로."""
    base = request.app.state.settings.oauth_redirect_base or ""
    return f"{base}/api/auth/{provider}/callback"


def _client(request: Request, provider: str) -> OAuthClient | None:
    if provider not in SOCIAL_PROVIDERS:
        raise StarletteHTTPException(404)
    client = request.app.state.oauth_clients.get(provider)
    if client is None:
        logger.warning("소셜 로그인 실패 (%s): 서버에 설정되지 않은 제공자", provider)
    return client


@router.get("/{provider}/start", summary="소셜 로그인 시작", status_code=302, response_class=RedirectResponse)
def start(provider: str, request: Request, auth: Annotated[AuthService, Depends(get_auth)]) -> RedirectResponse:
    """제공자 인증 화면으로 보낸다. 설정되지 않은 제공자는 auth_result=failed로 돌려보낸다."""
    client = _client(request, provider)
    if client is None:
        return result_redirect("failed")
    state, verifier = new_state(), new_code_verifier()
    expires_at = int(auth.now().timestamp() + STATE_TTL.total_seconds())
    cookie = encode_state_cookie(request.app.state.settings.secret_key, OAuthState(provider, state, verifier, expires_at))
    response = RedirectResponse(
        client.authorization_url(state, code_challenge_s256(verifier), callback_uri(request, provider)), status_code=302
    )
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        OAUTH_COOKIE,
        cookie,
        max_age=int(STATE_TTL.total_seconds()),
        path=OAUTH_COOKIE_PATH,
        secure=cookie_secure(request),
        httponly=True,
        samesite="lax",  # 제공자에서 돌아오는 최상위 GET 이동에는 실린다
    )
    return response


@router.get("/{provider}/callback", summary="소셜 로그인 콜백", status_code=302, response_class=RedirectResponse)
def callback(provider: str, request: Request, auth: Annotated[AuthService, Depends(get_auth)]) -> RedirectResponse:
    client = _client(request, provider)
    outcome, login = ("failed", None) if client is None else _complete(request, auth, client, provider)
    response = result_redirect(outcome)
    response.delete_cookie(OAUTH_COOKIE, path=OAUTH_COOKIE_PATH, secure=cookie_secure(request), httponly=True, samesite="lax")
    if login is not None:
        set_session_cookie(request, response, login.token)
    return response


def _complete(request: Request, auth: AuthService, client: OAuthClient, provider: str) -> tuple[str, LoginResult | None]:
    # 쿼리는 직접 읽는다. FastAPI 검증 오류(400 JSON)가 브라우저 화면에 나오지 않게 한다.
    params = request.query_params
    error = params.get("error")
    if error:
        if error == "access_denied":
            logger.info("소셜 로그인 취소 (%s)", provider)
            return "cancelled", None
        logger.warning("소셜 로그인 실패 (%s): 제공자 오류 응답", provider)
        return "failed", None

    now_epoch = auth.now().timestamp()
    try:
        value = decode_state_cookie(
            request.app.state.settings.secret_key, request.cookies.get(OAUTH_COOKIE), provider, params.get("state"), now_epoch
        )
    except OAuthStateError as reason:
        logger.warning("소셜 로그인 실패 (%s): %s", provider, reason)
        return "failed", None
    if not request.app.state.oauth_used_states.consume(value, now_epoch):
        logger.warning("소셜 로그인 실패 (%s): 이미 사용한 state", provider)
        return "failed", None
    code = params.get("code")
    if not code:
        logger.warning("소셜 로그인 실패 (%s): 인가 코드 없음", provider)
        return "failed", None

    try:
        profile = client.fetch_profile(code, value.verifier, callback_uri(request, provider))
    except OAuthError as reason:
        logger.warning("소셜 로그인 실패 (%s): %s", provider, reason)
        return "failed", None
    if profile.provider != provider:
        logger.warning("소셜 로그인 실패 (%s): 프로필의 제공자 불일치", provider)
        return "failed", None

    try:
        login = auth.social_login(profile, previous_token=session_token(request))
    except SocialEmailConflictError:
        logger.info("소셜 로그인 이메일 충돌 (%s): 계정을 만들지 않음", provider)
        return "email_exists", None
    except Exception:
        logger.exception("소셜 로그인 처리 중 오류 (%s)", provider)
        return "failed", None
    return "success", login
