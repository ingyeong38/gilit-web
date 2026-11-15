import logging
from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth as auth_api
from app.api import departure, health, routes
from app.api import oauth as oauth_api
from app.api.errors import install_error_handlers
from app.api.origin import install_origin_check
from app.auth import AuthService, create_auth_service
from app.auth.oauth import OAuthClient
from app.auth.oauth_state import UsedStates
from app.config import Settings, create_oauth_clients, create_route_provider, load_env_files

logger = logging.getLogger("app.api")
from app.departure import DepartureSolver, RouteProvider
from app.routing import RouteResultCache


def create_app(
    settings: Settings | None = None,
    provider: RouteProvider | None = None,
    clock: Callable[[], datetime] | None = None,
    auth: AuthService | None = None,
    oauth_clients: dict[str, OAuthClient] | None = None,
) -> FastAPI:
    """FastAPI 앱을 만든다. settings를 주지 않으면 .env와 환경변수에서 읽는다.

    RouteProvider, AuthService, 소셜 로그인 클라이언트는 여기서 한 번만 만든다. 카카오 어댑터의 캐시와 HTTP 세션,
    회원 저장소를 모든 요청이 함께 쓴다. 테스트는 settings, provider, clock, auth, oauth_clients를 직접 넣는다.
    """
    if settings is None:
        load_env_files()
        settings = Settings.from_env()
    if provider is None:
        provider = create_route_provider(settings)
    if auth is None:
        mysql = settings.mysql_config() if settings.auth_store == "mysql" else None
        auth = create_auth_service(settings.auth_store, clock=clock, mysql=mysql)
    if oauth_clients is None:
        oauth_clients = create_oauth_clients(settings)
    if oauth_clients and not settings.secret_key:
        raise ValueError("소셜 로그인에는 SECRET_KEY 환경변수가 필요합니다 (state 쿠키 서명).")
    if settings.oauth_mock:
        logger.warning("OAUTH_MOCK이 켜져 있습니다. 가짜 소셜 로그인입니다 (개발용, AUTH_STORE=memory).")

    app = FastAPI(
        title="길잇 API",
        version="0.1.0",
        description="도착 희망 시각으로 권장 출발시각을 알려 주는 길찾기 서비스 API. 명세: docs/api-spec.md",
    )
    app.state.route_cache = RouteResultCache(ttl=settings.route_cache_ttl_sec)
    app.state.settings = settings
    app.state.provider = provider
    app.state.solver = DepartureSolver(provider, settings.solver_config(), clock=clock)
    app.state.auth = auth
    app.state.oauth_clients = oauth_clients
    app.state.oauth_used_states = UsedStates()

    # 나중에 붙인 미들웨어가 바깥쪽이다. 출처 검사가 CORS보다 먼저 돈다 (preflight OPTIONS는 검사하지 않는다).
    # 로그인 세션 쿠키를 보내야 하므로 allow_credentials를 켜고, 출처는 CORS_ORIGINS로 정한 것만 허용한다.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    install_origin_check(app, settings.cors_origins)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth_api.router)
    app.include_router(oauth_api.router)
    app.include_router(departure.router)
    app.include_router(routes.router)
    return app
