# 길잇 API 명세 (가안)

응답 필드명은 `frontend/js/mock/*.json`과 같다. 필드를 바꾸면 mock과 이 문서를 함께 고친다.
DB 스키마는 `db/schema.sql`, 테이블 설명은 `db/README.md`에 있다. API 필드와 DB 컬럼 이름이 다른 곳은 서버가 매핑한다 (아래 "DB 매핑").

## 목록

| 메서드 | 경로 | 설명 | 로그인 | 프론트 함수 (`api.js`) | mock |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/places?q=` | 장소 검색 (카카오 모드 구현) | 불필요 | `searchPlaces` | `places.json` |
| POST | `/api/departure` | 권장 출발시각 계산 (**구현됨**) | 불필요 | 없음 | - |
| GET | `/api/routes?from=&to=&arrive=&buffer=` | 경로 비교: 옵션별 권장 출발시각·소요시간·거리·통행료 (**구현됨**) | 불필요 | `getRoutes` | `routes.json` |
| GET | `/api/routes/graph?from=&to=&arrive=` | 출발시각별 소요시간 | 불필요 | `getRouteGraph` | `routeGraph.json` |
| POST | `/api/auth/signup` | 이메일 회원가입 | 불필요 | `signup` | localStorage |
| POST | `/api/auth/login` | 이메일 로그인 | 불필요 | `loginWithEmail` | localStorage |
| POST | `/api/auth/logout` | 로그아웃 | 불필요 | `logoutSession` | 호출 안 함 |
| GET | `/api/auth/me` | 내 정보 | **필요** | 없음 | - |
| GET | `/api/favorites` | 즐겨찾기 목록 | **필요** | `getFavorites` | `favorites.json` |
| POST | `/api/favorites` | 즐겨찾기 추가 | **필요** | `addFavorite` | localStorage |
| PATCH | `/api/favorites?id=` | 즐겨찾기 수정 | **필요** | 없음 | - |
| DELETE | `/api/favorites?id=` | 즐겨찾기 삭제 | **필요** | `removeFavorite` | localStorage |
| GET | `/api/history` | 내 검색 기록 | **필요** | `getHistory` | `history.json` |
| POST | `/api/history` | 검색 기록 저장 | 불필요 | 없음 | - |
| GET | `/api/stats` | 이용 통계 | **필요** | `getStats` | `stats.json` |
| POST | `/api/visit` | 방문 로그 기록 | 불필요 | 없음 | - |
| GET | `/health` | 서버 상태 확인 (**구현됨**) | 불필요 | - | - |

"프론트 함수 없음"은 서버에 먼저 만들고 프론트에서 나중에 연결할 API다. **구현됨**은 `backend/app/api/`에 있고 `/docs`(Swagger)에서 시험할 수 있다. 나머지는 가안이다.

**[해민과 합의 필요]** 표시가 붙은 항목은 맨 아래 "해민과 정할 것"에 모아 두었다.

## 공통 형식

- 시각: ISO 8601, 한국 시간 (`2026-11-02T08:50:00+09:00`). DB에도 KST로 저장한다.
- 금액: 원, 거리: km, 시간: 분, 좌표: WGS84 십진수 (`lat`, `lng`)
- `id`: 모든 리소스의 `id`는 **문자열**로 내려준다 (DB의 BIGINT를 `"12"`처럼). 프론트는 `id`를 문자열로 비교하고, 큰 정수의 JS 정밀도 문제도 피한다.
- `from`, `to`: 장소 이름 (`김해시청`)
- `buffer`: 도착 희망 시각보다 일찍 도착하려는 여유 시간(분)
- 요청 본문은 JSON (`Content-Type: application/json`)

### 인증

로그인에 성공하면 서버가 세션을 만들고 `HttpOnly; Secure; SameSite=Lax` 쿠키로 세션 ID를 내려준다. 소셜 로그인도 같은 세션 방식을 쓴다. 프론트는 같은 출처로 요청하므로 쿠키가 자동으로 실린다. 프론트는 응답 본문의 사용자 정보를 화면 표시용으로만 `localStorage`(`gilit:user`)에 저장하고, 토큰은 다루지 않는다.

"로그인 필요" API는 세션이 없거나 만료되면 `401` "로그인이 필요합니다."를 돌려준다. 프론트도 해당 화면(`js/guard.js`의 `PROTECTED_PATHS`)을 로그인 모달로 막지만 화면 흐름용일 뿐이므로, 서버가 반드시 직접 검사한다.

### 오류

오류 응답 본문은 `{ "message": "..." }`이다. 프론트는 4xx의 `message`를 그대로 화면에 보여 주고, 5xx와 네트워크 오류는 "잠시 후 다시 시도해 주세요."로 바꾼다. 그래서 4xx `message`는 사용자에게 보여 줄 한국어 문장으로 쓰고, 내부 정보(SQL, 스택)를 넣지 않는다.

| 코드 | 언제 | `message` 예 |
| --- | --- | --- |
| `400` | 입력값 검증 실패 (필수값, 형식, 범위) | 올바른 이메일 형식이 아닙니다. |
| `401` | 로그인 필요 API에 세션 없음 | 로그인이 필요합니다. |
| `401` | 이메일 로그인 실패 | 이메일 또는 비밀번호가 올바르지 않습니다. |
| `404` | 리소스가 없거나 내 것이 아님, 없는 경로 | 찾을 수 없습니다. |
| `405` | 허용되지 않은 메서드 | 허용되지 않은 요청 방식입니다. |
| `409` | 이메일 중복 등 충돌 | 이미 가입된 이메일입니다. |
| `422` | 입력은 올바르지만 답을 낼 수 없음 (경로 없음, 제시간 도착 불가) | 경로를 찾을 수 없습니다 |
| `429` | 요청 횟수 제한 초과 | 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요. |
| `500` | 서버 오류 | 잠시 후 다시 시도해 주세요. |
| `502` | 외부 길찾기 API 오류 (인증, 거부, 연결 실패, 응답 이상) | 길찾기 정보를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요. |
| `503` | 외부 길찾기 API 호출 한도 초과 | 길찾기 API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요. |
| `504` | 외부 길찾기 API 응답 시간 초과 | 길찾기 서버 응답이 늦습니다. 잠시 후 다시 시도해 주세요. |

FastAPI 기본값인 `422` + `detail` 목록은 쓰지 않는다. 입력 검증 실패도 `400` + `message` 하나로 바꿔 보낸다 (`backend/app/api/errors.py`). 5xx의 원인(외부 API 응답 문구, HTTP 코드 등)은 응답에 넣지 않고 서버 로그에만 남긴다.

### CORS

허용 출처는 서버 환경변수 `CORS_ORIGINS`(쉼표 구분)로 정한다. 기본값은 로컬 개발용 `http://localhost:5500`, `http://127.0.0.1:5500`(VS Code Live Server)이다. 세션 쿠키를 보내야 하므로 `allow_credentials`를 켜고, `*`(모든 출처)는 쓸 수 없다. 허용 메서드는 `GET`, `POST`, `PATCH`, `DELETE`, 허용 헤더는 `Content-Type`이다.

