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

// 해당 시각이 오늘 이미 지났으면 내일 날짜를 돌려준다.
export function nextDateForTime(time) {
  const now = new Date();
  const nowTime = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  const today = toDateString(now);
  return time > nowTime ? today : daysFrom(today, 1);
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

export function buildResultUrl({ from, to, date, time, buffer }) {
  return `/pages/result.html?${new URLSearchParams({ from, to, date, time, buffer })}`;
}

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
