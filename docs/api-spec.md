# 길잇 API 명세 (가안)

응답 필드명은 `frontend/js/mock/*.json`과 같다. 필드를 바꾸면 mock과 이 문서를 함께 고친다.

## 목록

| 메서드 | 경로 | 쿼리 | 설명 | 프론트 함수 (`api.js`) | mock 파일 |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/places` | `q` | 장소 검색 | `searchPlaces` | `places.json` |
| GET | `/api/routes` | `from`, `to`, `arrive`, `buffer` | 경로·권장 출발시각 | `getRoutes` | `routes.json` |
| GET | `/api/routes/graph` | `from`, `to`, `arrive` | 출발시각별 소요시간 | `getRouteGraph` | `routeGraph.json` |
| GET | `/api/favorites` | - | 즐겨찾기 목록 | `getFavorites` | `favorites.json` |
| POST | `/api/favorites` | - | 즐겨찾기 추가 | - | - |
| DELETE | `/api/favorites` | `id` | 즐겨찾기 삭제 | - | - |
| GET | `/api/history` | - | 검색 기록 | `getHistory` | `history.json` |
| GET | `/api/stats` | - | 이용 통계 | `getStats` | `stats.json` |
| POST | `/api/visit` | - | 방문 기록 | - | - |

## 공통 형식

- 시각: ISO 8601, 한국 시간 (`2026-11-02T08:50:00+09:00`)
- 금액: 원, 거리: km, 시간: 분
- `from`, `to`: `위도,경도` 문자열 (`37.5547,126.9707`)
- `buffer`: 도착 희망 시각보다 일찍 도착하려는 여유 시간(분)

## GET /api/places?q=

요청: `GET /api/places?q=서울역`

```json
[
  { "id": "place-1", "name": "서울역", "address": "서울 용산구 한강대로 405", "lat": 37.5547, "lng": 126.9707 }
]
```

## GET /api/routes?from=&to=&arrive=&buffer=

요청: `GET /api/routes?from=37.5547,126.9707&to=37.3947,127.1112&arrive=2026-11-02T09:00:00%2B09:00&buffer=10`

`departTime`이 권장 출발시각이고, `arriveTime`은 `arrive`에서 `buffer`를 뺀 예상 도착 시각이다. `toll`은 통행료, `fuel`은 예상 유류비다.

```json
[
  {
    "id": "route-1",
    "name": "추천 경로",
    "departTime": "2026-11-02T08:08:00+09:00",
    "arriveTime": "2026-11-02T08:50:00+09:00",
    "durationMin": 42,
    "distanceKm": 24.6,
    "toll": 1000,
    "fuel": 3500,
    "path": [
      { "lat": 37.5547, "lng": 126.9707 },
      { "lat": 37.3947, "lng": 127.1112 }
    ]
  }
]
```

## GET /api/routes/graph?from=&to=&arrive=

요청: `GET /api/routes/graph?from=37.5547,126.9707&to=37.3947,127.1112&arrive=2026-11-02T09:00:00%2B09:00`

```json
[
  { "departTime": "2026-11-02T07:00:00+09:00", "durationMin": 34 },
  { "departTime": "2026-11-02T07:15:00+09:00", "durationMin": 36 }
]
```

## GET /api/favorites

```json
[
  { "id": "fav-1", "name": "판교역", "address": "경기 성남시 분당구 판교역로 160", "lat": 37.3947, "lng": 127.1112 }
]
```

## POST /api/favorites

요청:

```json
{ "name": "판교역", "address": "경기 성남시 분당구 판교역로 160", "lat": 37.3947, "lng": 127.1112 }
```

응답: `201`

```json
{ "id": "fav-1", "name": "판교역", "address": "경기 성남시 분당구 판교역로 160", "lat": 37.3947, "lng": 127.1112 }
```

## DELETE /api/favorites?id=

요청: `DELETE /api/favorites?id=fav-1`

응답: `204` (본문 없음)

## GET /api/history

```json
[
  {
    "id": "hist-1",
    "from": "서울역",
    "to": "판교역",
    "departTime": "2026-10-30T08:08:00+09:00",
    "arriveTime": "2026-10-30T08:50:00+09:00",
    "searchedAt": "2026-10-29T21:14:00+09:00"
  }
]
```

## GET /api/stats

```json
{
  "dailyVisitors": [
    { "date": "2026-10-25", "count": 42 }
  ],
  "popularDestinations": [
    { "name": "판교역", "count": 128 }
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

- `from`, `to` 형식 (좌표 문자열 또는 장소 id)
- 즐겨찾기 대상 (현재는 장소 단위)과 삭제 시 id 전달 방식
- `POST /api/visit` 요청 본문
- 로그인 방식과 인증이 필요한 API 범위, 오류 응답 형식