다른 사용자의 즐겨찾기처럼 권한이 없는 리소스도 `403` 대신 `404`로 응답해 존재 여부를 드러내지 않는다.

### 보안 규칙

- 모든 쿼리는 파라미터 바인딩(prepared statement)으로 실행한다. 문자열을 이어 붙여 SQL을 만들지 않는다.
- 비밀번호는 bcrypt(cost 12 이상)로 해시해 `users.password_hash`에만 저장한다. 평문 비밀번호를 DB, 로그, 오류 응답에 남기지 않는다. 요청 본문 로깅을 켠다면 `password` 필드를 가린다.
- 로그인 시도 횟수 제한(예: IP·이메일별 분당 5회)을 두고, 넘으면 `429`를 돌려준다.

## 목업 동작

`USE_MOCK = true`이면 `api.js`가 서버 역할 일부를 대신한다. 실제 서버는 아래 값을 직접 계산해서 돌려준다.

- 경로: `arriveTime`은 `arrive - buffer`, `departTime`은 `arriveTime - durationMin`
- 그래프: 마지막 출발시각이 `arrive`가 되도록 시각을 옮긴다
- 기록·통계: 가장 최근 날짜가 오늘이 되도록 날짜를 옮긴다
- 장소 검색: 앞뒤 공백을 제거한 `q`가 `name` 또는 `address`에 포함된 항목을 돌려준다
- 회원가입·로그인: 계정을 `localStorage`의 `gilit:mock:users`에 저장한다. 비밀번호는 평문이 아닌 SHA-256 값으로 두지만, 브라우저 안의 흉내일 뿐이다. 서버는 bcrypt를 쓴다.

## 길찾기 (로그인 불필요)

### GET /api/places?q=

백엔드가 카카오 로컬 키워드 검색을 중계한다. 키워드 결과가 없으면 주소 검색을 시도한다. REST 키는 서버에서만 관리한다.

요청: `GET /api/places?q=김해시청`

`q`는 장소명 또는 주소 검색어다. 프론트는 앞뒤 공백을 제거해 전달한다. 응답은 장소명(`name`)과 주소(`address`)를 포함한 배열이며, 결과가 없으면 빈 배열이다. 목업은 제공된 예시 장소 범위 안에서 이름·주소 부분 일치로 검색한다. 실제 검색은 기존 `/api/places` 계약을 사용하며 백엔드 구현은 별도 범위다.

```json
[
  { "id": "place-1", "name": "김해시청", "address": "경상남도 김해시", "lat": 35.2285, "lng": 128.8894 }
]
```

### POST /api/departure (구현됨)

로그인: 불필요. 구현: `backend/app/api/departure.py`, 엔진: `backend/app/departure/`

장소 검색 결과의 좌표로 권장 출발시각 하나를 계산한다. 목표 도착시각(`arrive_at - buffer_min`)까지 도착하는 가장 늦은 출발시각을 분 단위로 찾는다. 경로 목록·통행료·경로선은 돌려주지 않는다 (그건 아래 `GET /api/routes`). 추천 경로 기준이며, `GET /api/routes`의 `recommend` 카드와 같은 카카오 조회 캐시를 쓴다.

**[해민과 합의 필요]** 이 API는 요청·응답 필드를 snake_case로 쓴다. 다른 API와 프론트는 camelCase(`departTime`)다. 아래 "해민과 정할 것" 참고.

