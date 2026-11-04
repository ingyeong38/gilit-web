"""환경변수 설정. 비밀 값은 코드에 쓰지 않고 환경변수로만 받는다 (루트 .env.example 참고)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

from app.departure import KakaoRouteProvider, MockRouteProvider, RouteProvider, SolverConfig

ROUTE_PROVIDERS = ("mock", "kakao")
BACKEND_DIR = Path(__file__).resolve().parents[1]
# 앞의 파일이 우선한다. 이미 설정된 환경변수는 덮어쓰지 않으므로 우선순위는 환경변수 > backend/.env > 루트 .env다.
ENV_FILES = (BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env")


def load_env_files(paths: tuple[Path, ...] = ENV_FILES) -> None:
    """.env 파일을 환경변수로 읽는다. 진입점(cli, 이후 웹 서버)에서 한 번 부른다. import만으로는 읽지 않는다."""
    for path in paths:
        if path.is_file():
            load_dotenv(path, override=False)


@dataclass(frozen=True)
class Settings:
    route_provider: str = "mock"
    kakao_rest_api_key: str | None = field(default=None, repr=False)  # repr로 키가 출력되지 않게 한다
    departure_max_calls: int = 8
    departure_search_window_min: int = 360

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
    return KakaoRouteProvider(settings.kakao_rest_api_key)


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name}는 정수여야 합니다: {value}") from None
