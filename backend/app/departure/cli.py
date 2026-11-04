"""출발시각 역산 실행 예제.

backend/에서 실행한다:
    python -m app.departure.cli --from 35.2285,128.8894 --to 35.1441,129.0336 --arrive "2026-11-06 09:00" --buffer 10

ROUTE_PROVIDER=kakao이면 카카오모빌리티 미래 운행 정보를 쓴다. 도착 희망 시각은 내일 이후로 준다.
"""

import argparse
import json
import sys
from datetime import datetime

from app.config import Settings, create_route_provider, load_env_files
from app.departure import (
    KST,
    Coordinate,
    DepartureError,
    DepartureResult,
    DepartureSolver,
    RouteProviderError,
    TravelMode,
)

WEEKDAYS = "월화수목금토일"
PROVIDER_LABELS = {"mock": "Mock (가짜 데이터)", "kakao": "카카오모빌리티 미래 운행 정보"}


def parse_arrive(text: str) -> datetime:
    """ISO 8601 시각. 시간대가 없으면 한국 시간으로 본다."""
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"시각은 '2026-11-05 09:00' 형식이어야 합니다: {text}") from None
    return value if value.tzinfo else value.replace(tzinfo=KST)


def parse_coordinate(text: str) -> Coordinate:
    try:
        return Coordinate.parse(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="도착 희망 시각으로 권장 출발시각을 계산합니다.")
    parser.add_argument("--from", dest="origin", required=True, type=parse_coordinate, help="출발지 '위도,경도'")
    parser.add_argument("--to", dest="dest", required=True, type=parse_coordinate, help="목적지 '위도,경도'")
    parser.add_argument("--arrive", required=True, type=parse_arrive, help="도착 희망 시각 (예: '2026-11-06 09:00'). 카카오 사용 시 내일 이후")
    parser.add_argument("--buffer", type=int, default=0, help="여유시간(분), 기본 0")
    parser.add_argument("--mode", choices=[mode.value for mode in TravelMode], default="car", help="이동수단, 기본 car")
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    return parser


def format_time(value: datetime) -> str:
    local = value.astimezone(KST)
    return f"{local:%Y-%m-%d} ({WEEKDAYS[local.weekday()]}) {local:%H:%M}"


def format_result(result: DepartureResult, provider: str = "mock") -> str:
    lines = [
        f"권장 출발시각: {format_time(result.depart_at)}",
        f"예상 소요시간: {result.duration_min}분",
        f"예상 도착시각: {format_time(result.arrive_at)}",
        f"도착 희망 시각: {format_time(result.target_arrive_at)}",
    ]
    if result.buffer_applied:
        lines.append(f"여유시간: {result.buffer_min}분 반영")
    elif result.buffer_min:
        lines.append(f"여유시간: {result.buffer_min}분을 반영하지 못했습니다 (지금 출발해도 여유를 둘 수 없음)")
    else:
        lines.append("여유시간: 없음")
    lines.append(f"소요시간 조회: {result.provider_calls}회 ({PROVIDER_LABELS[provider]})")
    if not result.converged:
        lines.append("조회 한도에 걸려, 확인된 시각 중 가장 늦은 시각을 안내합니다. 실제로는 조금 더 늦게 출발해도 됩니다.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_files()
    try:
        settings = Settings.from_env()
        solver = DepartureSolver(create_route_provider(settings), settings.solver_config())
        result = solver.solve(args.origin, args.dest, args.arrive, args.buffer, args.mode)
    except (DepartureError, RouteProviderError, ValueError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_result(result, settings.route_provider))
    return 0


if __name__ == "__main__":
    sys.exit(main())