요청:

```json
{
  "origin": { "name": "김해시청", "lat": 35.2285, "lng": 128.8894 },
  "destination": { "name": "동의대학교", "lat": 35.1441, "lng": 129.0336 },
  "arrive_at": "2026-11-06T09:00:00+09:00",
  "buffer_min": 10,
  "travel_mode": "car"
}
```

| 필드 | 필수 | 규칙 | 오류 `message` (400) |
| --- | --- | --- | --- |
| `origin`, `destination` | 예 | `name`, `lat`, `lng`가 있는 객체 | 출발지가 필요합니다. / 출발지는 name, lat, lng가 있는 객체여야 합니다. |
| `*.name` | 예 | 앞뒤 공백 제거 후 1~100자 | 출발지 장소 이름은 1~100자로 입력해 주세요. |
| `*.lat` | 예 | -90 ~ 90 | 출발지 위도는 -90~90 사이의 숫자여야 합니다. |
| `*.lng` | 예 | -180 ~ 180 | 목적지 경도는 -180~180 사이의 숫자여야 합니다. |
| `arrive_at` | 예 | ISO 8601 문자열. 시간대가 없으면 한국 시간으로 본다. 지금보다 미래 | 도착 희망 시각은 ISO 8601 형식이어야 합니다 (예: 2026-11-06T09:00:00+09:00). / 도착 희망 시각이 이미 지났습니다. |
| `buffer_min` | 아니오 (기본 0) | `0`, `5`, `10`, `15` 중 하나인 정수 (`"10"`, `true`는 거부) | 여유시간은 0, 5, 10, 15분 중 하나여야 합니다. |
| `travel_mode` | 아니오 (기본 `car`) | `car` 또는 `transit`. 카카오 데이터는 `car`만 된다 | 이동수단은 car 또는 transit이어야 합니다. |

응답: `200`

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

| 필드 | 설명 |
| --- | --- |
| `recommended_depart_at` | 권장 출발시각 (한국 시간, 분 단위) |
| `duration_min` | 권장 출발시각에 출발했을 때의 예상 소요시간(분, 올림) |
| `expected_arrive_at` | 권장 출발시각에 출발했을 때의 예상 도착시각 (초 단위) |
| `desired_arrive_at` | 요청한 도착 희망 시각 (한국 시간으로 바꿔 돌려준다) |
| `buffer_min` | 요청한 여유시간 |
| `buffer_applied` | 여유시간을 반영했는지. 요청이 0분이거나, 지금 출발해도 여유를 둘 수 없으면 `false` (이때는 여유 없이 계산한 결과다) |
| `converged` | `false`면 조회 한도(`DEPARTURE_MAX_CALLS`, 기본 8회)에 걸려 확인된 시각 중 가장 늦은 것을 돌려준 것이다. 실제 답보다 이르거나 같으므로 늦지 않는다 |
| `api_calls` | 이번 계산의 소요시간 조회 횟수. 서버 캐시 적중도 센다 |
| `data_source` | `mock`(가짜 데이터) 또는 `kakao`(카카오모빌리티 미래 운행 정보). 서버 환경변수 `ROUTE_PROVIDER` |

오류:

| 코드 | 언제 | `message` |
| --- | --- | --- |
| `400` | 위 표의 입력 오류 | 표 참고 |
| `400` | 도착 희망 시각이 지남 | 도착 희망 시각이 이미 지났습니다. |
| `400` | `transit`인데 데이터 출처가 카카오 | 대중교통은 아직 지원하지 않습니다. |
| `422` | 지금(또는 탐색 구간 6시간) 안에 출발해도 늦음 | 지금 출발해도 도착 희망 시각까지 도착할 수 없습니다. |
| `422` | 경로 없음 (출발지·도착지가 5m 이내, 주변 도로 없음 등) | 경로를 찾을 수 없습니다: (카카오 안내 문구) (result_code=104) |
| `422` | 조회 한도 안에서 제시간 도착 시각을 하나도 확인하지 못함 | 출발시각을 계산하지 못했습니다. 잠시 후 다시 시도해 주세요. |
| `502` | 카카오 인증 실패, 요청 거부, 연결 실패, 응답 형식 이상 | 길찾기 정보를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요. |
| `503` | 카카오 호출 한도 초과 | 길찾기 API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요. |
| `504` | 카카오 응답 시간 초과 (10초) | 길찾기 서버 응답이 늦습니다. 잠시 후 다시 시도해 주세요. |

서버 동작:

- 카카오 어댑터는 서버를 띄울 때 하나만 만들어 모든 요청이 함께 쓴다. 같은 (출발지, 목적지, 출발시각(분), 이동수단) 조회는 메모리 캐시로 다시 부르지 않고, 캐시는 `ROUTE_CACHE_TTL_SEC`(기본 600초)이 지나면 버린다.
- 카카오 일일 쿼터는 5,000건이다. 요청 하나당 최대 8회라 하루 약 625회 계산까지 된다.
- 이 API는 `search_history`에 저장하지 않는다. 기록 저장은 `POST /api/history`다 (DB 연결 후 구현).

### GET /health (구현됨)

로그인: 불필요. 배포·로드밸런서 확인용이고 외부 API를 부르지 않는다.

응답: `200` `{ "status": "ok" }`

