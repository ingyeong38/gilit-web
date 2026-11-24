# 길잇 백엔드

백엔드 담당 인경. Python 3.11 이상, 웹 프레임워크는 FastAPI + uvicorn.

## 구조

```text
backend/
├── app/
│   ├── main.py                # 웹 서버 진입점 (uvicorn app.main:app)
│   ├── config.py              # 환경변수 설정, RouteProvider 선택
│   ├── routing.py             # 경로 비교 서비스 (compare_routes), 상세 경로 파싱, 응답 캐시
│   ├── db.py                  # MySQL 연결 풀 (PyMySQL, utf8mb4, time_zone +09:00), KST 시각 변환
│   ├── favorites/             # 즐겨찾기 (F9): 검증, 저장소(memory·mysql, 마이그레이션 003 필요), 좌표 확정·중복·20개 제한
│   ├── history/               # 검색 기록 (F9): 쌓기만 하고 조회할 때 같은 검색을 묶음, 삭제는 user_id NULL 분리 (통계 보존),
│   │                          #   recording.py: GET /api/routes 성공 때 자동 저장 (5분 안 같은 검색 생략, 실패해도 응답 영향 없음)
│   ├── auth/                  # 회원 인증 (SFR-001): 검증, bcrypt, 저장소(memory·mysql), 세션, 횟수 제한, OAuth(Google·카카오·Mock), state 쿠키
│   ├── api/                   # 웹 API (FastAPI)
│   │   ├── factory.py         # create_app: Provider·Solver·DB 연결 풀·저장소(회원·즐겨찾기)를 한 번 만들고 CORS, 출처 검사, 오류 처리, 라우터를 붙인다
│   │   ├── auth.py            # /api/auth/signup·login·logout·me, require_user·optional_user 의존성
│   │   ├── oauth.py           # /api/auth/{provider}/start·callback (소셜 로그인), 접근 로그의 콜백 쿼리 가림
│   │   ├── favorites.py       # GET·POST·PATCH·DELETE /api/favorites (로그인 필요, ?id= 방식)
│   │   ├── history.py         # GET /api/history?limit=, DELETE /api/history[?id=] (로그인 필요)
│   │   ├── origin.py          # POST·PATCH·DELETE 출처(Origin) 검사 (CSRF 방어)
│   │   ├── departure.py       # POST /api/departure
│   │   ├── routes.py          # GET /api/places, GET /api/routes (경로 비교), 장소 확정, 응답 캐시
│   │   ├── health.py          # GET /health
│   │   ├── schemas.py         # 요청·응답 모델과 입력 검증
│   │   └── errors.py          # 예외 -> { "message": ... } 응답
│   └── departure/             # 출발시각 역산 엔진 (SFR-003)
│       ├── models.py          # Coordinate, TravelMode, DepartureResult, RouteOption, RouteSummary
│       ├── providers.py       # RouteProvider(인터페이스), MockRouteProvider
│       ├── providers_kakao.py # KakaoRouteProvider (카카오모빌리티 미래 운행 정보)
│       ├── solver.py          # DepartureSolver, SolverConfig
│       ├── errors.py          # 예외
│       └── cli.py             # 실행 예제
├── scripts/check_road_routes.py # 수동 실조회 점검 (호출이 많다. 아래 "경로 비교" 참고)
├── scripts/seed_dev_users.py  # 로컬 DB에 로그인 테스트 계정 만들기 (db/README.md "로컬 DB 준비")
├── tests/                     # pytest (kakao_live·mysql_live 마커 테스트는 기본 실행에서 제외)
├── pyproject.toml             # pytest 설정
├── requirements.txt           # requests, python-dotenv, fastapi, uvicorn, bcrypt, PyMySQL
└── requirements-dev.txt       # requirements.txt + pytest, httpx2 (TestClient)
```

## 실행

`backend/`에서 실행한다. 아래는 Windows Git Bash 기준이고, macOS·Linux는 `venv/Scripts/` 대신 `venv/bin/`을 쓴다.

