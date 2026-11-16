"""환경변수 설정. 비밀 값은 코드에 쓰지 않고 환경변수로만 받는다 (루트 .env.example 참고)."""

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from app.auth.oauth import GoogleOAuthClient, KakaoOAuthClient, MockOAuthClient, OAuthClient
from app.auth.service import AUTH_STORES
from app.db import MySQLConfig
from app.departure import ROUTE_OPTIONS, KakaoRouteProvider, MockRouteProvider, RouteOption, RouteProvider, SolverConfig

logger = logging.getLogger(__name__)

ROUTE_PROVIDERS = ("mock", "kakao")
# 로컬 개발용 프론트 주소 (VS Code Live Server 기본 포트)
DEFAULT_CORS_ORIGINS = ("http://localhost:5500", "http://127.0.0.1:5500")
BACKEND_DIR = Path(__file__).resolve().parents[1]
# 앞의 파일이 우선한다. 이미 설정된 환경변수는 덮어쓰지 않으므로 우선순위는 환경변수 > backend/.env > 루트 .env다.
ENV_FILES = (BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env")


def load_env_files(paths: tuple[Path, ...] = ENV_FILES) -> None:
    """.env 파일을 환경변수로 읽는다. 진입점(cli, 웹 서버)에서 한 번 부른다. import만으로는 읽지 않는다."""
    for path in paths:
        if path.is_file():
            load_dotenv(path, override=False)


@dataclass(frozen=True)
class Settings:
    route_provider: str = "mock"
    kakao_rest_api_key: str | None = field(default=None, repr=False)  # repr로 키가 출력되지 않게 한다
    departure_max_calls: int = 8
    departure_search_window_min: int = 360
    route_cache_ttl_sec: int = 600  # 카카오 소요시간 캐시 유지 시간. 0이면 캐시하지 않는다
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    route_compare_options: tuple[str, ...] = tuple(ROUTE_OPTIONS)  # 경로 비교에 쓸 옵션과 카드 순서
    route_compare_max_calls: int = 6  # 경로 비교의 옵션 하나당 소요시간 조회 상한 (상세 조회는 따로 옵션당 1~2회)
    auth_store: str = "memory"  # 회원·세션 저장소. memory(재시작하면 사라짐) | mysql
    cookie_secure: bool = True  # 세션 쿠키의 Secure 속성. 로컬 http에서 쿠키가 안 실리면 false
    secret_key: str | None = field(default=None, repr=False)  # 서명용 비밀 값 (OAuth state 쿠키)
    # MySQL 접속 정보. 로컬 MySQL과 RDS는 이 값만 다르다. 코드에 기본 호스트·계정을 두지 않는다.
    db_host: str | None = None
    db_port: int = 3306
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = field(default=None, repr=False)
    db_ssl_ca: str | None = None  # RDS CA 번들 경로. 주면 TLS로 연결한다
    # 소셜 로그인. 콜백 주소는 {oauth_redirect_base}/api/auth/{provider}/callback
    google_client_id: str | None = None
    google_client_secret: str | None = field(default=None, repr=False)
    # 카카오 로그인은 길찾기용 KAKAO_REST_API_KEY와 따로 받는다 (같은 앱의 REST API 키를 넣어도 된다)
    kakao_login_client_id: str | None = None
    kakao_login_client_secret: str | None = field(default=None, repr=False)
    oauth_redirect_base: str | None = None  # 예: http://localhost:8000. 제공자 콘솔에 등록한 주소와 같아야 한다
    oauth_mock: bool = False  # 외부 호출 없는 가짜 소셜 로그인. AUTH_STORE=memory에서만 쓸 수 있다

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        provider = env.get("ROUTE_PROVIDER", "mock").strip().lower() or "mock"
        if provider not in ROUTE_PROVIDERS:
            raise ValueError(f"ROUTE_PROVIDER는 {', '.join(ROUTE_PROVIDERS)} 중 하나여야 합니다: {provider}")
        return cls(
            route_provider=provider,
            kakao_rest_api_key=env.get("KAKAO_REST_API_KEY", "").strip() or None,
            departure_max_calls=_int_env(env, "DEPARTURE_MAX_CALLS", cls.departure_max_calls),
            departure_search_window_min=_int_env(env, "DEPARTURE_SEARCH_WINDOW_MIN", cls.departure_search_window_min),
            route_cache_ttl_sec=_int_env(env, "ROUTE_CACHE_TTL_SEC", cls.route_cache_ttl_sec),
            cors_origins=_cors_origins_env(env),
            route_compare_options=_route_compare_options_env(env),
            route_compare_max_calls=_int_env(env, "ROUTE_COMPARE_MAX_CALLS", cls.route_compare_max_calls),
            auth_store=_auth_store_env(env),
            cookie_secure=_bool_env(env, "COOKIE_SECURE", cls.cookie_secure),
            secret_key=env.get("SECRET_KEY", "").strip() or None,
            db_host=env.get("DB_HOST", "").strip() or None,
            db_port=_int_env(env, "DB_PORT", cls.db_port),
            db_name=env.get("DB_NAME", "").strip() or None,
            db_user=env.get("DB_USER", "").strip() or None,
            db_password=env.get("DB_PASSWORD") or None,  # 비밀번호는 공백도 값일 수 있어 자르지 않는다
            db_ssl_ca=env.get("DB_SSL_CA", "").strip() or None,
            google_client_id=env.get("GOOGLE_CLIENT_ID", "").strip() or None,
            google_client_secret=env.get("GOOGLE_CLIENT_SECRET", "").strip() or None,
            kakao_login_client_id=env.get("KAKAO_LOGIN_CLIENT_ID", "").strip() or None,
            kakao_login_client_secret=env.get("KAKAO_LOGIN_CLIENT_SECRET", "").strip() or None,
            oauth_redirect_base=_redirect_base_env(env),
            oauth_mock=_bool_env(env, "OAUTH_MOCK", cls.oauth_mock),
        )

    def mysql_config(self) -> MySQLConfig:
        """DB 접속 정보. 빠진 값이 있으면 이름을 알려 준다 (값은 출력하지 않는다)."""
        required = {"DB_HOST": self.db_host, "DB_NAME": self.db_name, "DB_USER": self.db_user, "DB_PASSWORD": self.db_password}
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"AUTH_STORE=mysql에는 {', '.join(missing)} 환경변수가 필요합니다.")
        return MySQLConfig(
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            user=self.db_user,
            password=self.db_password,
            ssl_ca=self.db_ssl_ca,
        )

    def solver_config(self) -> SolverConfig:
        return SolverConfig(
            max_calls=self.departure_max_calls,
            search_window=timedelta(minutes=self.departure_search_window_min),
        )


    def compare_solver_config(self) -> SolverConfig:
        """경로 비교의 옵션별 역산 설정. 탐색 구간은 출발시각 역산과 같고 조회 상한만 다르다."""
        return SolverConfig(
            max_calls=self.route_compare_max_calls,
            search_window=timedelta(minutes=self.departure_search_window_min),
        )

    def route_options(self) -> tuple[RouteOption, ...]:
        return tuple(ROUTE_OPTIONS[key] for key in self.route_compare_options)


