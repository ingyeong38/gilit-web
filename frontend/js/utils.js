import { KAKAO_JS_KEY } from "/js/config.js";

let kakaoMapPromise = null;

// 카카오맵 SDK를 동적으로 로드한다. 키가 비어 있으면 로드하지 않고 null을 돌려준다.
export function loadKakaoMapSdk() {
  if (!KAKAO_JS_KEY) return Promise.resolve(null);
  if (kakaoMapPromise) return kakaoMapPromise;

  kakaoMapPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(KAKAO_JS_KEY)}&autoload=false`;
    script.onload = () => window.kakao.maps.load(() => resolve(window.kakao));
    script.onerror = () => {
      kakaoMapPromise = null;
      reject(new Error("카카오맵 SDK 로드 실패"));
    };
    document.head.appendChild(script);
  });
  return kakaoMapPromise;
}
