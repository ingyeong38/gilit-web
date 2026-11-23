export const USE_MOCK = false;
// 사이트 전체 통계 개발용 예시. 기본값은 실제 API.
export const USE_MOCK_STATS = false;
// GA4 웹 스트림의 공개 측정 ID. 빈 값이면 수집하지 않는다.
export const GA4_MEASUREMENT_ID = "";
// 장소 검색·경로 조회 모드만 제어한다. 로그인·즐겨찾기 등의 모드와 분리.
export const USE_MOCK_ROUTES = false;
export const BASE_URL = "/api";
// 브라우저에 노출되는 키. 실제 값을 넣은 채로 커밋하지 않는다.
export const KAKAO_JS_KEY = "";

// SFR-006: /api/routes/graph 구현 및 계약 확인 후 true로 전환한다.
export const GRAPH_API_ENABLED = false;

// 백엔드와 같은 출처의 소셜 로그인 시작 경로.
export const SOCIAL_AUTH_START_URLS = {
  google: "/api/auth/google/start",
  kakao: "/api/auth/kakao/start",
};

// 자동차 경로 설정과 독립: API가 없으면 로컬 개발 환경에서만 기존 예시 표시.
export const GRAPH_DATA_SOURCE = "auto";
