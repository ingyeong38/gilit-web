# 길잇 API 명세 (가안)

응답 필드명은 `frontend/js/mock/*.json`과 같다. 필드를 바꾸면 mock과 이 문서를 함께 고친다.
DB 스키마는 `db/schema.sql`, 테이블 설명은 `db/README.md`에 있다. API 필드와 DB 컬럼 이름이 다른 곳은 서버가 매핑한다 (아래 "DB 매핑").

## 목록

| 메서드 | 경로 | 설명 | 로그인 | 프론트 함수 (`api.js`) | mock |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/places?q=` | 장소 검색 | 불필요 | `searchPlaces` | `places.json` |
| GET | `/api/routes?from=&to=&arrive=&buffer=` | 경로·권장 출발시각 | 불필요 | `getRoutes` | `routes.json` |
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

"프론트 함수 없음"은 서버에 먼저 만들고 프론트에서 나중에 연결할 API다.

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
| `400` | 입력값 검증 실패 | 올바른 이메일 형식이 아닙니다. |
| `401` | 로그인 필요 API에 세션 없음 | 로그인이 필요합니다. |
| `401` | 이메일 로그인 실패 | 이메일 또는 비밀번호가 올바르지 않습니다. |
| `404` | 리소스가 없거나 내 것이 아님 | 찾을 수 없습니다. |
| `409` | 이메일 중복 등 충돌 | 이미 가입된 이메일입니다. |
| `429` | 요청 횟수 제한 초과 | 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요. |
| `500` | 서버 오류 | 잠시 후 다시 시도해 주세요. |

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
- 장소 검색: `name`에 `q`가 포함된 항목만 돌려준다
- 회원가입·로그인: 계정을 `localStorage`의 `gilit:mock:users`에 저장한다. 비밀번호는 평문이 아닌 SHA-256 값으로 두지만, 브라우저 안의 흉내일 뿐이다. 서버는 bcrypt를 쓴다.

## 길찾기 (로그인 불필요)

### GET /api/places?q=

호출 방식 미정(해민과 합의 필요): 프론트엔드가 장소 검색 API를 직접 호출할지, 백엔드가 이 API로 중계할지 정하지 않았다.

요청: `GET /api/places?q=김해시청`

```json
[
  { "id": "place-1", "name": "김해시청", "address": "경상남도 김해시", "lat": 35.2285, "lng": 128.8894 }
]
```

### GET /api/routes?from=&to=&arrive=&buffer=

요청: `GET /api/routes?from=김해시청&to=동의대학교&arrive=2026-11-02T09:00:00%2B09:00&buffer=10`

`departTime`이 권장 출발시각이고, `arriveTime`은 `arrive`에서 `buffer`를 뺀 예상 도착 시각이다. `label`은 경로 구분 표시, `toll`은 통행료, `fuel`은 예상 유류비, `aiSummary`는 AI 경로 추천 요약이다. 추천 경로를 첫 번째로 돌려준다.

```json
[
  {
    "id": "route-1",
    "label": "추천",
    "name": "남해고속도로 경유",
    "departTime": "2026-11-02T08:12:00+09:00",
    "arriveTime": "2026-11-02T08:50:00+09:00",
    "durationMin": 38,
    "distanceKm": 31.4,
    "toll": 1600,
    "fuel": 4200,
    "path": [
      { "lat": 35.2285, "lng": 128.8894 },
      { "lat": 35.1441, "lng": 129.0336 }
    ],
    "aiSummary": {
      "title": "남해고속도로 경유가 가장 안정적이에요",
      "text": "세 경로 중 예상 소요시간이 가장 짧아 가장 늦게 출발해도 제시간에 도착할 수 있어요."
    }
  }
]
```

### GET /api/routes/graph?from=&to=&arrive=

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

- 장소 검색 호출 방식: 프론트엔드가 장소 검색 API를 직접 호출할지, 백엔드 `GET /api/places`가 중계할지 (해민과 합의 필요)
- `from`, `to` 형식: 지금은 장소 이름만 전달한다. 길찾기 API에 좌표가 필요하면 URL 쿼리와 함께 바꾼다.
- 즐겨찾기 좌표: 프론트 즐겨찾기 추가 모달이 장소 검색 결과의 좌표를 보내도록 바꾸면 서버의 좌표 검색을 뺄 수 있다.
- 즐겨찾기·검색 기록 응답에 `lat`·`lng`, `buffer`·`departTime`을 더할지 (지금은 mock과 같은 필드만 돌려준다. 더하면 mock도 고친다)
- 검색 기록 저장을 프론트의 `POST /api/history` 대신 서버가 `GET /api/routes` 처리 중에 직접 할지
- `aiSummary`를 `/api/routes`에 포함할지, 별도 API로 분리할지
- 소셜 로그인(OAuth 콜백) 엔드포인트 경로