def create_route_provider(settings: Settings) -> RouteProvider:
    if settings.route_provider == "mock":
        return MockRouteProvider()
    if not settings.kakao_rest_api_key:
        raise ValueError("ROUTE_PROVIDER=kakao에는 KAKAO_REST_API_KEY 환경변수가 필요합니다.")
    return KakaoRouteProvider(settings.kakao_rest_api_key, cache_ttl_sec=settings.route_cache_ttl_sec)


def create_oauth_clients(settings: Settings) -> dict[str, OAuthClient]:
    """설정된 소셜 로그인 제공자. 아무것도 설정하지 않으면 빈 dict (소셜 로그인은 auth_result=failed).

    설정이 부족한 제공자만 끄고 빠진 환경변수 이름을 기록한다 (값은 출력하지 않는다).
    """
    if settings.oauth_mock:
        if settings.auth_store != "memory":
            raise ValueError("OAUTH_MOCK은 AUTH_STORE=memory일 때만 쓸 수 있습니다 (가짜 계정이 DB에 남지 않게).")
        if not settings.secret_key:
            raise ValueError("OAUTH_MOCK에도 SECRET_KEY 환경변수가 필요합니다 (state 쿠키 서명).")
        return {provider: MockOAuthClient(provider) for provider in ("google", "kakao")}

    clients: dict[str, OAuthClient] = {}
    providers = (
        ("google", "Google", "GOOGLE_CLIENT_ID", settings.google_client_id, "GOOGLE_CLIENT_SECRET", settings.google_client_secret, GoogleOAuthClient),
        ("kakao", "카카오", "KAKAO_LOGIN_CLIENT_ID", settings.kakao_login_client_id, "KAKAO_LOGIN_CLIENT_SECRET", settings.kakao_login_client_secret, KakaoOAuthClient),
    )
    for provider, label, id_name, client_id, secret_name, client_secret, client_class in providers:
        if not (client_id or client_secret):
            continue
        required = {
            id_name: client_id,
            secret_name: client_secret,
            "SECRET_KEY": settings.secret_key,
            "OAUTH_REDIRECT_BASE": settings.oauth_redirect_base,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            logger.warning("%s 로그인 비활성화: 필요한 환경변수 %s", label, ", ".join(missing))
            continue
        clients[provider] = client_class(client_id, client_secret)
    return clients


def _redirect_base_env(env: Mapping[str, str]) -> str | None:
    value = env.get("OAUTH_REDIRECT_BASE", "").strip().rstrip("/")
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query:
        raise ValueError(f"OAUTH_REDIRECT_BASE는 http(s)://호스트[:포트] 형식이어야 합니다 (경로 없이): {value}")
    return value


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name}는 정수여야 합니다: {value}") from None


TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


def _bool_env(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name, "").strip().lower()
    if not value:
        return default
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValueError(f"{name}는 true 또는 false여야 합니다: {value}")


def _auth_store_env(env: Mapping[str, str]) -> str:
    store = env.get("AUTH_STORE", "").strip().lower() or "memory"
    if store not in AUTH_STORES:
        raise ValueError(f"AUTH_STORE는 {', '.join(AUTH_STORES)} 중 하나여야 합니다: {store}")
    return store


def _cors_origins_env(env: Mapping[str, str]) -> tuple[str, ...]:
    """쉼표로 구분한 출처 목록. 비어 있으면 로컬 개발용 기본값을 쓴다."""
    origins = tuple(origin.strip().rstrip("/") for origin in env.get("CORS_ORIGINS", "").split(",") if origin.strip())
    if not origins:
        return DEFAULT_CORS_ORIGINS
    # 로그인 세션 쿠키를 함께 보내야 하므로(allow_credentials) 모든 출처 허용은 쓰지 않는다.
    if "*" in origins:
        raise ValueError("CORS_ORIGINS에는 *를 쓸 수 없습니다. 허용할 출처를 쉼표로 나열하세요.")
    return origins


def _route_compare_options_env(env: Mapping[str, str]) -> tuple[str, ...]:
    """쉼표로 구분한 경로 옵션 키. 적은 순서가 카드 순서다. 비어 있으면 4개 모두."""
    keys = tuple(key.strip().lower() for key in env.get("ROUTE_COMPARE_OPTIONS", "").split(",") if key.strip())
    if not keys:
        return tuple(ROUTE_OPTIONS)
    unknown = [key for key in keys if key not in ROUTE_OPTIONS]
    if unknown:
        raise ValueError(f"ROUTE_COMPARE_OPTIONS는 {', '.join(ROUTE_OPTIONS)} 중에서 고릅니다: {', '.join(unknown)}")
    if len(set(keys)) != len(keys):
        raise ValueError("ROUTE_COMPARE_OPTIONS에 같은 옵션이 두 번 있습니다.")
    return keys