```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements-dev.txt

# 테스트 (실제 API는 부르지 않는다)
venv\Scripts\python -m pytest

# 웹 서버. http://127.0.0.1:8000/docs 에서 요청을 시험한다
venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# 실제 카카오 데이터로 웹 서버 실행 (.env에 ROUTE_PROVIDER=kakao를 두어도 된다)
ROUTE_PROVIDER=kakao venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# 실제 카카오 API 테스트 (KAKAO_REST_API_KEY 필요, 한 번에 약 10회 호출)
venv/Scripts/python -m pytest -m kakao_live

# 실제 Gemini API 테스트 (GEMINI_API_KEY·GEMINI_MODEL 필요, 1회 호출)
venv/Scripts/python -m pytest -m gemini_live

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
| `ROUTE_COMPARE_OPTIONS` | `recommend,time,distance,free` | 경로 비교에 쓸 옵션. 적은 순서가 카드 순서다 |
| `ROUTE_COMPARE_MAX_CALLS` | `6` | 경로 비교의 옵션 하나당 소요시간 조회 상한. 상세 경로 조회는 옵션당 1~2회 따로 든다 |
| `CORS_ORIGINS` | `http://localhost:5500,http://127.0.0.1:5500` | 웹 API를 부를 수 있는 프론트 출처 (쉼표 구분). `*`는 쓸 수 없다. `/api/*` POST·PATCH·DELETE의 출처 검사도 이 목록과 같은 호스트만 허용한다 |
| `AUTH_STORE` | `memory` | 회원·세션 저장소. `memory`는 서버를 다시 시작하면 사라진다. `mysql`은 아래 `DB_*`가 필요하다 |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | 없음 (`DB_PORT`는 `3306`) | MySQL 접속 정보. 로컬 MySQL과 RDS는 이 값만 다르다. 계정은 서비스 계정 `gilit_app` (`db/README.md`) |
| `DB_SSL_CA` | 없음 | RDS CA 번들 경로. 주면 TLS로 연결한다 |
| `TEST_DB_NAME` | 없음 | `pytest -m mysql_live` 전용 DB (예: `gilit_test`). 테스트가 회원 데이터를 지우므로 `_test`로 끝나고 `DB_NAME`과 달라야 한다 |
| `COOKIE_SECURE` | `true` | 세션 쿠키(`gilit_session`)의 Secure 속성. 운영은 반드시 `true`. 로컬 http에서 쿠키가 안 실리면 `false` |
| `SECRET_KEY` | 없음 | 서명용 비밀 값. 소셜 로그인(OAuth state 쿠키 `gilit_oauth` 서명)에 필수 |
| `OAUTH_REDIRECT_BASE` | 없음 | 소셜 로그인 콜백 주소의 앞부분 (예: `http://localhost:8000`, 경로 없이). 콜백은 `{값}/api/auth/{google\|kakao}/callback`이고 제공자 콘솔에 똑같이 등록한다 |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | 없음 | Google OAuth 클라이언트 (웹 애플리케이션). 하나라도 있으면 둘 다와 `SECRET_KEY`, `OAUTH_REDIRECT_BASE`가 필요하다 |
| `KAKAO_LOGIN_CLIENT_ID`, `KAKAO_LOGIN_CLIENT_SECRET` | 없음 | 카카오 로그인 앱의 REST API 키와 Client Secret. 길찾기용 `KAKAO_REST_API_KEY`와 따로 받는다 (같은 앱이면 같은 키). 하나라도 있으면 둘 다와 `SECRET_KEY`, `OAUTH_REDIRECT_BASE`가 필요하다 |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | 없음 | AI 경로 요약(`POST /api/routes/summary`)의 Gemini API 키와 모델 이름. 둘 중 하나라도 없으면 Gemini를 부르지 않고 서버 규칙 요약(`source: "rule"`)을 돌려준다. 서버 시작에는 필요 없다 |
| `AI_SUMMARY_TIMEOUT_SEC` | `6` | Gemini 요청 제한 시간(초). 프론트 제한 10초보다 짧게 |
| `KAKAO_JS_KEY` | 없음 | 카카오 지도 JavaScript 키 (브라우저 공개 값). `GET /api/config`로 프론트에 내려 준다. 비어도 서버는 시작하고 지도는 좌표 미리보기 |
| `GA4_MEASUREMENT_ID` | 없음 | GA4 웹 스트림 측정 ID (`G-…`, 공개 값). `GET /api/config`로 내려 준다. 형식이 틀리면 빈 값으로 처리하고 이름만 경고 로그 |
| `OAUTH_MOCK` | `false` | `1`이면 외부 호출 없는 가짜 소셜 로그인 (Google·카카오 모두. start가 곧바로 콜백으로 이동, 고정 프로필, 카카오는 이메일 없음). `AUTH_STORE=memory`일 때만 켜지고, 켜면 실제 Google·카카오 설정은 쓰지 않는다 |