### GET /api/routes (구현됨, 경로 비교 F5)

로그인: 불필요. 구현: `backend/app/api/routes.py`(API), `backend/app/routing.py`의 `compare_routes`(비교 서비스), 엔진: `backend/app/departure/`

경로 옵션마다 출발시각 역산 엔진을 돌려, 옵션별 권장 출발시각·예상 도착시각·소요시간·거리·통행료·경로선을 카드 배열로 돌려준다. 필드는 camelCase다 (프론트 `getRoutes`, `js/mock/routes.json`).

요청:

```
GET /api/routes?from=김해시청&to=동의대학교&arrive=2026-11-13T09:00:00%2B09:00&buffer=10
               &fromLat=35.2285&fromLng=128.8894&toLat=35.1441&toLng=129.0336
```

| 파라미터 | 필수 | 규칙 | 오류 `message` (400) |
| --- | --- | --- | --- |
| `from`, `to` | 예 | 앞뒤 공백 제거 후 1~100자, 서로 달라야 한다 | 출발지가 필요합니다. / 출발지는 1~100자로 입력해 주세요. / 출발지와 다른 목적지를 입력해 주세요. |
| `arrive` | 예 | ISO 8601. 시간대가 없으면 한국 시간. `+`는 `%2B`로 보낸다. 지금보다 미래 | 도착 희망 시각은 ISO 8601 형식이어야 합니다 (예: 2026-11-06T09:00:00+09:00). / 도착 희망 시각이 이미 지났습니다. |
| `buffer` | 아니오 (기본 0) | `0`, `5`, `10`, `15` | 여유시간은 0, 5, 10, 15분 중 하나여야 합니다. |
| `fromLat`, `fromLng` | 아니오 | 함께 보낸다. 위도 -90~90, 경도 -180~180, NaN 불가 | 출발지 위도와 경도를 함께 보내 주세요. / 출발지 위도는 -90~90 사이의 숫자여야 합니다. |
| `toLat`, `toLng` | 아니오 | 위와 같다 | 목적지 위도와 경도를 함께 보내 주세요. / 목적지 경도는 -180~180 사이의 숫자여야 합니다. |

좌표가 있으면 그 좌표를 쓴다. 좌표가 없으면(좌표가 생기기 전의 공유 링크) 서버가 장소 검색으로 이름을 하나의 장소로 확정한다. 확정하지 못하면 422다.

응답: `200` 카드 배열. 카드 순서는 서버 설정 `ROUTE_COMPARE_OPTIONS` 순서(기본 추천, 최단시간, 최단거리, 무료도로)이고 **1~4개**다.

```json
[
  {
    "id": "recommend",
    "options": ["recommend", "time"],
    "label": "추천",
    "name": "남해고속도로(순천-부산) 경유",
    "departTime": "2026-11-13T08:19:00+09:00",
    "arriveTime": "2026-11-13T08:49:10+09:00",
    "durationMin": 31,
    "distanceKm": 21.97,
    "toll": 1300,
    "fuel": null,
    "bufferApplied": true,
    "converged": true,
    "dataSource": "kakao",
    "path": [
      { "lat": 35.2285, "lng": 128.8894 },
      { "lat": 35.1441, "lng": 129.0336 }
    ],
    "aiSummary": { "title": "추천 경로", "text": "소요시간·거리·통행료·경로선은 같은 상세 길찾기 응답 기준입니다." }
  }
]
```

위 값은 2026-11-12에 실제 카카오로 조회한 첫 카드다. `path`는 실제로 수백 개 좌표이고 여기서는 줄였다.

| 필드 | 설명 |
| --- | --- |
| `id` | 카드를 만든 경로 옵션: `recommend`(추천), `time`(최단시간), `distance`(최단거리), `free`(무료도로) |
| `options` | 이 카드에 합쳐진 옵션. 같은 길로 확인된 옵션은 앞 카드에 합친다 (예: 추천과 최단시간이 같은 길이면 `["recommend", "time"]`, 이때 `time` 카드는 따로 없다) |
| `label` | `id`의 이름: 추천, 최단시간, 최단거리, 무료도로 |
| `name` | 경로에서 가장 긴 도로 이름 + " 경유". 도로 이름이 없으면 `label` |
| `departTime` | 권장 출발시각 (한국 시간, 분 단위) |
| `arriveTime` | 예상 도착시각 = `departTime` + 상세 경로 소요시간 (초 단위) |
| `durationMin` | 예상 소요시간(분, 올림) |
| `distanceKm` | 거리(km) |
| `toll` | 통행료(원). 카카오가 주지 않으면 `null` (화면은 "미제공") |
| `fuel` | 예상 유류비. 아직 제공하지 않아 항상 `null` |
| `bufferApplied` | 여유시간을 반영했는지. 요청이 0분이거나 지금 출발해도 여유를 둘 수 없으면 `false` (여유 없이 계산한 결과) |
| `converged` | `false`면 조회 한도에 걸려 확인된 시각 중 가장 늦은 것을 돌려준 것. 실제 답보다 이르거나 같아서 늦지 않는다 |
| `dataSource` | `kakao` 또는 `mock` (서버 `ROUTE_PROVIDER`) |
| `path` | 지도에 그릴 경로 좌표 `[{lat, lng}]`. 두 개 이상 |
| `aiSummary` | 화면 호환용 고정 안내 `{title, text}`. AI 요약은 아직 없다 |

