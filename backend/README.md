# 길잇 백엔드

백엔드 담당 해민. Python 3.11 이상. 웹 프레임워크는 아직 정하지 않았다.

## 구조

```text
backend/
├── app/
│   ├── config.py              # 환경변수 설정, RouteProvider 선택
│   └── departure/             # 출발시각 역산 엔진 (SFR-003)
│       ├── models.py          # Coordinate, TravelMode, DepartureResult
│       ├── providers.py       # RouteProvider(인터페이스), MockRouteProvider
│       ├── solver.py          # DepartureSolver, SolverConfig
│       ├── errors.py          # 예외
│       └── cli.py             # 실행 예제
├── tests/                     # pytest
├── pyproject.toml             # pytest 설정
└── requirements-dev.txt
```

## 실행

`backend/`에서 실행한다. 아래는 Windows Git Bash 기준이고, macOS·Linux는 `venv/Scripts/` 대신 `venv/bin/`을 쓴다.

```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements-dev.txt

# 테스트
venv/Scripts/python -m pytest

# 실행 예제: 김해시청 -> 동의대학교, 09:00 도착, 여유 10분
venv/Scripts/python -m app.departure.cli --from 35.2285,128.8894 --to 35.1441,129.0336 --arrive "2026-11-05 09:00" --buffer 10
```

`--mode transit`으로 대중교통, `--json`으로 API 응답 필드 이름의 JSON을 볼 수 있다. 시간대 없이 쓴 시각은 한국 시간으로 본다.

## 출발시각 역산 엔진

도착 희망 시각까지 도착하는 가장 늦은 출발시각을 분 단위로 찾는다.

- 목표 도착시각은 `도착 희망 시각 - 여유시간`이다 (`docs/api-spec.md`의 `arriveTime = arrive - buffer`와 같다). 가장 늦은 출발시각에서 여유시간을 빼는 방식은 혼잡이 심해지는 시간대에서 실제 여유가 요청보다 줄어들 수 있어 쓰지 않는다.
- 1차 추정(`도착 희망 시각 - 기준 소요시간`)으로 시작해, 제시간 도착하는 출발시각과 늦는 출발시각 사이 구간을 1분 이하로 좁힌다. 다음 후보는 도착시각이 목표와 어긋난 만큼 옮긴 추정값이고, 그 값이 구간 밖이면 이분탐색한다.
- 같은 출발시각은 다시 조회하지 않는다. 조회 한도(`DEPARTURE_MAX_CALLS`, 기본 8회)에 걸리면 그때까지 확인한 시각 중 가장 늦은 것을 돌려주고 `converged=False`로 표시한다. 이 값은 정답보다 이르거나 같으므로 늦지 않는다.
- 지금 출발해도 여유시간을 둘 수 없으면 여유 없이 다시 계산하고 `buffer_applied=False`로 표시한다.
- 오류: 도착 희망 시각이 지남(`ArrivalTimePassedError`), 지금 또는 탐색 구간(`DEPARTURE_SEARCH_WINDOW_MIN`, 기본 6시간) 안에 출발해도 늦음(`NoFeasibleDepartureError`). 메시지는 API `4xx`의 `message`로 그대로 쓸 수 있다.

### 실제 길찾기 API로 바꾸기

`RouteProvider`를 상속해 `get_duration(origin, dest, depart_at, travel_mode)`(초 단위)만 구현하고, `app/config.py`의 `create_route_provider`에서 돌려주면 된다. 엔진 코드는 바꾸지 않는다. 엔진은 먼저 출발하면 늦게 도착하지 않는다(FIFO)고 가정한다. API 키는 환경변수(`KAKAO_REST_API_KEY`)로만 받는다. 루트 `.env.example`을 참고한다.

`MockRouteProvider`는 직선거리와 출퇴근 혼잡(08:00, 18:30 전후)을 흉내 낸 가짜 데이터다. 실제 교통 정보와 무관하다.
