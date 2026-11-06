import { KAKAO_JS_KEY } from "/js/config.js";

export const ROUTE_COLORS = ["#2563EB", "#16A36A", "#F59E0B"];
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/;

// innerHTML에 넣는 외부 값(쿼리, 입력, API 응답)은 반드시 거친다.
export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);
}

export function toDateString(date = new Date()) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function parseDate(dateString) {
  const [year, month, day] = dateString.split("-").map(Number);
  return new Date(year, month - 1, day);
}

export function isValidDate(value) {
  return DATE_PATTERN.test(value ?? "") && toDateString(parseDate(value)) === value;
}

export function isValidTime(value) {
  return TIME_PATTERN.test(value ?? "");
}

export function daysFrom(dateString, days) {
  const date = parseDate(dateString);
  date.setDate(date.getDate() + days);
  return toDateString(date);
}

// "5월 22일 (목)"
export function formatFullDate(dateString) {
  const date = parseDate(dateString);
  return `${date.getMonth() + 1}월 ${date.getDate()}일 (${WEEKDAYS[date.getDay()]})`;
}

// "5/22 목"
export function formatShortDate(dateString) {
  const date = parseDate(dateString);
  return `${date.getMonth() + 1}/${date.getDate()} ${WEEKDAYS[date.getDay()]}`;
}

// "오늘", "어제", "5월 20일"
export function formatRelativeDate(dateString) {
  const today = toDateString();
  if (dateString === today) return "오늘";
  if (dateString === daysFrom(today, -1)) return "어제";
  const date = parseDate(dateString);
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
}

// 브라우저/운영체제 시간대와 무관하게 서비스의 한국 시간을 사용한다.
export function koreaDateTime(now = new Date()) {
  const iso = new Date(now.getTime() + 9 * 60 * 60000).toISOString();
  return { date: iso.slice(0, 10), time: iso.slice(11, 16) };
}

// 최근 검색은 같은 시각의 다음 도착일을 사용한다. 현재 분은 이미 지난 것으로 본다.
export function nextDateForTime(time, now = new Date()) {
  const today = koreaDateTime(now);
  return time > today.time ? today.date : daysFrom(today.date, 1);
}

// 검색 폼과 다른 진입 경로에서 함께 사용하는 검사. 직접 입력한 장소명도 허용한다.
export function validateSearchConditions({ from, to, date, time, buffer }, now = new Date()) {
  if (!from?.trim()) return { field: "from", message: "출발지를 입력해 주세요" };
  if (!to?.trim()) return { field: "to", message: "목적지를 입력해 주세요" };
  if (from.trim() === to.trim()) return { field: "to", message: "출발지와 다른 목적지를 입력해 주세요" };
  if (!isValidDate(date)) return { field: "date", message: "올바른 도착 날짜를 입력해 주세요" };
  if (!isValidTime(time)) return { field: "time", message: "올바른 도착 시각을 입력해 주세요" };
  if (Date.parse(toIsoTime(date, time)) <= now.getTime()) {
    return { field: date < koreaDateTime(now).date ? "date" : "time", message: "현재보다 늦은 도착 시각을 선택해 주세요" };
  }
  if (!["0", "5", "10", "15"].includes(String(buffer))) return { field: "buffer", message: "여유시간을 다시 선택해 주세요" };
  return null;
}

// ISO 8601 시각 문자열("2026-11-02T08:50:00+09:00")을 다룬다. 표시는 문자열의 현지 시각 기준이다.
export function toIsoTime(date, time) {
  return `${date}T${time}:00+09:00`;
}

export function timeOf(iso) {
  return iso.slice(11, 16);
}

export function dateOf(iso) {
  return iso.slice(0, 10);
}

export function addMinutes(iso, minutes) {
  const shifted = new Date(Date.parse(`${iso.slice(0, 19)}Z`) + minutes * 60000);
  return `${shifted.toISOString().slice(0, 19)}${iso.slice(19)}`;
}

export function minutesBetween(fromIso, toIso) {
  return (Date.parse(toIso) - Date.parse(fromIso)) / 60000;
}