`durationMin`, `distanceKm`, `toll`, `path`, `name`, `arriveTime`은 모두 **같은 상세 경로 응답 하나**에서 나온다. 다른 옵션이나 다른 출발시각의 값을 섞지 않는다.

오류:

| 코드 | 언제 | `message` |
| --- | --- | --- |
| `400` | 위 표의 입력 오류, 지난 도착 희망 시각 | 표 참고 |
| `422` | 이름만 온 장소를 하나로 확정하지 못함 (mock 모드는 장소 검색이 없어 항상 이 경우) | 장소를 하나로 확인할 수 없어요. 정확한 장소명이나 주소로 다시 검색해 주세요. |
| `422` | 모든 옵션이 실패 (첫 옵션의 오류를 돌려준다) | 지금 출발해도 도착 희망 시각까지 도착할 수 없습니다. / 해당 조건으로 자동차 경로를 찾을 수 없습니다. 등 |
| `502` | 카카오 인증 실패, 요청 거부, 연결 실패, 응답 형식 이상 | 길찾기 정보를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요. |
| `503` | 카카오 호출 한도 초과 | 길찾기 API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요. |
| `504` | 카카오 응답 시간 초과 | 길찾기 서버 응답이 늦습니다. 잠시 후 다시 시도해 주세요. |

일부 옵션만 실패하면(경로 없음, 제시간 도착 불가, 무료도로인데 통행료가 있음) **그 카드만 빼고 200**을 돌려준다. 빠진 옵션과 이유는 응답에 넣지 않고 서버 로그(`app.api` 로거)에만 남긴다. 통행료 없는 길이 없는 경우는 INFO, 그 밖은 WARNING이다. 공급자 오류(5xx)는 남은 옵션을 부르지 않고 바로 돌려준다. 실제 조회가 실패해도 예시 경로로 대체하지 않는다.

서버 동작:

- 옵션마다 역산 엔진이 요약 조회(`summary=true`, 경로 좌표 없음)로 출발시각을 찾고(옵션당 최대 `ROUTE_COMPARE_MAX_CALLS`, 기본 6회), 확정된 출발시각에 상세 경로(`road_details=true`)를 한 번 받아 카드를 만든다.
- 중복: 엔진의 첫 조회(같은 출발시각의 소요시간·거리·통행료)가 이미 만든 카드와 같으면 탐색을 멈추고 상세 좌표 1회로 같은 길인지 확인한다. 같으면 앞 카드의 `options`에 합친다. 첫 조회는 달라도 상세 좌표가 같으면 역시 합친다.
- 무료도로(`free`)는 카카오 `avoid=toll`이다. 결과에 통행료가 있으면 카드에서 뺀다.
- 상세 경로의 소요시간이 요약과 다르면 상세 값 기준으로 출발시각을 앞당긴다 (늦게 안내하지 않는다). 더 짧으면 그대로 둔다.
- 요청당 카카오 호출: 옵션마다 요약 최대 6회 + 상세 1~2회, 최악 32회. 2026-11-12 실측(김해시청 → 동의대학교, 다음 날 09:00, 여유 10분)은 카드 3개(추천·최단시간이 합쳐짐), **18회**였다. 일일 쿼터 5,000건이면 하루 약 270회 비교다.
- 캐시: 카카오 요약 조회는 Provider 캐시(`ROUTE_CACHE_TTL_SEC`, 기본 600초, 옵션별)를 쓴다. `/api/departure`와 추천 옵션은 같은 캐시를 쓴다. 성공한 전체 응답은 같은 시간 동안 프로세스 메모리에 최대 64건 저장한다. 키는 출발지·목적지 이름과 좌표, 도착 희망 시각, 여유시간이고, 응답 헤더 `X-Gilit-Route-Cache: HIT|MISS`로 확인한다. 출발시각이 지난 결과·실패는 재사용하지 않는다. 캐시는 서버 재시작 시 사라지고 프로세스 간 공유하지 않는다. 응답에는 `Cache-Control: no-store`가 붙는다.

mock 모드 (`ROUTE_PROVIDER=mock`):

- 카카오 없이 동작한다. `dataSource`는 `mock`이고, 옵션마다 거리·속도·혼잡·통행료를 다르게 둔 가짜 데이터(`MockRouteProvider`)로 카드 4개를 만든다. 경로선은 출발지와 목적지를 잇는 가짜 곡선이고, `name`은 "가상 고속도로 경유"처럼 나온다. 실제 교통 정보와 무관하다.
- mock 모드에는 장소 검색이 없으므로 **좌표 파라미터가 필요하다**. 이름만 오면 422다. `GET /api/places`는 mock 모드에서 502다.
- 프론트 `USE_MOCK_ROUTES=true`일 때는 서버를 부르지 않고 `js/mock/routes.json`을 쓴다. 이 둘은 다른 mock이다.

### GET /api/routes/graph?from=&to=&arrive=

실제 API는 미구현이다. 실제 경로 모드에서는 프론트가 이 요청을 보내지 않고 차트를 숨긴다. 예시 모드는 기존 그래프를 유지한다.

