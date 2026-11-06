# 길잇 (Gilit)

> 도착 시간만 정하세요. 출발 시간은 알려드릴게요.

## 프로젝트 설명

길잇은 **도착 희망 시각을 기준으로 출발 시각을 알려주는 자동차 길찾기 웹 서비스**입니다.

기존 내비게이션은 출발지와 목적지를 입력하면 "지금 출발하면 몇 분 걸리는지"를 알려줍니다. 하지만 약속, 통학, 면접처럼 정해진 시각에 도착해야 하는 상황에서는 사용자가 출발 시각을 직접 계산해야 합니다. 시간대에 따라 교통량이 달라 단순 계산은 오차도 큽니다.

길잇은 이 과정을 반대로 뒤집습니다. 사용자가 출발지, 목적지, 도착 희망 시각을 입력하면 경로별로 몇 시에 출발해야 하는지를 계산해 알려줍니다.

## 목표

- 도착 시각 기준으로 경로별 권장 출발 시각을 제공해 출발 시간 계산의 부담을 없앤다.
- 시간대별 교통 상황을 반영해 단순 계산보다 정확한 출발 시각을 안내한다.
- 여유 시간 설정과 출발 시각별 소요 시간 비교로 지각 위험을 줄인다.
- AWS 기반 웹 서비스로 구현해 클라우드 환경에서의 개발·배포 경험을 쌓는다.

## 주요 기능

| 구분 | 기능 | 설명 |
|---|---|---|
| 핵심 | 출발 시각 역산 | 도착 희망 시각에서 경로별 권장 출발 시각을 계산 |
| 핵심 | 경로 비교 | 소요 시간, 거리, 통행료, 유류비를 경로별로 비교 |
| 핵심 | 여유 시간 설정 | 5/10/15분 여유를 반영해 안전한 출발 시각 안내 |
| 차별화 | 출발 시각별 소요 시간 그래프 | 몇 시에 출발해야 덜 막히는지 한눈에 비교 |
| 차별화 | AI 경로 추천 요약 | 가장 안정적인 경로와 이유를 한 줄로 요약 |
| 차별화 | 출발 알림 | 권장 출발 시각 전에 알림 전송 |
| 기본 | 장소 검색·지도 경로 표시 | 출발지·목적지 검색과 지도 위 경로 표시 |
| 기본 | 소셜 로그인 | Google·카카오 계정으로 간편 로그인 |
| 편의 | 즐겨찾기·검색 기록 | 자주 가는 장소와 최근 검색 저장 |
| 편의 | 경로 공유 | 검색 조건을 링크로 복사해 다른 사람에게 공유 |
| 운영 | 이용 통계 대시보드 | 방문자 수, 인기 출발지·목적지 확인 |

## 개발 일정

기간: 2026.11.01 ~ 2026.12.07 (5주)

| 주차 | 기간 | 주요 내용 |
|---|---|---|
| 1주차 | 11/1 ~ 11/9 | 주제·기능 확정, 길찾기 API 신청·검증, 화면 디자인, 개발 환경 세팅 |
| 2주차 | 11/10 ~ 11/16 | 출발 시각 역산 엔진, 장소 검색, 도착시각·여유시간 입력, 소셜 로그인 |
| 3주차 | 11/17 ~ 11/23 | 경로 비교 목록, 지도 경로 표시, 소요 시간 그래프, 즐겨찾기·검색 기록 |
| 4주차 | 11/24 ~ 11/30 | AI 경로 추천 요약, 출발 알림, 경로 공유, 이용 통계 대시보드 |
| 5주차 | 12/1 ~ 12/7 | 통합 테스트, 버그 수정, AWS 배포, 보고서 작성 |

## 프론트엔드 실행 · SFR-005 지도 경로 표시

프로젝트 루트(`gilit-web`)에서 실행합니다. 백엔드나 추가 패키지 설치가 필요하지 않습니다.

```sh
python3 -m http.server 5500 --directory frontend
```

- 검색: http://localhost:5500/pages/search.html
- 결과 예시: http://localhost:5500/pages/result.html?from=김해시청&to=동의대학교&date=2026-11-07&time=09:00&buffer=10
- 중지: 서버 터미널에서 Ctrl+C