설정이 반쯤만 있으면(예: `KAKAO_LOGIN_CLIENT_ID`만 있음) 서버가 시작하지 않고 빠진 환경변수 이름만 알려 준다. 값은 출력하지 않는다.

`GET /api/config`(`app/api/config.py`)는 `kakaoJsKey`·`ga4MeasurementId` **두 값만** 돌려준다. 응답 모델에 필드를 명시해 만들고 `Settings`를 직렬화하지 않는다. 다른 설정(REST 키, 로그인 시크릿, `SECRET_KEY`, DB, Gemini, GA 서비스 계정)을 여기에 추가하지 않는다 (`tests/test_config_api.py`가 가짜 시크릿으로 확인한다).

테스트는 `tests/conftest.py`의 fixture가 이 변수들을 지우고 `.env`도 읽지 않으므로, `.env`에 `ROUTE_PROVIDER=kakao`, `AUTH_STORE=mysql`, 실제 Google·카카오 키를 두어도 기본 테스트는 실제 API와 DB를 쓰지 않는다. 회원 저장소 계약 테스트를 MySQL에서 돌리려면 `pytest -m mysql_live`를 쓴다 (`TEST_DB_NAME` DB에 `db/schema.sql`이 적용돼 있어야 한다).

### 회원 인증

API 계약(엔드포인트, 쿠키, `auth_result` 값, 소셜 계정 처리 방침)은 `docs/api-spec.md` "인증"과 "회원"에 있다. 코드는 `app/auth/`(도메인)와 `app/api/auth.py`·`oauth.py`(웹)로 나뉜다. 다른 API에서 로그인 사용자가 필요하면 `app/api/auth.py`의 `require_user`(없으면 401) 또는 `optional_user`(없으면 `None`) 의존성을 쓴다.

```bash
venv/Scripts/python -m pytest                     # 메모리 저장소, 가짜 OAuth 클라이언트 (외부 호출 없음)
venv/Scripts/python -m pytest -m mysql_live       # 같은 계약 테스트를 MySQL 테스트 DB에서 (db/README.md)
AUTH_STORE=memory OAUTH_MOCK=1 venv/Scripts/python -m uvicorn app.main:app --port 8000   # 가짜 소셜 로그인으로 서버 실행
```

### 즐겨찾기·검색 기록 (F9)

API 계약은 `docs/api-spec.md` "즐겨찾기"와 "검색 기록"에 있다. 저장소는 `AUTH_STORE`를 따라 메모리 또는 MySQL이고, MySQL은 회원 저장소와 같은 연결 풀(`app.state.db_pool`)을 쓴다. 저장소 메서드의 첫 인자는 항상 `user_id`이고 SQL은 `WHERE id = ? AND user_id = ?`라서, 남의 데이터는 없는 것과 같은 `404`다.

- 즐겨찾기(`app/favorites/`): 같은 사용자의 같은 별칭 금지(대소문자·악센트 무시, `409`), 사용자당 20개(`409`). MySQL은 `users` 행을 `FOR UPDATE`로 잠가 동시 추가에도 지킨다. 마이그레이션 003이 필요하다 (`db/README.md`).
- 검색 기록(`app/history/`): 행은 쌓기만 하고, 조회할 때 같은 검색(출발지, 목적지, 도착 시각의 KST 시:분)을 묶고, 삭제는 `user_id`를 NULL로 분리한다 (통계 보존).
- 자동 저장(`app/history/recording.py`): `GET /api/routes`가 `200`을 돌려줄 때만 응답을 보낸 뒤(FastAPI 백그라운드 작업) 저장한다. 응답 캐시 적중도 저장한다. 로그인 사용자의 같은 검색은 5분 안에 다시 저장하지 않는다. 세션 확인·저장 실패는 로그만 남기고 경로 응답에는 영향이 없다.
- 계약 테스트는 `favorites_backend`·`history_backend` fixture로 메모리와 MySQL(`-m mysql_live`)에서 같은 테스트를 돈다.

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
- 캐시: 응답은 캐시하지 않는다. 카카오모빌리티 약관상 길찾기 응답은 임시로도 캐시·저장할 수 없어, 같은 (출발지, 목적지, 출발시각, 경로 옵션) 조회도 매번 API를 부른다. 요청 하나 안에서 같은 출발시각을 두 번 묻지 않는 것은 엔진의 계산 과정일 뿐 요청 사이에 남지 않는다.
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

