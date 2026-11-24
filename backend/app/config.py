"""환경변수 설정. 비밀 값은 코드에 쓰지 않고 환경변수로만 받는다 (루트 .env.example 참고)."""

import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from app.ai_summary.client import GeminiClient
from app.auth.oauth import GoogleOAuthClient, KakaoOAuthClient, MockOAuthClient, OAuthClient
from app.auth.service import AUTH_STORES
from app.db import MySQLConfig
from app.departure import ROUTE_OPTIONS, KakaoRouteProvider, MockRouteProvider, RouteOption, RouteProvider, SolverConfig
from app.route_graph import GraphConfig

ROUTE_PROVIDERS = ("mock", "kakao")
# 로컬 개발용 프론트 주소 (VS Code Live Server 기본 포트)
DEFAULT_CORS_ORIGINS = ("http://localhost:5500", "http://127.0.0.1:5500")
BACKEND_DIR = Path(__file__).resolve().parents[1]
# 앞의 파일이 우선한다. 이미 설정된 환경변수는 덮어쓰지 않으므로 우선순위는 환경변수 > backend/.env > 루트 .env다.
ENV_FILES = (BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env")
# GA4 웹 스트림 측정 ID (프론트 gtag용 공개 값). 형식이 틀리면 쓰지 않는다.
GA4_MEASUREMENT_ID_PATTERN = re.compile(r"G-[A-Z0-9]+")

logger = logging.getLogger("app.config")


def valid_ga4_measurement_id(value: str | None) -> str:
    """측정 ID가 G-XXXX 형식이면 그대로, 아니면 빈 문자열."""
    value = (value or "").strip()
    return value if GA4_MEASUREMENT_ID_PATTERN.fullmatch(value) else ""


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
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    route_compare_options: tuple[str, ...] = tuple(ROUTE_OPTIONS)  # 경로 비교에 쓸 옵션과 카드 순서
    route_compare_max_calls: int = 6  # 경로 비교의 옵션 하나당 소요시간 조회 상한 (상세 조회는 따로 옵션당 1~2회)
    # 소요시간 그래프 (GET /api/routes/graph). 카카오 약관상 응답 캐시가 불가하므로 캐시 설정은 두지 않는다.
    graph_slots_before: int = 3  # 카드 출발시각 앞 슬롯 수
    graph_slots_after: int = 3  # 뒤 슬롯 수
    graph_slot_interval_min: int = 15  # 슬롯 간격(분)
    graph_time_budget_sec: float = 8  # 요청 하나의 서버 시간 예산. 넘으면 받은 점까지 돌려준다 (프론트 제한 10초)
    graph_max_workers: int = 4  # 슬롯 동시 조회 수 (앱 전체 공유)
    graph_daily_call_budget: int = 1500  # 그래프 전용 일일 카카오 호출 수 (KST 날짜 기준, 프로세스별)
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
    # AI 경로 요약 (POST /api/routes/summary). 키나 모델이 없으면 Gemini를 부르지 않고 rule 요약을 돌려준다.
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_model: str | None = None
    ai_summary_timeout_sec: float = 6  # Gemini 요청 제한 시간(초). 프론트 제한 10초보다 짧게

    ga4_property_id: str | None = None
    ga4_collection_start_date: str | None = None
    # 브라우저에 공개하는 값 (GET /api/config). 비어 있어도 앱은 시작한다. 지도 키는 로그에 나오지 않게 repr에서 뺀다.
    kakao_js_key: str = field(default="", repr=False)
    ga4_measurement_id: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        provider = env.get("ROUTE_PROVIDER", "mock").strip().lower() or "mock"
        if provider not in ROUTE_PROVIDERS:
            raise ValueError(f"ROUTE_PROVIDER는 {', '.join(ROUTE_PROVIDERS)} 중 하나여야 합니다: {provider}")
        return cls(
            route_provider=provider,
            ga4_property_id=env.get("GA4_PROPERTY_ID", "").strip() or None,
            ga4_collection_start_date=env.get("GA4_COLLECTION_START_DATE", "").strip() or None,
            kakao_js_key=env.get("KAKAO_JS_KEY", "").strip(),
            ga4_measurement_id=_ga4_measurement_id_env(env),
            kakao_rest_api_key=env.get("KAKAO_REST_API_KEY", "").strip() or None,
            departure_max_calls=_int_env(env, "DEPARTURE_MAX_CALLS", cls.departure_max_calls),
            departure_search_window_min=_int_env(env, "DEPARTURE_SEARCH_WINDOW_MIN", cls.departure_search_window_min),
            cors_origins=_cors_origins_env(env),
            route_compare_options=_route_compare_options_env(env),
            route_compare_max_calls=_int_env(env, "ROUTE_COMPARE_MAX_CALLS", cls.route_compare_max_calls),
            graph_slots_before=_int_env(env, "GRAPH_SLOTS_BEFORE", cls.graph_slots_before, minimum=0),
            graph_slots_after=_int_env(env, "GRAPH_SLOTS_AFTER", cls.graph_slots_after, minimum=0),
            graph_slot_interval_min=_int_env(env, "GRAPH_SLOT_INTERVAL_MIN", cls.graph_slot_interval_min, minimum=1),
            graph_time_budget_sec=_positive_float_env(env, "GRAPH_TIME_BUDGET_SEC", cls.graph_time_budget_sec),
            graph_max_workers=_int_env(env, "GRAPH_MAX_WORKERS", cls.graph_max_workers, minimum=1),
            graph_daily_call_budget=_int_env(env, "GRAPH_DAILY_CALL_BUDGET", cls.graph_daily_call_budget, minimum=0),
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
            gemini_api_key=env.get("GEMINI_API_KEY", "").strip() or None,
            gemini_model=env.get("GEMINI_MODEL", "").strip() or None,
            ai_summary_timeout_sec=_positive_float_env(env, "AI_SUMMARY_TIMEOUT_SEC", cls.ai_summary_timeout_sec),
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

    def graph_config(self) -> GraphConfig:
        return GraphConfig(
            slots_before=self.graph_slots_before,
            slots_after=self.graph_slots_after,
            interval_min=self.graph_slot_interval_min,
            max_workers=self.graph_max_workers,
        )


def create_route_provider(settings: Settings) -> RouteProvider:
    if settings.route_provider == "mock":
        return MockRouteProvider()
    if not settings.kakao_rest_api_key:
        raise ValueError("ROUTE_PROVIDER=kakao에는 KAKAO_REST_API_KEY 환경변수가 필요합니다.")
    return KakaoRouteProvider(settings.kakao_rest_api_key)


def create_summary_client(settings: Settings) -> GeminiClient | None:
    """AI 요약용 Gemini 클라이언트. 키나 모델이 없으면 None (앱은 시작하고 요약은 rule로 돌려준다)."""
    if not (settings.gemini_api_key and settings.gemini_model):
        return None
    return GeminiClient(settings.gemini_api_key, settings.gemini_model, timeout=settings.ai_summary_timeout_sec)


def create_oauth_clients(settings: Settings) -> dict[str, OAuthClient]:
    """설정된 소셜 로그인 제공자. 아무것도 설정하지 않으면 빈 dict (소셜 로그인은 auth_result=failed).

    설정이 반쯤만 있으면 앱 시작에서 빠진 환경변수 이름을 알려 준다 (값은 출력하지 않는다).
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
            raise ValueError(f"{label} 로그인에는 {', '.join(missing)} 환경변수가 필요합니다.")
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


def _ga4_measurement_id_env(env: Mapping[str, str]) -> str:
    raw = env.get("GA4_MEASUREMENT_ID", "").strip()
    value = valid_ga4_measurement_id(raw)
    if raw and not value:
        # 값은 로그에 남기지 않는다.
        logger.warning("GA4_MEASUREMENT_ID 형식이 G-XXXX가 아니어서 비워 둡니다 (GA 수집 안 함).")
    return value


def _int_env(env: Mapping[str, str], name: str, default: int, minimum: int | None = None) -> int:
    value = env.get(name, "").strip()
    if not value:
        return default
    try:
        number = int(value)
    except ValueError:
        raise ValueError(f"{name}는 정수여야 합니다: {value}") from None
    if minimum is not None and number < minimum:
        raise ValueError(f"{name}는 {minimum} 이상이어야 합니다: {value}")
    return number


def _positive_float_env(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name, "").strip()
    if not value:
        return default
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"{name}는 숫자여야 합니다: {value}") from None
    if not (number > 0 and number != float("inf")):
        raise ValueError(f"{name}는 0보다 큰 숫자여야 합니다: {value}")
    return number


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