`frontend/js/config.js`의 예시 경로 모드(`USE_MOCK_ROUTES=true`)와 빈 지도 키로도 실행할 수 있습니다. 목업 좌표는 김해시청 → 동의대학교이며, 검색어를 바꿔도 이 예시 좌표를 반환합니다. 지도와 결과 안내에 이를 표시합니다. 좌표를 순서대로 연결한 예시선이므로 실제 주행 가능한 도로 경로로 해석하지 않습니다.

카카오 지도 배경을 시험하려면 `frontend/js/config.js`의 `KAKAO_JS_KEY`에 **JavaScript 키**를 로컬에서 설정하고 카카오 개발자 설정에 실행 출처(`http://localhost:5500`)를 등록합니다. 지도 사용 설정도 확인합니다. 실제 키를 저장한 파일은 커밋하지 말고 작업 후 빈 문자열로 되돌립니다. 키가 있어도 `USE_MOCK_ROUTES = true`이면 예시 좌표를 카카오 지도 위에 그립니다. 지도 SDK 연결은 자동차 길찾기 조회와 별개이며, 이번 기능은 이미 제공된 `route.path`를 표시합니다. 실제 경로 조회·장소 검색·출발시각 계산 API를 새로 호출하지 않습니다.

수정 위치와 검색할 함수:

- `frontend/js/components/map.js`: `renderRouteMap`(기존 호출 호환), `validateRoutePath`(좌표 검사), `projectRoutePath`(화면 좌표 변환), `renderPreview`(SVG), `renderKakaoMap`(Polyline·Marker·범위·확대축소), `destroyRouteMap`(이전 표시와 감시 정리)
- `frontend/js/utils.js`: `loadKakaoMapSdk`(공유 로딩, 10초 제한, 실패 후 재시도)
- `frontend/js/pages/result.js`: `setupResults`(카드 선택·예시 명칭), `init`(목업 안내)
- `frontend/css/pages/result.css`: `.route-preview`, `.kakao-map-canvas`, `.map-status`, 모바일 미디어 쿼리

검증: JS 문법, 세 목업 경로의 서로 다른 선 모양, 수평·수직·동일 좌표, 누락·범위 초과·문자열·NaN 좌표, SDK 실패·시간 초과·재시도, 빠른 선택 시 최신 경로 유지, 감시·오버레이·컨트롤 정리를 JavaScript 모의 환경에서 확인했습니다. 로컬 결과 HTML은 HTTP 200 응답을 확인했습니다. 브라우저 자동화 도구의 연결 오류(`timeoutMs`)로 실제 브라우저 화면·모바일 시각 검증을 완료하지 못했습니다. 실제 카카오 키를 사용한 지도 타일·도메인 인증·기기별 동작은 별도 확인이 필요합니다.

수동 확인: 결과 화면에서 세 카드를 번갈아 선택해 선 모양·색상·출발/도착을 확인하고, 화면 폭을 375px로 줄여 지도와 안내가 잘리는지 확인합니다. 키 설정 후에는 확대/축소와 창 크기 변경을 확인합니다. SDK 요청을 브라우저 개발자 도구에서 차단하면 오류 안내와 좌표 미리보기가 남아야 합니다. 요청을 완료하지 않는 경우에는 10초 후 미리보기 안내로 전환됩니다.