요청: `GET /api/routes/graph?from=김해시청&to=동의대학교&arrive=2026-11-02T09:00:00%2B09:00`

경로별로 출발시각에 따른 소요시간을 돌려준다. `routeId`는 `/api/routes`의 `id`다.

```json
[
  {
    "routeId": "route-1",
    "points": [
      { "departTime": "2026-11-02T07:30:00+09:00", "durationMin": 45 },
      { "departTime": "2026-11-02T07:40:00+09:00", "durationMin": 48 }
    ]
  }
]
```

## 회원 (`users`, `social_accounts`)

### 사용자 객체

회원 API가 돌려주는 사용자 정보다.

```json
{ "id": "1", "name": "길잇", "email": "user@example.com", "provider": "email" }
```

- `name`: `users.nickname`
- `provider`: `users.password_hash`가 있으면 `email`, 없으면 연결된 소셜 계정의 `social_accounts.provider` (`google` | `kakao`)

### 검증 규칙

프론트(`js/components/authModal.js`)도 같은 규칙으로 먼저 검사하지만, 서버가 다시 검사한다.

| 필드 | 규칙 | 오류 `message` |
| --- | --- | --- |
| `name` | 앞뒤 공백 제거 후 2~20자 | 이름은 2~20자로 입력해 주세요. |
| `email` | 앞뒤 공백 제거·소문자 변환 후 이메일 형식, 254자 이하 | 올바른 이메일 형식이 아닙니다. |
| `password` | 8~64자, 영문과 숫자를 모두 포함, UTF-8 72바이트 이하 (bcrypt 한계) | 비밀번호는 영문과 숫자를 포함해 8~64자로 입력해 주세요. |
| `agreeTerms`, `agreePrivacy` | 둘 다 `true` | 필수 약관에 모두 동의해 주세요. |

### 같은 이메일의 소셜 계정 처리

계정은 이메일 하나당 하나다 (`users.email` UNIQUE). 계정을 자동으로 합치지 않는다.

- 이메일 회원가입 시 같은 이메일이 이미 있으면 (소셜 가입이어도) `409` "이미 가입된 이메일입니다."를 돌려준다. 가입 화면은 중복 여부를 알려 줄 수밖에 없으므로 이 응답만 예외로 둔다.
- 소셜 로그인 시 `social_accounts`의 `(provider, provider_user_id)`로 사용자를 찾는다. 처음 로그인하는데 그 이메일의 `users` 행이 이미 있으면 새 계정을 만들지 않고 `409` "이미 가입된 이메일입니다. 기존에 쓰던 방법으로 로그인해 주세요."를 돌려준다.
- 이유: 카카오는 이메일 인증 여부가 보장되지 않아, 이메일만 보고 합치면 남의 계정에 로그인할 수 있다. 계정 연결은 나중에 "내 정보"에서 로그인한 상태로만 제공한다.
- 소셜 첫 로그인으로 가입할 때 `users` 행(`password_hash` NULL)과 `social_accounts` 행을 한 트랜잭션으로 만든다. 약관 동의를 받은 시각을 `agreed_at`에 넣는다.

### POST /api/auth/signup

로그인: 불필요

요청:

```json
{ "name": "길잇", "email": "user@example.com", "password": "gilit1234", "agreeTerms": true, "agreePrivacy": true }
```

응답: `201` + 사용자 객체. 가입만 하고 로그인 세션은 만들지 않는다. 프론트는 로그인 화면으로 돌아가 이메일을 채워 둔다.

```json
{ "id": "1", "name": "길잇", "email": "user@example.com", "provider": "email" }
```

DB: `users`에 `email`(소문자), `password_hash`(bcrypt), `nickname`(= `name`), `agreed_at`(= 지금)을 넣는다. 중복 검사는 먼저 조회하지 말고 INSERT에서 UNIQUE 위반(MySQL 오류 1062)을 받아 `409`로 바꾼다. 동시에 가입해도 하나만 성공한다.

오류: `400` 검증 실패 (위 표의 `message`), `409` "이미 가입된 이메일입니다."

### POST /api/auth/login

로그인: 불필요

요청:

```json
{ "email": "user@example.com", "password": "gilit1234" }
```

응답: `200` + 세션 쿠키 + 사용자 객체. `users.last_login_at`을 지금 시각으로 갱신한다.

오류: `401` "이메일 또는 비밀번호가 올바르지 않습니다." 계정이 없을 때, 소셜 전용 계정(`password_hash` NULL)일 때, 비밀번호가 틀렸을 때 모두 같은 응답이다. 계정이 없거나 소셜 전용일 때도 고정된 더미 해시로 bcrypt 비교를 한 번 수행해 응답 시간으로 계정 존재가 드러나지 않게 한다.

### POST /api/auth/logout

로그인: 불필요 (세션이 없어도 `204`)

세션을 지우고 쿠키를 만료시킨다. 응답: `204` (본문 없음)

### GET /api/auth/me

로그인: **필요**

새로고침 등으로 서버 세션 기준의 로그인 상태를 확인할 때 쓴다. 응답: `200` + 사용자 객체

오류: `401` "로그인이 필요합니다."

## 즐겨찾기 (`favorite_places`, 로그인 필요)

모든 즐겨찾기 API는 세션의 사용자 것만 다룬다. 세션이 없으면 `401`, 다른 사용자의 `id`는 `404`다.

