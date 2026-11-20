import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth as auth_api
from app.api import departure, health, routes
from app.api import favorites as favorites_api
from app.api import history as history_api
from app.api import oauth as oauth_api
from app.api import stats as stats_api
from app.api.errors import install_error_handlers
from app.api.origin import install_origin_check
from app.api.routes import resolve_place
from app.auth import AuthService, create_auth_service
from app.auth.oauth import OAuthClient
from app.auth.oauth_state import UsedStates
from app.ai_summary import GeminiClient
from app.api import summary as summary_api
from app.config import Settings, create_oauth_clients, create_route_provider, create_summary_client, load_env_files
from app.departure import DepartureError, DepartureSolver, RouteProvider
from app.favorites import Coordinates, FavoriteService, create_favorite_store
from app.history import HistoryService, create_history_store
from app.route_graph import DailyCallBudget

logger = logging.getLogger("app.api")


def place_locator(provider: RouteProvider) -> Callable[[str], Coordinates | None]:
    """즐겨찾기 좌표 찾기. 장소 검색 결과가 정확히 하나일 때만 좌표를 준다 (경로 API의 resolve_place와 같은 규칙).

    못 찾음·여러 개·mock 모드(장소 검색 없음)는 None. 길찾기 API 장애(RouteProviderError)는 그대로 올린다.
    """

    def locate(query: str) -> Coordinates | None:
        try:
            found = resolve_place(provider, query)
        except DepartureError:
            return None
        return Coordinates(found.lat, found.lng)

    return locate


def create_app(
    settings: Settings | None = None,
    provider: RouteProvider | None = None,
    clock: Callable[[], datetime] | None = None,
    auth: AuthService | None = None,
    oauth_clients: dict[str, OAuthClient] | None = None,
    favorites: FavoriteService | None = None,
    history: HistoryService | None = None,
    summary_client: GeminiClient | None = None,
) -> FastAPI:
    """FastAPI 앱을 만든다. settings를 주지 않으면 .env와 환경변수에서 읽는다.

    RouteProvider, DB 연결 풀, 저장소(회원·즐겨찾기), 소셜 로그인 클라이언트는 여기서 한 번만 만든다.
    AUTH_STORE=mysql이면 연결 풀 하나를 모든 저장소가 함께 쓴다 (app.state.db_pool). 풀은 처음 쓸 때 연결한다.
    테스트는 settings, provider, clock, auth, oauth_clients, favorites를 직접 넣는다.
    """
    if settings is None:
        load_env_files()
        settings = Settings.from_env()
    if provider is None:
        provider = create_route_provider(settings)

    pool = None
    if settings.auth_store == "mysql" and (auth is None or favorites is None or history is None):
        from app.db import ConnectionPool  # pymysql은 mysql을 쓸 때만 불러온다

        pool = ConnectionPool(settings.mysql_config())
    if auth is None:
        auth = create_auth_service(settings.auth_store, clock=clock, pool=pool)
    if favorites is None:
        store = create_favorite_store(settings.auth_store, pool)
        if store is None:
            logger.warning("AUTH_STORE=%s용 즐겨찾기 저장소가 아직 없습니다. 즐겨찾기 API는 503을 돌려줍니다.", settings.auth_store)
        else:
            favorites = FavoriteService(store, locate=place_locator(provider), clock=clock)
    if history is None:
        history_store = create_history_store(settings.auth_store, pool)
        if history_store is None:
            logger.warning("AUTH_STORE=%s용 검색 기록 저장소가 없습니다. 검색 기록 API는 503을 돌려줍니다.", settings.auth_store)
        else:
            history = HistoryService(history_store, clock=clock)

    if summary_client is None:
        # 키·모델이 없으면 None. 앱은 시작하고 요약 API는 rule 요약을 돌려준다.
        summary_client = create_summary_client(settings)
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
    # 길찾기 응답은 캐시하지 않는다 (카카오 약관). 소요시간 그래프도 마찬가지다. 일일 예산과 작업 스레드는 프로세스에 하나씩 둔다.
    app.state.graph_budget = DailyCallBudget(settings.graph_daily_call_budget)
    app.state.graph_executor = ThreadPoolExecutor(max_workers=settings.graph_max_workers, thread_name_prefix="route-graph")
    app.state.settings = settings
    app.state.provider = provider
    app.state.solver = DepartureSolver(provider, settings.solver_config(), clock=clock)
    app.state.db_pool = pool
    app.state.auth = auth
    app.state.favorites = favorites
    app.state.history = history
    app.state.oauth_clients = oauth_clients
    app.state.summary_client = summary_client
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
    app.include_router(favorites_api.router)
    app.include_router(history_api.router)
    app.include_router(stats_api.router)
    app.include_router(departure.router)
    app.include_router(routes.router)
    app.include_router(summary_api.router)
    return app
