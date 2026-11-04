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
│       ├── providers_kakao.py # KakaoRouteProvider (카카오모빌리티 미래 운행 정보)
│       ├── solver.py          # DepartureSolver, SolverConfig
│       ├── errors.py          # 예외
│       └── cli.py             # 실행 예제
├── tests/                     # pytest (test_kakao_live.py는 실제 API 호출, 기본 실행에서 제외)
├── pyproject.toml             # pytest 설정
├── requirements.txt           # requests, python-dotenv
└── requirements-dev.txt       # requirements.txt + pytest
```

## 실행

`backend/`에서 실행한다. 아래는 Windows Git Bash 기준이고, macOS·Linux는 `venv/Scripts/` 대신 `venv/bin/`을 쓴다.

```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements-dev.txt

# 테스트 (실제 API는 부르지 않는다)
venv/Scripts/python -m pytest

# 실제 카카오 API 테스트 (KAKAO_REST_API_KEY 필요, 한 번에 약 10회 호출)
venv/Scripts/python -m pytest -m kakao_live

# 실행 예제: 김해시청 -> 동의대학교, 09:00 도착, 여유 10분 (Mock 데이터)
venv/Scripts/python -m app.departure.cli --from 35.2285,128.8894 --to 35.1441,129.0336 --arrive "2026-11-06 09:00" --buffer 10

# 같은 예제를 실제 카카오 API로
ROUTE_PROVIDER=kakao venv/Scripts/python -m app.departure.cli --from 35.2285,128.8894 --to 35.1441,129.0336 --arrive "2026-11-06 09:00" --buffer 10
```

`--json`으로 API 응답 필드 이름의 JSON을 볼 수 있다. 시간대 없이 쓴 시각은 한국 시간으로 본다. `--mode transit`은 Mock에서만 된다.

### 환경변수와 .env

설정은 `app/config.py`가 읽는다. 진입점(`cli.py`)이 `backend/.env`, 루트 `.env`를 차례로 읽고, 이미 있는 환경변수는 덮어쓰지 않는다. 우선순위는 환경변수 > `backend/.env` > 루트 `.env`다. 두 `.env` 모두 `.gitignore`에 들어 있다. 변수 목록은 루트 `.env.example`을 본다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `ROUTE_PROVIDER` | `mock` | `mock` 또는 `kakao` |
| `KAKAO_REST_API_KEY` | 없음 | `kakao`일 때 필수. 카카오 개발자 앱의 REST API 키 |
| `DEPARTURE_MAX_CALLS` | `8` | 요청 하나당 소요시간 조회 최대 횟수 |
| `DEPARTURE_SEARCH_WINDOW_MIN` | `360` | 도착 희망 시각 몇 분 전까지 출발시각을 찾을지 |

테스트는 `tests/conftest.py`의 fixture가 이 변수들을 지우고 `.env`도 읽지 않으므로, `.env`에 `ROUTE_PROVIDER=kakao`를 두어도 기본 테스트는 실제 API를 부르지 않는다.

## 출발시각 역산 엔진

도착 희망 시각까지 도착하는 가장 늦은 출발시각을 분 단위로 찾는다.

- 목표 도착시각은 `도착 희망 시각 - 여유시간`이다 (`docs/api-spec.md`의 `arriveTime = arrive - buffer`와 같다). 가장 늦은 출발시각에서 여유시간을 빼는 방식은 혼잡이 심해지는 시간대에서 실제 여유가 요청보다 줄어들 수 있어 쓰지 않는다.
- 1차 추정(`도착 희망 시각 - 기준 소요시간`)으로 시작해, 제시간 도착하는 출발시각과 늦는 출발시각 사이 구간을 1분 이하로 좁힌다. 다음 후보는 도착시각이 목표와 어긋난 만큼 옮긴 추정값이고, 그 값이 구간 밖이면 이분탐색한다.
- 같은 출발시각은 다시 조회하지 않는다. 조회 한도(`DEPARTURE_MAX_CALLS`, 기본 8회)에 걸리면 그때까지 확인한 시각 중 가장 늦은 것을 돌려주고 `converged=False`로 표시한다. 이 값은 정답보다 이르거나 같으므로 늦지 않는다.
- 지금 출발해도 여유시간을 둘 수 없으면 여유 없이 다시 계산하고 `buffer_applied=False`로 표시한다.
- 오류: 도착 희망 시각이 지남(`ArrivalTimePassedError`), 지금 또는 탐색 구간(`DEPARTURE_SEARCH_WINDOW_MIN`, 기본 6시간) 안에 출발해도 늦음(`NoFeasibleDepartureError`). 메시지는 API `4xx`의 `message`로 그대로 쓸 수 있다.

### 카카오모빌리티 어댑터 (`KakaoRouteProvider`)

`GET https://apis-navi.kakaomobility.com/v1/future/directions`로 출발시각별 자동차 소요시간(`routes[0].summary.duration`, 초)을 조회한다.