카카오 SDK 메서드 참고: [Kakao Maps Web API 공식 문서](https://apis.map.kakao.com/web/documentation/).

지도 회귀 테스트(Node.js가 설치된 환경, npm 설치 불필요):

```sh
node frontend/tests/map.test.mjs
```

`frontend/tests/map.test.mjs`는 좌표 오류·수평/수직/동일 좌표·15만 좌표·카드 전환 경쟁·SDK 실패/시간 초과/재시도·감시 정리를 검증합니다. DOM과 SDK는 모의 객체이므로 실제 브라우저 렌더링 검증은 별도로 진행합니다.

## SFR-002 장소 검색·도착 조건 입력

실행 명령은 프로젝트 루트에서 `python3 -m http.server 5500 --directory frontend`이며, 검색 주소는 http://localhost:5500/pages/search.html 입니다. 이미 5500 서버가 실행 중이면 해당 주소를 새로고침합니다.

- `frontend/js/api.js`의 `searchPlaces`: 목업의 이름·주소 부분 검색, 검색어 공백 제거. `USE_MOCK_ROUTES = false`에서는 `BASE_URL`의 `GET /places?q=...`를 사용합니다. 실제 백엔드 연결은 아래 복원 항목을 참고합니다.
- `frontend/js/components/placeAutocomplete.js`의 `setupAutocomplete`: 200ms 디바운스, 입력 즉시 이전 응답 무효화, 검색 중/없음/실패와 재시도, 마우스·방향키·Enter·Escape·Tab 조작. 선택한 장소 좌표를 결과 쿼리에 전달하고 재입력 시 이전 선택을 무효화합니다. 이름 직접 입력도 허용합니다.
- `frontend/js/pages/search.js`의 `submit`, `goToResult`, `fillForm`, `setBuffer`: 입력 검사·포커스, 중복 제출 차단, 뒤로 가기 복구, URL 조건 복원, 여유시간 선택과 `aria-pressed`. 최근 검색도 `submit`으로 같은 검사를 거칩니다.
- `frontend/js/utils.js`의 `koreaDateTime`, `nextDateForTime`, `validateSearchConditions`: 브라우저 시간대와 관계없이 KST 도착 시각 검사, 자정 경계 처리. 현재 분과 과거는 제출할 수 없습니다.
- `frontend/js/pages/result.js`의 `init`: 직접 URL·즐겨찾기 기록 링크로 들어와도 공통 조건 검사를 수행하고, 오류가 있으면 쿼리를 유지한 조건 수정 링크를 제공합니다.
- `frontend/pages/search.html`, `frontend/css/pages/search.css`: 예시 장소 검색 범위와 한국 시간 안내, 접근성 속성, 모바일에서 검색 목록이 다음 입력칸을 가리지 않는 배치.

자동 회귀 테스트(추가 패키지 불필요, Node.js 필요):

```sh
node frontend/tests/search.test.mjs
node frontend/tests/map.test.mjs
```

SFR-002 검증: 이름·주소 검색, 빈 결과, API 요청 쿼리, 빠른 입력의 응답 역전, 키보드·마우스 선택, 실패 안내, HTML 이스케이프, 입력별 오류·포커스, KST 자정·연말, 조건 복원·교환, 여유시간, 중복 제출·뒤로 가기 복구를 모의 DOM/API 환경에서 검증했습니다. Chrome에서 화면 로드, 주소 검색(경상남도 → 3개 결과), 방향키·Enter 선택 후 목록 닫힘을 확인했습니다. 브라우저 제어가 간헐적으로 중단되어 나머지 브라우저 상호작용·실제 모바일 화면은 모두 확인하지 못했습니다. 실제 백엔드 연결은 미검증입니다.

수동 확인: 두 입력칸에 이름/주소를 입력하고 방향키·Enter로 선택합니다. 일치하지 않는 검색어, 필수값 누락, 같은 장소, 과거 도착 시각을 시험합니다. 개발자 도구에서 `/js/mock/places.json` 요청을 차단하면 실패 안내와 재시도가 보여야 합니다. 정상 조건으로 결과에 이동한 뒤 조건 수정과 브라우저 뒤로 가기에서 입력값과 검색 버튼을 확인합니다. 모바일 폭에서는 검색 목록을 열고 아래 목적지·날짜·시각 입력칸에 접근할 수 있는지 확인합니다.

카카오 지도 오류 진단: `renderRouteMap`의 `catch(error)`는 `[Gilit 지도] 지도 표시 실패`로 콘솔에 `stage`, `code`, `name`, `message`를 남깁니다. Error 원본과 stack은 SDK URL의 키를 노출할 수 있어 출력하지 않습니다. `getKakaoMapErrorDetails`가 설정된 키와 URL의 키 매개변수를 가립니다.

| 코드 | 확인할 단계 |
| --- | --- |
| `SDK_REQUEST_FAILED` | SDK script 요청 실패. 개발자 도구 Network에서 HTTP 상태·도메인·인증·요청 차단 확인 |
| `SDK_DOWNLOAD_TIMEOUT` | SDK script 다운로드가 10초 안에 완료되지 않음 |
| `SDK_INITIALIZATION_TIMEOUT` | script 로드 후 SDK 초기화 콜백이 전체 제한시간 안에 완료되지 않음 |
| `SDK_INVALID_RESPONSE` | script 로드 후 `kakao.maps.load`가 없음 |
| `SDK_INITIALIZATION_FAILED` | SDK 초기화 중 예외 또는 초기화 후 Map 생성자가 없음 |
| `MAP_RENDER_FAILED` | SDK 로드 이후 지도·경로·마커·지도 범위 설정 중 오류 |

교차 출처 script의 `onerror` 자체는 HTTP 상태나 응답 본문을 제공하지 않습니다. `SDK_REQUEST_FAILED`만으로 도메인 오류를 단정하지 않습니다. Network의 SDK 응답이 `401` 및 `domain mismatched`라면 **config.js에 사용한 JavaScript 키**의 SDK 도메인 설정에서 현재 브라우저의 출처(프로토콜·호스트·포트)를 확인하고 저장합니다. 키가 들어 있는 전체 SDK URL은 공유하지 않습니다. 카카오 설정 변경은 코드 변경과 별개이며, 포트를 바꾸지 말고 실제 접속 주소를 기준으로 확인합니다.

## 실제 자동차 도로 경로 연동 (복원)

실제 경로 연동을 다시 적용했습니다. 기존 지도·검색 UI를 유지합니다. 현재 모드는 아래와 같이 분리합니다.

- `frontend/js/config.js`: `USE_MOCK_ROUTES=false`는 실제 장소 검색·도로 경로 조회에만 적용합니다. `true`로 바꾸면 예시 장소·경로·그래프를 사용합니다.
- `USE_MOCK=true`는 즐겨찾기·기록·통계 등 기존 예시 데이터 흐름을 유지합니다. 이번 변경에는 SFR-001 서버 인증 작업을 포함하지 않습니다.
- 지도용 JavaScript 키는 기존 설정을 유지하고, 길찾기 REST 키는 서버 `.env`의 `KAKAO_REST_API_KEY`에서만 읽습니다. 실제 키를 커밋하지 않습니다.

프로젝트 루트 `gilit-web`의 VS Code 터미널에서 실행합니다(Python 3.11 이상으로 만든 `backend/venv` 필요).

```sh
ROUTE_PROVIDER=kakao backend/venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8003 --no-access-log
```

백엔드가 프론트도 함께 제공하므로 정적 서버를 별도로 실행하지 않습니다. 같은 포트의 기존 서버가 켜져 있으면 그 서버를 먼저 종료합니다.

- 검색: http://127.0.0.1:8003/pages/search.html
- API 문서: http://127.0.0.1:8003/docs
- 종료: 실행 터미널에서 Control+C

장소 검색에서 ‘동의대학교’를 입력한 뒤 원하는 캠퍼스를 선택합니다. 선택 좌표도 쿼리에 전달해 다른 지점으로 바뀌지 않게 합니다. 조건 수정과 교환에서도 좌표를 함께 처리하고 재입력하면 이전 선택을 무효화합니다. 좌표 없는 이전 링크는 서버가 이름·주소를 하나로 확정할 수 있어야 합니다.

경로선은 `sections[].roads[].vertexes`의 모든 좌표를 순서대로 사용합니다. 각 카드의 거리·시간·경로는 최종 계산에 쓴 같은 응답에 대응하고 동일 경로는 중복 제거합니다. 실제 조회 실패는 안내하며 예시 결과로 대체하지 않습니다. 실제 그래프 API는 별도 범위여서 실제 경로 모드에서는 차트를 숨기고 미제공 요금은 ‘미제공’으로 표시합니다.

캐시가 없는 첫 요청은 기본 최대 24회 길찾기 조회가 발생할 수 있습니다. 같은 조건 결과는 `ROUTE_CACHE_TTL_SEC`(기본 600초) 동안 최대 64건 재사용합니다. 응답의 `X-Gilit-Route-Cache: HIT|MISS`로 확인할 수 있습니다. 실패·만료·이미 지난 출발시각은 재사용하지 않습니다. 캐시는 단일 서버 프로세스 메모리이며 동시 최초 요청은 별도 호출될 수 있습니다.

검증:

```sh
cd backend
venv/bin/python -m pytest -q
```

프로젝트 루트에서(Node.js 필요):

```sh
node frontend/tests/routes.test.mjs
node frontend/tests/map.test.mjs
node frontend/tests/search.test.mjs
```

실제 API 수동 검사는 `backend/venv/bin/python backend/scripts/check_road_routes.py`입니다. 외부 요청을 사용하므로 필요할 때만 실행합니다. 상세 검증 기록은 `docs/road-route-verification.md`를 참고합니다.