필드 매핑: `name` = `place_name`, `type` = `label`, `address` = `address`, `lat`·`lng` = 같은 이름. `type`은 `집`, `학교`, `회사`, `기타` 중 하나다.

### GET /api/favorites

최근에 추가한 것이 마지막에 오도록 `created_at` 오름차순으로 돌려준다.

```json
[
  { "id": "1", "name": "집", "address": "경상남도 김해시 내외중앙로 47", "type": "집" }
]
```

### POST /api/favorites

요청:

```json
{ "name": "집", "address": "경상남도 김해시 내외중앙로 47", "type": "집", "lat": 35.2285, "lng": 128.8894 }
```

- `name`: 1~100자, `address`: 255자 이하 (생략 가능), `type`: 위 4개 중 하나
- `lat`, `lng`: DB에서 필수다. **지금 프론트(`addPlaceModal.js`)는 좌표를 보내지 않으므로**, 요청에 좌표가 없으면 서버가 `address`(없으면 `name`)로 카카오 로컬 API를 검색해 첫 결과의 좌표를 넣는다. 찾지 못하면 `400` "장소 위치를 찾을 수 없습니다."

응답: `201`

```json
{ "id": "1", "name": "집", "address": "경상남도 김해시 내외중앙로 47", "type": "집" }
```

### PATCH /api/favorites?id=

요청: `PATCH /api/favorites?id=1`. 바꿀 필드만 보낸다. 규칙은 POST와 같다. `address`를 바꾸고 좌표를 보내지 않으면 서버가 좌표를 다시 찾는다.

```json
{ "name": "우리 집", "type": "집" }
```

응답: `200` + 수정된 즐겨찾기. 오류: `400`, `404`

### DELETE /api/favorites?id=

요청: `DELETE /api/favorites?id=1`

응답: `204` (본문 없음). 오류: `404`

## 검색 기록 (`search_history`)

### GET /api/history

로그인: **필요**

내 검색 기록을 최신순으로 돌려준다 (`user_id = 세션 사용자`, `created_at` 내림차순, 인덱스 `idx_history_user_created`). `limit` 쿼리로 개수를 정한다 (기본 20, 최대 100).

```json
[
  { "id": "1", "from": "김해시청", "to": "동의대학교", "arriveTime": "2026-11-02T09:00:00+09:00" }
]
```

매핑: `from` = `origin_name`, `to` = `dest_name`, `arriveTime` = `arrive_at`

### POST /api/history

로그인: 불필요. 로그인 상태면 `user_id`에 세션 사용자를, 아니면 NULL을 넣는다. 비로그인 검색도 인기 출발지·목적지 통계에 쓴다.

길찾기 결과를 보여 준 뒤 한 번 호출한다.

```json
{
  "from": { "name": "김해시청", "lat": 35.2285, "lng": 128.8894 },
  "to": { "name": "동의대학교", "lat": 35.1441, "lng": 129.0336 },
  "arrive": "2026-11-02T09:00:00+09:00",
  "buffer": 10,
  "departTime": "2026-11-02T08:12:00+09:00",
  "travelMode": "car",
  "aiSummary": "남해고속도로 경유가 가장 안정적이에요"
}
```

- `from`, `to`: `name` 100자 이하, 좌표 생략 가능
- `arrive`: 필수. `buffer`: 0 이상 정수, 생략하면 0
- `departTime`, `aiSummary`: 생략 가능. `travelMode`: `car` | `transit`, 생략하면 `car`

매핑: `origin_*`·`dest_*` = `from`·`to`, `arrive_at` = `arrive`, `buffer_min` = `buffer`, `recommended_depart_at` = `departTime`, `travel_mode` = `travelMode`, `ai_summary` = `aiSummary`

응답: `201` `{ "id": "1" }`. 오류: `400`

## 이용 통계

### GET /api/stats

로그인: **필요**

`dailyVisitors`는 최근 7일이고 마지막 항목이 오늘이다. `weekChangePct`는 최근 7일과 그 전 7일의 방문자 증감률(%)이다. 오늘 방문자, 어제 대비 증감, 주간 합계, 방문자당 검색 수는 프론트에서 계산한다.

```json
{
  "totalVisitors": 48290,
  "monthVisitors": 7428,
  "totalSearches": 126842,
  "weekChangePct": 8.2,
  "dailyVisitors": [
    { "date": "2026-11-02", "count": 338 }
  ],
  "popularOrigins": [
    { "name": "김해시청", "count": 1284 }
  ],
  "popularDestinations": [
    { "name": "동의대학교", "count": 1498 }
  ]
}
```

계산: 방문자는 `visit_logs.session_id`의 서로 다른 값 개수, 검색 수는 `search_history` 행 수, 인기 출발지·목적지는 `origin_name`·`dest_name`별 개수 상위 5개다. 방문이 없는 날은 `count: 0`으로 채운다. 쿼리 예시는 `db/README.md`에 있다.

## 방문 로그

### POST /api/visit

로그인: 불필요

페이지를 열 때 한 번 호출한다.

```json
{ "path": "/pages/search.html" }
```

