"""환경변수 설정. 비밀 값은 코드에 쓰지 않고 환경변수로만 받는다 (루트 .env.example 참고)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

from app.departure import KakaoRouteProvider, MockRouteProvider, RouteProvider, SolverConfig

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
        )

    def solver_config(self) -> SolverConfig:
        return SolverConfig(
            max_calls=self.departure_max_calls,
            search_window=timedelta(minutes=self.departure_search_window_min),
        )


def create_route_provider(settings: Settings) -> RouteProvider:
    if settings.route_provider == "mock":
        return MockRouteProvider()
    if not settings.kakao_rest_api_key:
        raise ValueError("ROUTE_PROVIDER=kakao에는 KAKAO_REST_API_KEY 환경변수가 필요합니다.")
    return KakaoRouteProvider(settings.kakao_rest_api_key, cache_ttl_sec=settings.route_cache_ttl_sec)


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name}는 정수여야 합니다: {value}") from None


def _cors_origins_env(env: Mapping[str, str]) -> tuple[str, ...]:
    """쉼표로 구분한 출처 목록. 비어 있으면 로컬 개발용 기본값을 쓴다."""
    origins = tuple(origin.strip().rstrip("/") for origin in env.get("CORS_ORIGINS", "").split(",") if origin.strip())
    if not origins:
        return DEFAULT_CORS_ORIGINS
    # 로그인 세션 쿠키를 함께 보내야 하므로(allow_credentials) 모든 출처 허용은 쓰지 않는다.
    if "*" in origins:
        raise ValueError("CORS_ORIGINS에는 *를 쓸 수 없습니다. 허용할 출처를 쉼표로 나열하세요.")
    return origins
