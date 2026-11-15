# 경로 결과 UI 개선 — 2026-11-14

작업 폴더: /private/tmp/gilit-duration-graph, 브랜치: haemin/duration-graph.
기존 미커밋 그래프 작업을 유지해 그 위에서 수정했다. 원래 haemin/login 폴더는 변경하지 않았다.
commit/push/merge/배포는 하지 않았다.

## 변경 파일과 내용

- js/pages/result.js: 실제 API 응답을 사용한 동일 크기 4개 정보 카드, 깃발·도착 시각·여유시간 영역.
  카드와 차트에 선택한 경로 태그를 전달한다. 시간 역산·도착 시각 계산은 바꾸지 않았다.
- js/components/icon.js: 기존 선형 SVG 아이콘 시스템에 톨게이트·주유소·깃발 추가.
- js/components/charts.js: 접이식 카드 목록, 행/점 선택 동기화, 클릭 요약 카드, 키보드 및 외부 클릭 닫기.
  다른 경로 렌더링 시 선택 및 외부 이벤트를 정리한다. 통계 차트는 유지한다.
- js/components/durationGraph.js: 이전 시간대 대비 정확한 증감 문구와 좌우/위아래 요약 카드 위치 계산.
- css/pages/result.css: 이미지의 남색·블루그레이 카드 스타일, PC 4열/태블릿·모바일 2열,
  화면 폭에 따라 결과 영역을 1열로 전환. 모바일 요약 카드는 그래프 아래 배치한다.
- tests/duration-graph.test.mjs: 선택 동기화, 토글·외부 닫기·이벤트 정리·모바일 분기·증감·실제 카드 수치 회귀 검증 추가.

HTML 마크업은 기존 result.html의 컨테이너 안에 JS가 생성한다. 별도 결과 화면은 만들지 않았다.
API·검색·지도·인증·백엔드·DB·.env는 이번 UI 작업에서 변경하지 않았다.

## 사용 방법

그래프 동그라미를 클릭하거나 Enter/Space로 선택하면 요약 카드가 열린다.
같은 점을 다시 선택하거나 닫기 버튼, Escape, 그래프/표 바깥을 클릭하면 닫힌다.
표 행을 선택하면 같은 인덱스의 점과 표 행 하나만 강조하며 요약 카드도 갱신한다.
표 펼침/접힘은 네이티브 details/summary로 동작하며 아이콘도 방향을 바꾼다.

비교값은 유효한 데이터를 시간순으로 정렬한 직전 데이터와의 차이다.
46 → 54분은 8분 증가, 54 → 51분은 3분 단축, 같은 값은 동일,
첫 데이터는 비교 대상 없음으로 표시한다. 지점 선택은 권장 출발 시각을 변경하지 않는다.
실제 모드에서는 API 응답값을 그대로 표시한다. 비용 누락은 미제공이고 0원과 구분한다.
예시 모드에서는 테스트용 예시 표시를 유지한다. 실제 그래프 API는 여전히 연동 대기다.

## 실행

VS Code에서 /private/tmp/gilit-duration-graph를 폴더로 열고 터미널에서:

```sh
cd /private/tmp/gilit-duration-graph
python3 frontend/tests/serve-duration-preview.py --port 5502
```

http://127.0.0.1:5502/pages/search.html 접속 → 김해시청/동의대학교 선택 → 미래 도착 시각 검색.
이미 5502 서버가 실행 중이면 그대로 접속한 뒤 Cmd+Shift+R로 새로고침한다.
이 서버는 예시 데이터 전용이다. 기존 8003 서버는 원래 로그인 작업 폴더이므로 새 UI가 표시되지 않는다.

## 검증

Node REPL에서 duration-graph/search/map/routes 4개 테스트 모듈 통과.
셸에서 Node.js를 사용할 수 있으면 다음과 같이 재실행한다:

```sh
node frontend/tests/duration-graph.test.mjs
node frontend/tests/search.test.mjs
node frontend/tests/map.test.mjs
node frontend/tests/routes.test.mjs
```

검증 범위: 실제 카드 수치·도착 시각·여유시간·비용 누락, 그래프/표 단일 선택,
요약 카드 토글·외부/키보드 닫기, 증감/첫 데이터, 좌우·상하 경계 및 모바일 위치 분기,
경로 변경·이벤트 정리, 기존 지도/검색/경로 데이터 회귀. UI 상호작용은 모의 DOM 검증이다.
git diff --check 통과.

실제 브라우저 검증은 Chrome 제어 중 사용자 화면 전환으로 중단되어 완료하지 못했다.
이미지와의 최종 시각 비교, 네이티브 details 조작, 실제 모바일 터치/레이아웃,
실제 카카오 타일 및 OAuth 인증은 미검증이다. 로그인 코드는 이번 작업에서 변경하지 않았다.

## 크기·간격 후속 조정

- 권장 출발: PC 38px / 모바일 32px. 경로명 아래 라벨 간격 8px(모바일 6px),
  정보 카드 위 간격 12px로 축소. 도착 영역·정보 아이콘·색상·계산은 유지.
- 요약 카드: 폭 250px, 모서리 12px, 내부 12~13px, 소요시간 28px.
  선택 지점의 실제 화면 좌표에 맞춘 꼬리 추가. 화면 경계에 따라 좌/우를 전환하고
  세로 위치를 제한한다. 모바일은 그래프 아래에 표시하며 꼬리를 숨긴다.
  표 또는 요약 카드에 키보드 초점이 있어도 Escape로 닫힌다.
- 데이터 목록: 제목 PC 17px, 행 최소 높이 52px, 시각/배지 14px, 아이콘 16px,
  행 간격 6px, 내부 12px로 축소. 모바일은 내용이 길면 행 높이를 자연스럽게 늘린다.
- 후속 수정 파일: css/pages/result.css, js/components/charts.js,
  js/components/durationGraph.js, tests/duration-graph.test.mjs 및 이 문서.
- 그래프/표/키보드/경로 전환 모의 DOM, 꼬리 좌표와 상하 경계,
  기존 검색·지도·경로 테스트 통과. PC/모바일 실제 렌더링과 실기기 터치는 미검증.

## 브라우저 갱신 보완

실제 열린 탭이 5502임을 확인했다. 주소 문제라는 이전 안내는 잘못이었다.
result.html의 CSS/페이지 JS와 그래프 모듈 의존성에 버전 쿼리를 추가했다.
미리보기 서버를 새 스크립트로 재시작하고 모든 응답에 no-store를 적용했다.
미래 If-Modified-Since 요청도 200과 최신 본문을 반환하는 것을 확인했다.
기존 탭을 직접 새로고침하고 결과 화면을 캡처했으나 브라우저 검사 도구 오류로
정확한 계산 스타일 수치 및 말풍선의 최종 시각 확인은 완료하지 못했다.

## 최종 2개 영역 조정 — 실제 Chrome 검증

PC 부모 그리드 330px → 600px, 페이지 최대 폭 1240px → 1440px.
카드 내부 padding·출발 글꼴·아이콘·도착 영역은 유지했고 정보 카드를 4열로 바꿨다.
1100px 이하는 좌우 영역을 세로 배치하고 640px 이하는 정보 카드 2열로 표시한다.
말풍선은 디자인·테두리·꼬리·색상·내용 순서를 유지하고 320px → 290px로 줄였다.
중앙 여백 12px → 8px, 소요시간 30px → 28px, 본문 padding 14/16px → 10/12px.
데이터 표 스타일과 API/계산/지도 코드는 변경하지 않았다.

