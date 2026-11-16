export const USE_MOCK = true;
// 장소 검색·경로 조회 모드만 제어한다. 로그인·즐겨찾기 등의 모드와 분리.
export const USE_MOCK_ROUTES = false;
export const BASE_URL = "/api";
// 브라우저에 노출되는 키. 실제 값을 넣은 채로 커밋하지 않는다.
export const KAKAO_JS_KEY = "";

// SFR-006: /api/routes/graph 구현 및 계약 확인 후 true로 전환한다.
export const GRAPH_API_ENABLED = false;

// SFR-001: 백엔드 담당자와 시작 경로를 합의한 뒤 같은 출처 URL을 입력한다.
// 예시 경로를 실제 API로 간주하지 않도록 기본값은 비워 둔다.
export const SOCIAL_AUTH_START_URLS = { google: "", kakao: "" };

// 자동차 경로 설정과 독립: API가 없으면 로컬 개발 환경에서만 기존 예시 표시.
export const GRAPH_DATA_SOURCE = "auto";