export function formatWon(amount) {
  return `${amount.toLocaleString("ko-KR")}원`;
}

export function formatBuffer(minutes) {
  return minutes > 0 ? `${minutes}분` : "없음";
}

export function buildResultUrl({ from, to, date, time, buffer, ...coordinates }) {
  const params = { from, to, date, time, buffer };
  for (const key of ["fromLat", "fromLng", "toLat", "toLng"]) {
    if (coordinates[key] !== undefined && coordinates[key] !== null) params[key] = coordinates[key];
  }
  return `/pages/result.html?${new URLSearchParams(params)}`;
}

let kakaoMapPromise = null;

function kakaoSdkError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

// Error 객체/stack에는 SDK URL과 키가 포함될 수 있어 정리한 필드만 로그에 전달한다.
export function getKakaoMapErrorDetails(error, stage) {
  const redact = (value) => {
    let text = String(value ?? "");
    const key = KAKAO_JS_KEY.trim();
    if (key) {
      text = text.split(encodeURIComponent(key)).join("[REDACTED]");
      text = text.split(key).join("[REDACTED]");
    }
    return text.replace(/([?&](?:appkey|app_key|apikey|key)=)[^&#\s"'<>]+/gi, "$1[REDACTED]");
  };
  const codes = ["SDK_REQUEST_FAILED", "SDK_DOWNLOAD_TIMEOUT", "SDK_INITIALIZATION_TIMEOUT", "SDK_INVALID_RESPONSE", "SDK_INITIALIZATION_FAILED"];
  return {
    stage,
    code: codes.includes(error?.code) ? error.code : stage === "map-render" ? "MAP_RENDER_FAILED" : "SDK_LOAD_FAILED",
    name: redact(error?.name || "Error"),
    message: redact(error?.message || "원인을 확인할 수 없는 오류"),
  };
}

// 카카오맵 SDK를 동적으로 로드한다. 키가 비어 있으면 로드하지 않고 null을 돌려준다.
export function loadKakaoMapSdk() {
  if (!KAKAO_JS_KEY.trim()) return Promise.resolve(null);
  if (kakaoMapPromise) return kakaoMapPromise;

  kakaoMapPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    let settled = false;
    let stage = "download";
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      script.onload = script.onerror = null;
      if (error) { script.remove(); reject(error); }
      else resolve(window.kakao);
    };
    const timer = setTimeout(() => finish(kakaoSdkError(
      stage === "download" ? "SDK_DOWNLOAD_TIMEOUT" : "SDK_INITIALIZATION_TIMEOUT",
      stage === "download" ? "카카오맵 SDK 다운로드 시간 초과 (10초)" : "카카오맵 SDK 초기화 시간 초과 (10초)"
    )), 10000);
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(KAKAO_JS_KEY.trim())}&autoload=false`;
    script.onload = () => {
      if (settled) return;
      stage = "initialize";
      try {
        if (!window.kakao?.maps?.load) {
          finish(kakaoSdkError("SDK_INVALID_RESPONSE", "카카오맵 SDK 응답에 maps.load가 없어요."));
          return;
        }
        window.kakao.maps.load(() => {
          if (settled) return;
          try {
            finish(typeof window.kakao?.maps?.Map === "function" ? null
              : kakaoSdkError("SDK_INITIALIZATION_FAILED", "카카오맵 SDK 초기화 후 Map 생성자가 없어요."));
          } catch (error) { finish(error); }
        });
      } catch (error) {
        finish(kakaoSdkError("SDK_INITIALIZATION_FAILED", error?.message || "카카오맵 SDK 초기화 실패"));
      }
    };
    // 교차 출처 script.onerror로는 HTTP 상태나 본문을 읽을 수 없다. 단정하지 않는다.
    script.onerror = () => finish(kakaoSdkError("SDK_REQUEST_FAILED", "카카오맵 SDK 로드 실패. Network에서 인증·도메인·차단 여부를 확인해 주세요."));
    document.head.appendChild(script);
  }).catch((error) => {
    kakaoMapPromise = null;
    throw error;
  });
  return kakaoMapPromise;
}