Chrome의 tests/result-layout.html에서 같은 iframe 폭으로 실제 DOM을 전후 측정했다.
1440/1280px: 경로 카드 330×331 → 600×273px, 말풍선 320×212 → 290×178px.
1024px: 세로 배치·정보 4열, 390px: 정보 2열·카드 높이 341px 유지.
모든 폭에서 페이지/정보 카드/말풍선 가로 넘침 없음. 표 행 높이 42px 유지.
클릭 선택·같은 점 닫기·X 닫기·바깥 닫기·표 연동·다른 경로 갱신을 브라우저에서 검증했다.
마지막 지점 말풍선도 차트 가로 경계 안에 있음을 확인했다.
실제 결과 탭에서 08:00 지점을 직접 클릭하고 최종 화면도 캡처했다.
상세 수치: result-layout-verification.json. 기존 4개 Node 테스트도 통과.
실제 지도 타일·소셜 인증·교통 그래프 API는 이번에 다시 검증하지 않았다.

추가 파일: tests/result-layout.html(브라우저 측정), tests/serve-duration-preview.py(측정 결과 수신),
docs/result-layout-verification.json(측정 기록). 테스트 서버 변경은 frontend/tests에만 있다.

## 정확한 고정 크기 적용

데스크톱 그리드: 600px minmax(0, 1fr). 카드 자체 높이는 기존 auto 유지.
말풍선: border-box, width 250px, height 160px. 내부 padding 8px 10px,
간격 5~6px, 소요시간 26px로 조절했다. 색상·아이콘·배지·구분선·꼬리는 유지.
다른 경로 카드의 내부 폰트와 데이터 표 규칙은 변경하지 않았다.
HTML/JS 모듈의 버전 쿼리만 fixed-20261114-5로 갱신했다.

실제 Chrome getBoundingClientRect 결과:
- 1440/1280px: 모든 경로 카드 width=600px, height 약273px, 정보 4열.
- 1024px: 카드 984px로 세로 배치. 390px: 카드 362px, 정보 2열.
- 모든 폭에서 말풍선 250×160px 정확히 일치.
- 가로/세로 overflow 및 글씨·아이콘의 경계 초과 없음.
- 꼬리와 선택한 점의 Y좌표 오차 1px 미만, 마지막 점도 차트 가로 범위 내.
- 열기·같은 점 닫기·X·외부 닫기·표 선택 연동·경로 전환 통과.
- 표 행 높이 42px 그대로. 기존 4개 Node 테스트 모듈 통과.

실측 원본: result-fixed-size-verification.json.
검증은 예시 데이터로 수행했으며 실제 카카오 타일/교통 API를 재검증하지 않았다.
이번 수정 파일: result.css, result.html·result.js·charts.js(버전 쿼리),
tests/result-layout.html(잘림/전체 카드/꼬리 측정 추가), 문서 및 측정 JSON.

## 경로 카드 530px 조정

높이는 auto 유지. 실제 Chrome 1440/1280px에서 세 카드 모두 530×242.3px.
기존 600×273.3px에서 폭 70px·높이 약31px 감소. 목표 약241px에 근접한다.
카드 padding 14→10px, 정보 카드 최소 높이52→48px 및 주변 margin/gap 축소.
권장 출발 글꼴38px·색상·아이콘·배경·도착 영역 디자인은 유지했다.
숫자/단위에는 nowrap을 적용해 줄바꿈을 방지했다.
1024px에서는 카드984px로 세로 배치, 390px에서는 카드362px·2열.
실제 DOM에서 값4개 모두 한 줄, 글씨/아이콘 잘림 및 가로 넘침 없음.
말풍선250×160px, 표 행42px 유지. 열기/닫기·표 연동·경로 전환 통과.
기존 검색/지도/경로 및 그래프 Node 테스트4개 통과. 상세: result-card530-verification.json.
이번 변경: result.css, result.html/result.js/charts.js의 버전 쿼리,
tests/result-layout.html의 숫자 줄바꿈/아이콘 검사, 이 문서·실측 JSON.
백엔드/DB/API 및 기존 미커밋 작업은 보존했다.