- 좌표: 카카오는 `경도,위도` 순서다. 엔진의 `Coordinate`(위도, 경도)를 어댑터에서 바꾼다.
- 출발시각: 한국 시간 `YYYYMMDDHHmm`. 초는 내린다. 도착 희망 시각은 내일 이후로 준다 (미래 운행 정보 API).
- 이동수단: `car`만 된다. `transit`은 `UnsupportedTravelModeError`("대중교통은 아직 지원하지 않습니다.").
- 캐시: 같은 (출발지, 목적지, 출발시각(분), 이동수단)은 프로세스 메모리 LRU 캐시(기본 1,024건)로 다시 부르지 않는다. 오류는 캐시하지 않는다. 만료 시간은 없으므로, 웹 서버로 오래 띄우면 예측값이 갱신되지 않는다.
- 쿼터: 일일 5,000건. 검색 한 번에 최대 `DEPARTURE_MAX_CALLS`(8)회라 하루 약 625회 검색까지 된다. `request_count`로 실제 호출 수를 볼 수 있다.
- 타임아웃: 10초.

| 상황 | 예외 | API 응답으로 쓸 때 |
| --- | --- | --- |
| `result_code != 0` (예: 104 출발지와 도착지가 5m 이내, 103 도착 지점 주변 도로 없음) | `RouteNotFoundError` (`DepartureError`) | `4xx` |
| `transit` 요청 | `UnsupportedTravelModeError` (`DepartureError`) | `4xx` |
| HTTP 401, 403 | `ProviderAuthError` | `5xx` |
| HTTP 429 | `ProviderQuotaExceededError` | `5xx` |
| 타임아웃 | `ProviderTimeoutError` | `5xx` |
| HTTP 5xx, 연결 실패 | `ProviderUnavailableError` | `5xx` |
| HTTP 400 등 (예: 좌표 순서가 뒤바뀜 "출발지가 유효하지 않습니다.") | `ProviderBadRequestError` | `5xx` |
| 응답 형식 이상 | `RouteProviderError` | `5xx` |

`Provider*Error`는 모두 `RouteProviderError`의 하위 클래스다. 메시지는 한국어이고 API 키를 넣지 않는다. 카카오는 401 응답 본문에 보낸 키를 그대로 돌려주므로 인증 오류에서는 본문을 읽지 않고, 다른 오류에 붙이는 카카오 안내 문구에서도 키를 가린다. requests 예외는 종류 이름만 남기고 예외 체인에 붙이지 않는다. `Settings`와 `KakaoRouteProvider`의 `repr`에도 키가 나오지 않는다.

### 다른 길찾기 API로 바꾸기

`RouteProvider`를 상속해 `get_duration(origin, dest, depart_at, travel_mode)`(초 단위)만 구현하고, `app/config.py`의 `create_route_provider`에서 돌려주면 된다. 엔진 코드는 바꾸지 않는다. 엔진은 먼저 출발하면 늦게 도착하지 않는다(FIFO)고 가정한다. API 키는 환경변수(`KAKAO_REST_API_KEY`)로만 받는다. 루트 `.env.example`을 참고한다.

`MockRouteProvider`는 직선거리와 출퇴근 혼잡(08:00, 18:30 전후)을 흉내 낸 가짜 데이터다. 실제 교통 정보와 무관하다.
