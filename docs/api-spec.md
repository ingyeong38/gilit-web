# 길잇 API 명세 (가안)

응답 필드명은 `frontend/js/mock/*.json`과 같다. 필드를 바꾸면 mock과 이 문서를 함께 고친다.

## 목록

| 메서드 | 경로 | 쿼리 | 설명 | 프론트 함수 (`api.js`) | mock 파일 |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/places` | `q` | 장소 검색 | `searchPlaces` | `places.json` |
| GET | `/api/routes` | `from`, `to`, `arrive`, `buffer` | 경로·권장 출발시각 | `getRoutes` | `routes.json` |
| GET | `/api/routes/graph` | `from`, `to`, `arrive` | 출발시각별 소요시간 | `getRouteGraph` | `routeGraph.json` |
| GET | `/api/favorites` | - | 즐겨찾기 목록 | `getFavorites` | `favorites.json` |
| POST | `/api/favorites` | - | 즐겨찾기 추가 | `addFavorite` | localStorage에 저장 |
| DELETE | `/api/favorites` | `id` | 즐겨찾기 삭제 | `removeFavorite` | localStorage에 저장 |
| GET | `/api/history` | - | 검색 기록 | `getHistory` | `history.json` |
| GET | `/api/stats` | - | 이용 통계 | `getStats` | `stats.json` |
| POST | `/api/visit` | - | 방문 기록 | - | - |
| POST | `/api/auth/signup` | - | 이메일 회원가입 | `signup` | localStorage에 저장 |
| POST | `/api/auth/login` | - | 이메일 로그인 | `loginWithEmail` | localStorage에서 확인 |
| POST | `/api/auth/logout` | - | 로그아웃 | `logoutSession` | 호출 안 함 |

## 공통 형식

- 시각: ISO 8601, 한국 시간 (`2026-11-02T08:50:00+09:00`)
- 금액: 원, 거리: km, 시간: 분
- `from`, `to`: 장소 이름 (`김해시청`)
- `buffer`: 도착 희망 시각보다 일찍 도착하려는 여유 시간(분)
- 오류: 4xx 응답 본문은 `{ "message": "..." }`이다. 프론트는 4xx의 `message`를 그대로 화면에 보여 주고, 5xx와 네트워크 오류는 "잠시 후 다시 시도해 주세요."로 바꾼다.

## 목업 동작

`USE_MOCK = true`이면 `api.js`가 서버 역할 일부를 대신한다. 실제 서버는 아래 값을 직접 계산해서 돌려준다.

- 경로: `arriveTime`은 `arrive - buffer`, `departTime`은 `arriveTime - durationMin`
- 그래프: 마지막 출발시각이 `arrive`가 되도록 시각을 옮긴다
- 기록·통계: 가장 최근 날짜가 오늘이 되도록 날짜를 옮긴다
- 장소 검색: `name`에 `q`가 포함된 항목만 돌려준다
- 회원가입·로그인: 계정을 `localStorage`의 `gilit:mock:users`에 저장한다. 비밀번호는 평문이 아닌 SHA-256 값으로 두지만, 브라우저 안의 흉내일 뿐이다. 서버는 아래 규칙대로 bcrypt를 쓴다.

## GET /api/places?q=

요청: `GET /api/places?q=김해시청`

```json
[
  { "id": "place-1", "name": "김해시청", "address": "경상남도 김해시", "lat": 35.2285, "lng": 128.8894 }
]
```

## GET /api/routes?from=&to=&arrive=&buffer=

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

## GET /api/routes/graph?from=&to=&arrive=

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

## GET /api/favorites

`type`은 `집`, `학교`, `회사`, `기타` 중 하나다.

```json
[
  { "id": "fav-1", "name": "집", "address": "경상남도 김해시 내외중앙로 47", "type": "집" }
]
```

## POST /api/favorites

요청:

```json
{ "name": "집", "address": "경상남도 김해시 내외중앙로 47", "type": "집" }
```

응답: `201`

```json
{ "id": "fav-1", "name": "집", "address": "경상남도 김해시 내외중앙로 47", "type": "집" }
```

## DELETE /api/favorites?id=

요청: `DELETE /api/favorites?id=fav-1`

응답: `204` (본문 없음)

## GET /api/history

```json
[
  { "id": "hist-1", "from": "김해시청", "to": "동의대학교", "arriveTime": "2026-11-02T09:00:00+09:00" }
]
```

## GET /api/stats

`dailyVisitors`는 최근 7일이고 마지막 항목이 오늘이다. `weekChangePct`는 주간 방문자 증감률(%)이다. 오늘 방문자, 어제 대비 증감, 주간 합계, 방문자당 검색 수는 프론트에서 계산한다.

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

## POST /api/visit

요청:

```json
{ "path": "/pages/search.html" }
```

응답: `204` (본문 없음)

## 이메일 회원가입·로그인

DB 스키마는 `backend/migrations/001_create_users.sql`에 있다.

### 서버 검증 규칙

프론트(`js/components/authModal.js`)도 같은 규칙으로 먼저 검사하지만, 서버가 다시 검사한다.

| 필드 | 규칙 | 오류 `message` |
| --- | --- | --- |
| `name` | 앞뒤 공백 제거 후 2~20자 | 이름은 2~20자로 입력해 주세요. |
| `email` | 앞뒤 공백 제거·소문자 변환 후 이메일 형식, 254자 이하 | 올바른 이메일 형식이 아닙니다. |
| `password` | 8~64자, 영문과 숫자를 모두 포함, UTF-8 72바이트 이하 (bcrypt 한계) | 비밀번호는 영문과 숫자를 포함해 8~64자로 입력해 주세요. |
| `agreeTerms`, `agreePrivacy` | 둘 다 `true` | 필수 약관에 모두 동의해 주세요. |

### 보안 규칙

- 비밀번호는 bcrypt(cost 12 이상)로 해시해 `password_hash`에만 저장한다. 평문 비밀번호를 DB, 로그, 오류 응답에 남기지 않는다. 요청 본문 로깅을 켠다면 `password` 필드를 가린다.
- 모든 쿼리는 파라미터 바인딩(prepared statement)으로 실행한다. 문자열을 이어 붙여 SQL을 만들지 않는다.
- 로그인 실패는 이유와 관계없이 `401` + "이메일 또는 비밀번호가 올바르지 않습니다."로 통일한다. 계정이 없거나 소셜 전용 계정(`password_hash`가 NULL)일 때도 고정된 더미 해시로 bcrypt 비교를 한 번 수행해 응답 시간으로 계정 존재가 드러나지 않게 한다.
- 로그인 시도 횟수 제한(예: IP·이메일별 분당 5회)을 둔다.

### 같은 이메일의 소셜 계정 처리

계정은 이메일 하나당 하나다 (`users.email` UNIQUE). 계정을 자동으로 합치지 않는다.

- 이메일 회원가입 시 같은 이메일이 이미 있으면 (소셜 가입이어도) `409` "이미 가입된 이메일입니다."를 돌려준다. 가입 화면은 중복 여부를 알려 줄 수밖에 없으므로 이 응답만 예외로 둔다.
- 소셜 로그인 시 `(provider, provider_user_id)`로 계정을 찾는다. 처음 로그인하는데 그 이메일로 이메일 계정이 이미 있으면 새 계정을 만들지 않고 `409` "이미 이메일로 가입된 계정입니다. 이메일로 로그인해 주세요."를 돌려준다.
- 이유: 카카오는 이메일 인증 여부가 보장되지 않아, 이메일만 보고 합치면 남의 계정에 로그인할 수 있다. 계정 연결은 나중에 "내 정보"에서 로그인한 상태로만 제공한다.

### 로그인이 필요한 API

`/api/favorites`(GET·POST·DELETE), `/api/history`, `/api/stats`는 세션이 없으면 `401`을 돌려준다. 프론트도 해당 화면(`js/guard.js`의 `PROTECTED_PATHS`)을 로그인 모달로 막지만, 이건 화면 흐름용이라 서버 검사를 대신하지 않는다. `/api/places`, `/api/routes`, `/api/routes/graph`는 로그인 없이 쓴다.

### 로그인 상태

로그인에 성공하면 서버가 세션을 만들고 `HttpOnly; Secure; SameSite=Lax` 쿠키로 세션 ID를 내려준다. 소셜 로그인도 같은 세션 방식을 쓴다. 프론트는 응답 본문의 사용자 정보를 화면 표시용으로만 `localStorage`(`gilit:user`)에 저장하고, 토큰은 다루지 않는다.

## POST /api/auth/signup

요청:

```json
{ "name": "길잇", "email": "user@example.com", "password": "gilit1234", "agreeTerms": true, "agreePrivacy": true }
```

응답: `201`. 가입만 하고 로그인 세션은 만들지 않는다. 프론트는 로그인 화면으로 돌아가 이메일을 채워 둔다.

```json
{ "id": "user-1", "name": "길잇", "email": "user@example.com", "provider": "email" }
```

오류: `400` 검증 실패 (위 표의 `message`), `409` "이미 가입된 이메일입니다."

## POST /api/auth/login

요청:

```json
{ "email": "user@example.com", "password": "gilit1234" }
```

응답: `200` + 세션 쿠키

```json
{ "id": "user-1", "name": "길잇", "email": "user@example.com", "provider": "email" }
```

오류: `401` "이메일 또는 비밀번호가 올바르지 않습니다."

## POST /api/auth/logout

세션을 지우고 쿠키를 만료시킨다. 응답: `204` (본문 없음)

## 해민과 정할 것

프론트에서 먼저 잡은 값이다. 백엔드 구성에 맞춰 확정한다.

- `from`, `to` 형식: 지금은 장소 이름만 전달한다. 길찾기 API에 좌표가 필요하면 URL 쿼리와 함께 바꾼다.
- 즐겨찾기 대상(현재는 장소 단위)과 삭제 시 id 전달 방식
- `aiSummary`를 `/api/routes`에 포함할지, 별도 API로 분리할지
- `POST /api/visit` 요청 본문
- 마이그레이션 SQL은 MySQL 8 기준이다. DB를 다르게 고르면 맞춰 고친다.
- 새로고침 시 서버 세션 기준으로 로그인 상태를 확인할 `GET /api/auth/me`가 필요한지