- `path`: `/`로 시작, 255자 이하. 쿼리 문자열(`?` 뒤)은 서버가 잘라서 저장한다 (공유 링크의 장소 이름이 로그에 남지 않게).
- `session_id`: 요청 본문으로 받지 않는다. 서버가 방문자 쿠키(`gilit_vid`, `HttpOnly`, 무작위 32바이트 hex = 64자, 1년)를 확인하고, 없으면 새로 발급해 그 값을 저장한다.
- `user_id`: 로그인 상태면 세션 사용자, 아니면 NULL

응답: `204` (본문 없음). 오류: `400`

## DB 매핑

| API | 필드 | DB 컬럼 |
| --- | --- | --- |
| 회원 | `name` | `users.nickname` |
| 회원 | `provider` | `users.password_hash` 유무, `social_accounts.provider` |
| 회원가입 | `agreeTerms`·`agreePrivacy` | `users.agreed_at` (동의 시각) |
| 즐겨찾기 | `name`, `type` | `favorite_places.place_name`, `favorite_places.label` |
| 검색 기록 | `from`, `to`, `arriveTime` (`arrive`) | `search_history.origin_name`, `dest_name`, `arrive_at` |
| 검색 기록 | `buffer`, `departTime`, `travelMode`, `aiSummary` | `buffer_min`, `recommended_depart_at`, `travel_mode`, `ai_summary` |
| 공통 | `id` (문자열) | 각 테이블 `id` (BIGINT) |

## 해민과 정할 것

### [해민과 합의 필요] 출발시각 API (`POST /api/departure`)

1. **필드 표기**: 이 API만 snake_case(`recommended_depart_at`)이고 나머지 명세와 프론트는 camelCase(`departTime`)다. 둘 중 하나로 통일한다. camelCase로 맞추면 서버에서 별칭(alias)만 바꾸면 된다.
2. **`/api/routes`와의 관계**: (나)로 구현했다. `GET /api/routes`가 경로 옵션마다 이 엔진으로 `departTime`을 계산한다. `POST /api/departure`는 단일 계산용으로 남긴다.
3. **좌표 전달**: 이 API는 좌표가 필수다. 지금 검색 조건 URL 쿼리(`from`, `to`)에는 장소 이름만 있어서, 결과 화면이 좌표를 알려면 쿼리에 좌표를 더하거나 장소 id로 다시 조회해야 한다.
4. **개발 환경 주소**: 프론트 `config.js`의 `BASE_URL`은 `/api`(같은 출처)다. Live Server(5500)와 uvicorn(8000)을 따로 띄우면 `http://127.0.0.1:8000/api`로 바꿔야 한다. 배포 때는 같은 출처로 두면 CORS가 필요 없다.
5. **오류 코드**: 입력 오류 400, 계산 불가 422, 외부 API 오류 502/503/504. 프론트는 4xx의 `message`를 그대로 보여 주고 5xx는 일반 문장으로 바꾼다 (지금 `api.js` 동작과 같다).

### [해민과 합의 필요] 경로 비교 (`GET /api/routes`)

1. **`js/mock/routes.json` 갱신**: `id`가 `route-1` 형식에서 `recommend` 등 옵션 키로 바뀌고 `options`, `bufferApplied`, `converged`가 생겼다. 목업을 바꾸면 `js/mock/routeGraph.json`의 `routeId`도 같이 바꿔야 그래프가 계속 짝지어진다.
2. **합쳐진 카드 표시**: `options`가 2개 이상이면(예: 추천 = 최단시간) 태그를 "추천 · 최단시간"처럼 보여 줄지.
3. **`bufferApplied=false` 안내**: 지금 카드는 요청한 여유시간을 항상 "여유 10분"으로 표시한다. 반영하지 못했을 때 "여유시간 미반영"을 보여 줄지.
4. **카드 4개**: 태그 색(`tag-3`)과 지도 색(`ROUTE_COLORS`)이 3개까지만 있다. 4번째 카드의 색을 정한다.
5. **색 기준**: 지금 색은 카드 순서(index)에 붙는다. 옵션(`id`)마다 색을 고정할지.
6. **빠진 옵션 안내**: 빠진 옵션과 이유는 서버 로그에만 있다. 화면에 "무료도로 경로 없음" 같은 안내가 필요하면 응답 형식을 다시 정한다.

### 그 밖의 항목

- 장소 검색 호출 방식: 프론트엔드가 장소 검색 API를 직접 호출할지, 백엔드 `GET /api/places`가 중계할지 (해민과 합의 필요)
- `from`, `to` 형식: 지금은 장소 이름만 전달한다. 출발시각 계산에는 좌표가 필요하다 (위 3번).
- 즐겨찾기 좌표: 프론트 즐겨찾기 추가 모달이 장소 검색 결과의 좌표를 보내도록 바꾸면 서버의 좌표 검색을 뺄 수 있다.
- 즐겨찾기·검색 기록 응답에 `lat`·`lng`, `buffer`·`departTime`을 더할지 (지금은 mock과 같은 필드만 돌려준다. 더하면 mock도 고친다)
- 검색 기록 저장을 프론트의 `POST /api/history` 대신 서버가 `GET /api/routes` 처리 중에 직접 할지
- `aiSummary`를 `/api/routes`에 포함할지, 별도 API로 분리할지
- 소셜 로그인(OAuth 콜백) 엔드포인트 경로
