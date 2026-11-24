// GA4 페이지 조회 수집. 측정 ID는 js/runtimeConfig.js에서 받는다 (서버 GET /api/config → 없으면 config.js).
// 측정 ID가 비어 있거나 형식이 틀리면 아무것도 하지 않는다 (gtag를 불러오지 않는다).
// 모든 화면의 header.js가 import "/js/analytics.js"로 불러온다. 설정을 기다리는 동안 헤더 렌더링을 막지 않게 비동기로 시작한다.
import { loadRuntimeConfig } from "/js/runtimeConfig.js";

const pagePaths = new Set([
  "/", "/index.html", "/pages/search.html", "/pages/result.html",
  "/pages/favorites.html", "/pages/mypage.html", "/pages/stats.html",
]);

// 수집을 시작했으면 true. 이미 시작했거나(window.gtag) 대상 화면이 아니면 false.
export function startAnalytics(measurementId) {
  const { pathname, origin } = window.location;
  if (typeof measurementId !== "string" || !/^G-[A-Z0-9]+$/.test(measurementId) || !pagePaths.has(pathname) || window.gtag) {
    return false;
  }
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };

  // 공유 링크의 검색 쿼리, 인증 콜백 파라미터 및 원래 referrer를 보내지 않는다.
  const page = {
    page_location: origin + (pathname === "/" ? "/index.html" : pathname),
    page_referrer: origin + "/",
    ignore_referrer: true,
  };
  window.gtag("js", new Date());
  window.gtag("config", measurementId, {
    ...page,
    send_page_view: false,
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
  });
  window.gtag("event", "page_view", { ...page, send_to: measurementId });

  const script = document.createElement("script");
  script.async = true;
  script.referrerPolicy = "no-referrer";
  script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(measurementId)}`;
  document.head.append(script);
  return true;
}

export const analyticsReady = loadRuntimeConfig()
  .then(({ ga4MeasurementId }) => startAnalytics(ga4MeasurementId))
  .catch(() => false);
