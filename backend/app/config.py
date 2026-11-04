"""환경변수 설정. 비밀 값은 코드에 쓰지 않고 환경변수로만 받는다 (루트 .env.example 참고)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from app.departure import MockRouteProvider, RouteProvider, SolverConfig

ROUTE_PROVIDERS = ("mock", "kakao")


@dataclass(frozen=True)
class Settings:
    route_provider: str = "mock"
    kakao_rest_api_key: str | None = None
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
            kakao_rest_api_key=env.get("KAKAO_REST_API_KEY") or None,
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
    raise NotImplementedError("KakaoRouteProvider는 아직 구현 전입니다. ROUTE_PROVIDER=mock을 쓰세요.")


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name}는 정수여야 합니다: {value}") from None
