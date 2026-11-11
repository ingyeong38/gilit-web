# 길잇 백엔드

백엔드 담당 인경. Python 3.11 이상, 웹 프레임워크는 FastAPI + uvicorn.

## 구조

```text
backend/
├── app/
│   ├── main.py                # 웹 서버 진입점 (uvicorn app.main:app)
│   ├── config.py              # 환경변수 설정, RouteProvider 선택
│   ├── api/                   # 웹 API (FastAPI)
│   │   ├── factory.py         # create_app: Provider·Solver를 한 번 만들고 CORS, 오류 처리, 라우터를 붙인다
│   │   ├── departure.py       # POST /api/departure
│   │   ├── health.py          # GET /health
│   │   ├── schemas.py         # 요청·응답 모델과 입력 검증
│   │   └── errors.py          # 예외 -> { "message": ... } 응답
│   └── departure/             # 출발시각 역산 엔진 (SFR-003)
│       ├── models.py          # Coordinate, TravelMode, DepartureResult
│       ├── providers.py       # RouteProvider(인터페이스), MockRouteProvider
│       ├── providers_kakao.py # KakaoRouteProvider (카카오모빌리티 미래 운행 정보)
│       ├── solver.py          # DepartureSolver, SolverConfig
│       ├── errors.py          # 예외
│       └── cli.py             # 실행 예제
├── tests/                     # pytest (test_kakao_live.py는 실제 API 호출, 기본 실행에서 제외)
├── pyproject.toml             # pytest 설정
├── requirements.txt           # requests, python-dotenv, fastapi, uvicorn
└── requirements-dev.txt       # requirements.txt + pytest, httpx2 (TestClient)
```

## 실행

`backend/`에서 실행한다. 아래는 Windows Git Bash 기준이고, macOS·Linux는 `venv/Scripts/` 대신 `venv/bin/`을 쓴다.

```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements-dev.txt

# 테스트 (실제 API는 부르지 않는다)
venv/Scripts/python -m pytest

# 웹 서버. http://127.0.0.1:8000/docs 에서 요청을 시험한다
venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# 실제 카카오 데이터로 웹 서버 실행 (.env에 ROUTE_PROVIDER=kakao를 두어도 된다)
ROUTE_PROVIDER=kakao venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# 실제 카카오 API 테스트 (KAKAO_REST_API_KEY 필요, 한 번에 약 10회 호출)
venv/Scripts/python -m pytest -m kakao_live

# 실행 예제: 김해시청 -> 동의대학교, 09:00 도착, 여유 10분 (Mock 데이터)
venv/Scripts/python -m app.departure.cli --from 35.2285,128.8894 --to 35.1441,129.0336 --arrive "2026-11-06 09:00" --buffer 10

# 같은 예제를 실제 카카오 API로
ROUTE_PROVIDER=kakao venv/Scripts/python -m app.departure.cli --from 35.2285,128.8894 --to 35.1441,129.0336 --arrive "2026-11-06 09:00" --buffer 10
```

Windows PowerShell·cmd에서는 `venv\Scripts\python -m uvicorn app.main:app --reload --port 8000`처럼 쓴다. PowerShell에서 환경변수를 잠깐 바꾸려면 `$env:ROUTE_PROVIDER = "kakao"`를 먼저 실행한다.

`--json`으로 엔진 결과의 JSON을 볼 수 있다 (camelCase, 웹 API 응답과 필드 이름이 다르다). 시간대 없이 쓴 시각은 한국 시간으로 본다. `--mode transit`은 Mock에서만 된다.

### 환경변수와 .env

설정은 `app/config.py`가 읽는다. 진입점(`cli.py`, 웹 서버의 `create_app`)이 `backend/.env`, 루트 `.env`를 차례로 읽고, 이미 있는 환경변수는 덮어쓰지 않는다. 우선순위는 환경변수 > `backend/.env` > 루트 `.env`다. 두 `.env` 모두 `.gitignore`에 들어 있다. 변수 목록은 루트 `.env.example`을 본다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `ROUTE_PROVIDER` | `mock` | `mock` 또는 `kakao` |
| `KAKAO_REST_API_KEY` | 없음 | `kakao`일 때 필수. 카카오 개발자 앱의 REST API 키 |
| `DEPARTURE_MAX_CALLS` | `8` | 요청 하나당 소요시간 조회 최대 횟수 |
| `DEPARTURE_SEARCH_WINDOW_MIN` | `360` | 도착 희망 시각 몇 분 전까지 출발시각을 찾을지 |
| `ROUTE_CACHE_TTL_SEC` | `600` | 카카오 소요시간 캐시 유지 시간(초). `0`이면 캐시하지 않는다 |
| `CORS_ORIGINS` | `http://localhost:5500,http://127.0.0.1:5500` | 웹 API를 부를 수 있는 프론트 출처 (쉼표 구분). `*`는 쓸 수 없다 |

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
- 경로 옵션: `get_route_summary(…, option)`은 `summary=true`로 소요시간·거리·통행료(`summary.fare.toll`, 없으면 `None`)만 받는다. 옵션(`RouteOption`, `app/departure/models.py`)은 `priority`(`RECOMMEND`/`TIME`/`DISTANCE`)와 `avoid`(`toll` 등, 여러 개면 `|`로 잇는다)로 정한다. 경로 비교의 4개 옵션은 `ROUTE_OPTIONS`(추천, 최단시간, 최단거리, 무료도로=`avoid=toll`)다. `get_duration`은 추천 옵션의 요약이다. `get_detailed_route(…, priority, avoid)`는 지도용 상세 좌표를 받고 캐시하지 않는다.
- 캐시: 같은 (출발지, 목적지, 출발시각(분), 경로 옵션)은 프로세스 메모리 LRU 캐시(기본 1,024건)로 다시 부르지 않는다. `/api/departure`와 경로 비교의 추천 옵션은 같은 캐시 항목을 쓴다. 항목은 `ROUTE_CACHE_TTL_SEC`(기본 10분)이 지나면 버려 예측값이 갱신된다. 적중해도 만료 시각은 늘어나지 않는다. 오류는 캐시하지 않는다. 웹 서버는 어댑터 하나를 여러 요청 스레드가 함께 쓰므로 캐시는 잠금 안에서 고친다. 서버 프로세스를 여러 개 띄우면 캐시는 프로세스마다 따로다.
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