`POST /api/departure`, `GET /api/routes`(아래 "경로 비교"), `GET /api/places`(카카오 모드만), `GET /health`를 구현했다. 전체 명세(필드 규칙, 오류 표, 해민과 합의할 항목)는 `docs/api-spec.md`에 있다.

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


## 경로 비교 (`GET /api/routes`, F5)

`app/api/routes.py`(API, 장소 확정)와 `app/routing.py`의 `compare_routes`(비교 서비스)가 처리한다. 필드·오류·mock 동작 전체는 `docs/api-spec.md`의 `GET /api/routes`를 본다.

- 옵션은 `ROUTE_COMPARE_OPTIONS`(기본 추천, 최단시간, 최단거리, 무료도로)다. 옵션마다 `OptionRouteProvider`가 엔진(`DepartureSolver`)의 소요시간 조회를 그 옵션의 카카오 요약 조회로 바꾸고, 확정된 출발시각에 상세 경로를 한 번 받아 카드를 만든다. 엔진 코드는 그대로다.
- 같은 길로 확인된 옵션은 한 카드의 `options`에 합친다. 무료도로 결과에 통행료가 있으면 그 카드를 뺀다. 일부 옵션이 실패하면 그 카드만 빼고, 이유는 `app.api` 로거로 남긴다 (무료도로 없음은 INFO, 그 밖은 WARNING).
- 응답은 캐시하지 않는다 (카카오 약관). 같은 조건을 다시 검색해도 매번 카카오를 부른다. 응답에는 `Cache-Control: no-store`가 붙는다.
- mock 모드에서도 동작하지만 장소 검색이 없으므로 좌표 파라미터(`fromLat` 등)가 필요하다.

실측 (2026-11-12, `ROUTE_PROVIDER=kakao`, 김해시청 → 동의대학교, 다음 날 09:00 도착, 여유 10분, 좌표 전달):

| 카드 | options | name | 출발 | 소요 | 거리 | 통행료 |
| --- | --- | --- | --- | --- | --- | --- |
| recommend | recommend, time | 남해고속도로(순천-부산) 경유 | 08:19 | 31분 | 21.97km | 1,300원 |
| distance | distance | 관문대로 경유 | 08:05 | 45분 | 19.686km | 0원 |
| free | free | 관문대로 경유 | 08:09 | 41분 | 21.251km | 0원 |

카카오 호출은 18회였고, 같은 조건을 다시 부르면 캐시 HIT로 0회였다. 요청 하나의 최악은 옵션마다 요약 6회 + 상세 1~2회로 32회다 (`ROUTE_COMPARE_MAX_CALLS`로 조절). 일일 쿼터 5,000건이면 하루 약 270회 비교다. 상한을 너무 낮추면(Mock 출근 시간대 기준 3회) 출발시각을 찾지 못한 옵션이 빠진다.

### 프론트와 함께 실행

`app/main.py`는 API와 함께 `frontend/`를 같은 출처로 제공하므로 프론트 서버를 따로 띄우지 않아도 된다. 프론트는 `USE_MOCK_ROUTES=false`, `BASE_URL="/api"`를 쓴다. 프로젝트 루트에서:

```sh
ROUTE_PROVIDER=kakao backend/venv/Scripts/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8003 --no-access-log
```

macOS·Linux는 `backend/venv/bin/python`이다. `ROUTE_PROVIDER=kakao`는 이 프로세스에만 적용되고 `.env`의 값은 바꾸지 않는다. `.env`에 `KAKAO_REST_API_KEY`가 있어야 한다.

### 수동 실조회 점검 (`scripts/check_road_routes.py`)

