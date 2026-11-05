from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import departure, health
from app.api.errors import install_error_handlers
from app.config import Settings, create_route_provider, load_env_files
from app.departure import DepartureSolver, RouteProvider


def create_app(
    settings: Settings | None = None,
    provider: RouteProvider | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """FastAPI 앱을 만든다. settings를 주지 않으면 .env와 환경변수에서 읽는다.

    RouteProvider는 여기서 한 번만 만든다. 카카오 어댑터의 캐시와 HTTP 세션을 모든 요청이 함께 쓴다.
    테스트는 settings, provider, clock을 직접 넣는다.
    """
    if settings is None:
        load_env_files()
        settings = Settings.from_env()
    if provider is None:
        provider = create_route_provider(settings)

    app = FastAPI(
        title="길잇 API",
        version="0.1.0",
        description="도착 희망 시각으로 권장 출발시각을 알려 주는 길찾기 서비스 API. 명세: docs/api-spec.md",
    )
    app.state.settings = settings
    app.state.provider = provider
    app.state.solver = DepartureSolver(provider, settings.solver_config(), clock=clock)

    # 로그인 세션 쿠키를 보내야 하므로 allow_credentials를 켜고, 출처는 CORS_ORIGINS로 정한 것만 허용한다.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(departure.router)
    return app