## 웹 API

`POST /api/departure`와 `GET /health`를 구현했다. 전체 명세(필드 규칙, 오류 표, 해민과 합의할 항목)는 `docs/api-spec.md`에 있다.

- 앱은 `app/api/factory.py`의 `create_app`이 만든다. RouteProvider와 DepartureSolver는 이때 한 번만 만들어 모든 요청이 함께 쓴다 (카카오 어댑터의 캐시·HTTP 세션 공유).
- 엔드포인트는 동기 함수라 FastAPI가 스레드 풀에서 실행한다. 엔진과 카카오 어댑터가 블로킹 I/O(requests)를 쓰기 때문이다.
- 오류는 모두 `{ "message": "..." }`이다. 입력 검증 실패는 `400`(FastAPI 기본 `422` 목록 대신), `DepartureError`는 `400`/`422`, `RouteProviderError`는 `502`/`503`/`504`다. 5xx의 원래 메시지(HTTP 코드, 카카오 안내 문구 등)는 응답에 넣지 않고 `app.api` 로거로 서버 로그에만 남긴다.
- 테스트는 `app.main`을 import하지 않는다 (import하면 `.env`를 읽는다). `create_app(settings, provider, clock)`에 가짜 Provider와 고정 시각을 넣는다 (`tests/test_api.py`).

### 요청 예시

`/docs`에서 `POST /api/departure` → Try it out에 예시 본문이 채워져 있다. `arrive_at`은 미래 시각으로 바꿔서 보낸다. curl로는:

```bash
curl -X POST http://127.0.0.1:8000/api/departure \
  -H "Content-Type: application/json" \
  -d '{
    "origin": {"name": "김해시청", "lat": 35.2285, "lng": 128.8894},
    "destination": {"name": "동의대학교", "lat": 35.1441, "lng": 129.0336},
    "arrive_at": "2026-11-06T09:00:00+09:00",
    "buffer_min": 10,
    "travel_mode": "car"
  }'
```

응답 (`ROUTE_PROVIDER=kakao`, 2026-11-05에 실행한 실제 결과):

```json
{
  "recommended_depart_at": "2026-11-06T08:19:00+09:00",
  "duration_min": 31,
  "expected_arrive_at": "2026-11-06T08:49:25+09:00",
  "desired_arrive_at": "2026-11-06T09:00:00+09:00",
  "buffer_min": 10,
  "buffer_applied": true,
  "converged": true,
  "api_calls": 4,
  "data_source": "kakao"
}
```

오류 예시:

```json
// 400: 위도 범위 밖
{ "message": "목적지 위도는 -90~90 사이의 숫자여야 합니다." }
// 400: 지난 시각
{ "message": "도착 희망 시각이 이미 지났습니다." }
// 422: 출발지와 목적지가 같음 (카카오 result_code=104)
{ "message": "경로를 찾을 수 없습니다: 출발지와 도착지가 5 m 이내로 설정된 경우 경로를 탐색할 수 없음 (result_code=104)" }
// 502: 카카오 인증 실패 등. 원인은 서버 로그에만 남는다
{ "message": "길찾기 정보를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요." }
```


## 복원한 상세 도로 경로 API

`app/api/routes.py`의 `/api/places`, `/api/routes`와 `app/routing.py`의 상세 좌표 변환을 복원했습니다. 기존 `KakaoRouteProvider` 인증/오류 처리 및 `DepartureSolver`를 재사용합니다. 기존 인증 라우터와 별도 인증 개발 진입점은 보존했습니다.

프로젝트 루트에서:

```sh
ROUTE_PROVIDER=kakao backend/venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8003 --no-access-log
```

같은 서버가 frontend/를 제공하므로 별도 프론트 터미널은 필요 없습니다. 프론트 `USE_MOCK_ROUTES=false`, `BASE_URL="/api"`를 사용합니다. 서버 `.env`에 REST 키가 있어야 합니다. 기존 `.env`의 ROUTE_PROVIDER 값을 덮어쓰지 않고 실행 프로세스에만 kakao 모드를 적용합니다. 지도 키/기존 인증 설정은 변경하지 않습니다.

새 전체 경로 결과 캐시는 `ROUTE_CACHE_TTL_SEC`로 제어하며 최대 64건, 같은 이름/좌표·도착시각·여유시간에 적용됩니다. TTL=0이면 끕니다. 응답 헤더 `X-Gilit-Route-Cache`에서 HIT/MISS를 확인합니다. 기존 소요시간 캐시와는 별개이고 실패·이미 지난 출발시각은 재사용하지 않습니다.
