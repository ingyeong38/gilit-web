# 기존 그래프 + 실제 자동차 API 프론트 통합

원본: `~/Desktop/gilit-graph-final-20261114-103700/frontend`.
기존 백업 폴더는 보존하고 그래프 브랜치의 프론트 연결 코드만 수정했다.
기존 CSS, charts.js, durationGraph.js, 지도·로그인·검색 컴포넌트는 원본 그대로다.
코드 변경은 `js/config.js`, `js/api.js`, `js/pages/result.js`, 신규 `js/graphData.js`뿐이다.

## 실행 (프로젝트 루트, Mac M1)

백엔드가 이미 8003에서 실행 중이면 재실행할 필요 없다.
현재 설치된 Python과 패키지로 확인한 실행 명령:

```sh
PYTHONPATH=backend/venv/lib/python3.11/site-packages /opt/homebrew/bin/python3.11 -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8003 --no-access-log
```

별도 터미널:

```sh
python3 scripts/serve_frontend.py --port 8765 --directory frontend
```

접속: http://127.0.0.1:8765/pages/search.html
일반 `http.server`로 실행하면 API 프록시가 없어 404가 발생한다.
개발 프록시가 `/api/*` GET 요청을 기존 8003 백엔드로 전달한다.
백엔드 소스·환경변수·DB 변경은 필요하지 않다. 프론트 공개 지도 키는 frontend/js/config.js에 로컬에서 입력하며 키를 넣은 설정 파일을 커밋하지 않는다.

## 그래프 데이터 모드

`GRAPH_DATA_SOURCE`는 `USE_MOCK_ROUTES`와 독립적이다.

- `auto`: 기존 `/api/routes/graph` 조회. 404인 로컬 개발 환경에서만 예시를 표시한다.
- `api`: 기존 API만 사용한다. 실패 시 그래프에 오류를 표시하고 카드·지도는 유지한다.
- `example`: 로컬 개발 환경에서만 기존 예시 JSON을 사용한다.
- `off`: 그래프 비활성화.

실제 API의 카드와 그래프는 동일 `routeId`로만 연결한다.
요청은 `/api/routes` 카드마다 `card=<id>@<departTime>`을 반복해 보낸다(departTime 없는 카드 제외, 최대 4개, 카드가 없으면 요청 안 함). 예: `GET /api/routes/graph?from=김해시청&to=동의대학교&arrive=2026-11-18T09:00:00%2B09:00&buffer=10&card=recommend%402026-11-18T08:20:00%2B09:00&card=time%402026-11-18T08:10:00%2B09:00`
현재 실제 그래프 API는 미구현이다. 예시 `route-1/2/3`은 실제 카드의
`recommend/time/distance/free`와 다르므로 임의로 변환하거나 연결하지 않는다.
독립된 예시 선택기에서 예시 카드와 정확히 ID가 맞는 예시 그래프만 보여준다.
점선의 출발시각도 실제 카드가 아닌 원본 예시 카드의 시각이다.
예시 날짜와 값은 변조하지 않으며 실제 교통 예측이 아님을 표시한다.
API 5xx/시간초과를 예시로 감추지 않는다. 예시는 운영 도메인에서 차단된다.

## 검증 및 팀원 요청

- 실제 `/api/places`: HTTP 200, 검색 15개. Safari 자동완성 확인.
- 실제 `/api/routes`: HTTP 200. Safari 경로 카드와 예시 그래프 동시 표시 확인.
- 기존 그래프 점 클릭 말풍선, 데이터 표 펼치기 확인.
- CSS와 그래프 렌더러는 원본과 바이트 단위 동일 (530px 카드·250×160px 말풍선 포함).
- 지도 SDK: HTTP 401 `domain mismatched` for `http://127.0.0.1:8765`.
  현재 좌표 미리보기만 표시한다. 카카오 앱 담당자에게 JavaScript 키의 허용 웹 도메인에
  `http://127.0.0.1:8765` (localhost 사용 시 `http://localhost:8765`도) 등록 요청이 필요하다.
  이 작업에서 개발자 콘솔 설정은 변경하지 않았다.
- 백엔드 담당자에게 기존 카드 ID와 동일한 `routeId` 및
  `points: [{departTime: ISO8601, durationMin: number}]` 배열을 반환하는 그래프 API 계약 확인을 요청한다.
  새 API는 구현하지 않았다.
- 로그인·회원가입·즐겨찾기·공유 코드는 변경하지 않았고 이번 통합의 동작 검증 대상에서는 제외했다.

Node가 설치되어 있다면 `node frontend/tests/graph-data.test.mjs`로 데이터 연결 테스트 실행.
