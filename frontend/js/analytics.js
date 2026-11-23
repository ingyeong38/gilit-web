import { GA4_MEASUREMENT_ID } from "/js/config.js";

const pagePaths = new Set([
  "/", "/index.html", "/pages/search.html", "/pages/result.html",
  "/pages/favorites.html", "/pages/mypage.html", "/pages/stats.html",
]);

const { pathname, origin } = window.location;
if (/^G-[A-Z0-9]+$/.test(GA4_MEASUREMENT_ID) && pagePaths.has(pathname) && !window.gtag) {
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };

  // 공유 링크의 검색 쿼리, 인증 콜백 파라미터 및 원래 referrer를 보내지 않는다.
  const page = {
    page_location: origin + (pathname === "/" ? "/index.html" : pathname),
    page_referrer: origin + "/",
    ignore_referrer: true,
  };
  window.gtag("js", new Date());
  window.gtag("config", GA4_MEASUREMENT_ID, {
    ...page,
    send_page_view: false,
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
  });
  window.gtag("event", "page_view", { ...page, send_to: GA4_MEASUREMENT_ID });

  const script = document.createElement("script");
  script.async = true;
  script.referrerPolicy = "no-referrer";
  script.src = `https://www.googletagmanager.com/gtag/js?id=${GA4_MEASUREMENT_ID}`;
  document.head.append(script);
}
