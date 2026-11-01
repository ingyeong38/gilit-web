# 길잇 (Gilit)

도착 희망 시각을 입력하면 경로별 권장 출발시각을 알려주는 자동차 길찾기 웹. 프론트 인경, 백엔드 해민.

## 폴더 구조

- `frontend/`: 서버 루트. `index.html`, `pages/`, `css/`, `js/`, `assets/`
- `frontend/js/`: `config.js`, `api.js`, `auth.js`, `utils.js`, `components/`, `pages/`, `mock/`
- `frontend/js/components/map.js`: 지금은 가짜 SVG 지도. 카카오맵 교체 시 `renderRouteMap`만 바꾼다
- `docs/design-reference/`: Figma Make 원본 (참고용, 빌드에 쓰지 않음)
- `backend/`: 언어·프레임워크 미정. 해민 담당
- `docs/api-spec.md`: API 명세 가안

## 규칙

- 순수 HTML/CSS/JS만 쓴다. 프레임워크와 npm은 쓰지 않고, 외부 라이브러리는 CDN으로 불러온다.
- 스크립트는 `type="module"`을 쓴다. 차트는 라이브러리 없이 SVG로 그린다 (`components/charts.js`).
- 경로는 루트 절대경로(`/css/...`, `/js/...`)로 쓴다.
- 서버 호출은 `js/api.js`에만 둔다.
- 쿼리·입력·API 응답을 `innerHTML`에 넣을 때는 `escapeHtml`을 거친다. 공유 링크의 쿼리가 화면에 출력된다.
- 검색 조건은 URL 쿼리(`from`, `to`, `date`, `time`, `buffer`)로 전달한다.
- 로그인은 임시 구현이다 (`js/auth.js`, localStorage).
- 목업 우선: `USE_MOCK = true`이면 `js/mock/*.json`으로 동작한다. 서버 없이 화면을 개발할 수 있어야 한다.
- API 필드를 바꾸면 `js/mock/*.json`과 `docs/api-spec.md`를 함께 고친다.
- 비밀 키를 커밋하지 않는다. `.env`는 커밋 금지이고 `.env.example`에는 값을 넣지 않는다. `config.js`의 `KAKAO_JS_KEY`도 빈 값으로 커밋한다.
