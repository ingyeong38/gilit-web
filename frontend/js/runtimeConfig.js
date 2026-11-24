// 서버 공개 설정(GET /api/config)과 config.js 값을 합친 런타임 설정. 페이지당 한 번만 서버에 묻는다.
// 지도(components/map.js)와 GA(analytics.js)가 같은 결과를 공유하므로 이 모듈의 import에는 ?v=를 붙이지 않는다.
// 값마다 서버 값이 있으면 그 값을, 비어 있으면 config.js 값을 쓴다 (로컬 개발용). 둘 다 비면 빈 문자열.
import { getRuntimeConfig, normalizeRuntimeConfig } from "/js/api.js";
// 이름 import는 config.js에 그 이름이 없으면 모듈 전체가 실패한다. 개발자마다 config.js가 다를 수 있어 네임스페이스로 읽는다.
import * as localConfig from "/js/config.js";

let runtimeConfig = null;

export function resolveRuntimeConfig(server, local) {
  const fromServer = normalizeRuntimeConfig(server);
  const fromLocal = normalizeRuntimeConfig(local);
  return Object.freeze({
    kakaoJsKey: fromServer.kakaoJsKey || fromLocal.kakaoJsKey,
    ga4MeasurementId: fromServer.ga4MeasurementId || fromLocal.ga4MeasurementId,
  });
}

// 실패하지 않는다 (서버 오류는 config.js 값 또는 빈 값으로).
export function loadRuntimeConfig() {
  runtimeConfig ??= getRuntimeConfig()
    .catch(() => null)
    .then((server) => resolveRuntimeConfig(server, {
      kakaoJsKey: localConfig.KAKAO_JS_KEY,
      ga4MeasurementId: localConfig.GA4_MEASUREMENT_ID,
    }));
  return runtimeConfig;
}
