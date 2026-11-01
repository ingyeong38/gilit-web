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

## 공통 형식

- 시각: ISO 8601, 한국 시간 (`2026-11-02T08:50:00+09:00`)
- 금액: 원, 거리: km, 시간: 분
- `from`, `to`: 장소 이름 (`김해시청`)
- `buffer`: 도착 희망 시각보다 일찍 도착하려는 여유 시간(분)

## 목업 동작

`USE_MOCK = true`이면 `api.js`가 서버 역할 일부를 대신한다. 실제 서버는 아래 값을 직접 계산해서 돌려준다.

- 경로: `arriveTime`은 `arrive - buffer`, `departTime`은 `arriveTime - durationMin`
- 그래프: 마지막 출발시각이 `arrive`가 되도록 시각을 옮긴다
- 기록·통계: 가장 최근 날짜가 오늘이 되도록 날짜를 옮긴다
- 장소 검색: `name`에 `q`가 포함된 항목만 돌려준다

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

## 해민과 정할 것

프론트에서 먼저 잡은 값이다. 백엔드 구성에 맞춰 확정한다.

- `from`, `to` 형식: 지금은 장소 이름만 전달한다. 길찾기 API에 좌표가 필요하면 URL 쿼리와 함께 바꾼다.
- 즐겨찾기 대상(현재는 장소 단위)과 삭제 시 id 전달 방식
- `aiSummary`를 `/api/routes`에 포함할지, 별도 API로 분리할지
- `POST /api/visit` 요청 본문
- 로그인 방식과 인증이 필요한 API 범위, 오류 응답 형식