두 구간(장소 이름 → 장소 검색 → 경로 비교)을 실제 카카오로 조회해 카드·제외 옵션·조회 수를 출력한다. **최대 약 70회** 호출하므로 필요할 때만 실행한다. 키는 출력하지 않는다.

```sh
cd backend && venv/Scripts/python scripts/check_road_routes.py
```

## 사이트 전체 이용 통계 (SFR-010)

1. [Google Analytics Data API 빠른 시작](https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart)에 따라 운영 Google Cloud 프로젝트에서 **Google Analytics Data API**(`analyticsdata.googleapis.com`)를 사용 설정한다.
2. GA4 관리에서 길잇 웹 데이터 스트림과 사이트 전용 속성을 확인하거나 만든다. 속성 보고 시간대를 **대한민국 / 서울**(`Asia/Seoul`)로 설정해 DB의 KST와 맞춘다. 속성 액세스 관리에서 서버 서비스 계정 이메일에 **뷰어** 권한을 부여한다. 실제 데이터 API 보고서의 `metadata.timeZone`을 확인한다.
3. 서버 환경 변수 또는 `backend/.env`(우선)·루트 `.env`에 숫자 속성 ID `GA4_PROPERTY_ID`와, GA4 보고서에서 확인한 최초 수집일 `GA4_COLLECTION_START_DATE`(`YYYY-MM-DD`, KST)를 설정한다. 누적 조회 범위는 이 날짜부터 조회일(오늘)까지이며, 신규 태그는 이전 방문을 수집하지 않는다. 오늘 데이터는 GA4 처리 상태에 따라 갱신된다.
4. 서버에 `requirements.txt`를 설치한다. Google 인증은 `analytics.readonly` 범위의 [ADC](https://docs.cloud.google.com/docs/authentication/application-default-credentials)를 사용한다. 서버에 연결된 서비스 계정 또는 워크로드 ID 연동을 사용할 수 있다. ADC 파일을 사용하면 `GOOGLE_APPLICATION_CREDENTIALS`를 서버 전용 파일 경로로 지정한다. 연결 서비스 계정처럼 파일을 쓰지 않는 배포에서는 해당 변수를 설정에서 생략한다. 키 본문과 토큰은 서버의 비밀 저장소에서 관리한다.
5. 수집을 켜기 전에 웹 스트림의 **향상된 측정**을 끄고, 자동 페이지뷰를 보내는 중복 태그/GTM 설정과 사용자 제공 데이터 수집 설정이 없는지 확인한다. 서버 환경변수 `GA4_MEASUREMENT_ID`에 웹 스트림 공개 측정 ID(`G-…`)를 설정하고 서버를 다시 시작한다 (`GET /api/config`로 프론트에 전달. `frontend/js/config.js`의 같은 이름은 로컬 개발용 대체값). 공통 헤더가 알려진 사이트 페이지마다 순수 경로로 페이지뷰를 한 번 전송한다. [Google 태그 페이지뷰 설정](https://developers.google.com/analytics/devguides/collection/ga4/views)
6. GA4에서 홈 및 공유 결과 링크의 페이지뷰가 한 번씩 수집되고 전송 데이터에 URL 쿼리·해시·원래 referrer가 없는지 확인한다. 로그인한 브라우저에서 `GET /api/stats` 응답의 기간과 방문자 값을 GA4 보고서와 대조한다. 운영의 검색 기록은 기존 `AUTH_STORE=mysql` 및 `DB_*` 설정을 사용한다. 운영 계정이 `search_history`를 읽을 수 있는지 확인하고, 별도 MySQL 테스트 DB에서 `python -m pytest -m mysql_live tests/test_stats.py`로 날짜 경계와 순위를 검증한다.

GA4 환경 변수나 자격 증명이 없어도 서버는 기동하고 기존 기능은 동일하게 작동한다. 브라우저 측정 ID는 빈 값이면 수집하지 않는다. 메모리 저장소는 로컬에서 집계 흐름을 확인할 수 있으나 서버 재시작 시 기록이 사라진다. 운영에서 비로그인 검색까지 집계하려면 성공한 비로그인 검색을 기록할 별도 수집 범위와 보관 정책이 필요하다. 현재 순위는 기존 DB를 사용할 수 있으므로 GA4 맞춤 검색 이벤트를 추가하지 않았다.
