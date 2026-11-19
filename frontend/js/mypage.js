// 마이페이지의 데이터와 계산. 화면 연결은 js/pages/mypage.js가 한다.
// 이번 범위는 화면과 mock 데이터까지다. 서버 연결 지점은 아래 TODO에 있다 (서버 호출은 js/api.js에만 둔다).
import { USE_MOCK_STATS } from "/js/config.js";

const DAY_MS = 24 * 60 * 60 * 1000;
const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

// --- 닉네임 ---

// 닉네임 규칙 (다음 작업의 서버 검증도 이 문장 그대로 같은 규칙을 쓴다)
// - 앞뒤 공백 제거 후 길이 2~20자
// - 허용 문자: 한글 완성형(가-힣), 영문(A-Za-z), 숫자(0-9), 공백(스페이스), 특수문자 - _ ! # (이 4개만)
// - 한글·영문·숫자 중 최소 1자를 포함해야 한다(특수문자와 공백만으로 이루어진 값 불허)
// - 불허: 위 외의 모든 문자(. @ / < > & ' " 등 특수문자, 이모지, 한글 자모 단독 ㄱ-ㅎ·ㅏ-ㅣ, 탭·줄바꿈 등 스페이스 이외의 공백 문자)
// - 중간 공백은 단일 공백만 허용(연속 공백 불허)
// - 빈 값 불가, 현재 닉네임과 같으면 저장 불가
// - 규칙은 변경 시에만 검사한다(현재 표시 중인 닉네임에는 적용하지 않는다)
// - 중복은 허용한다
export const NICKNAME_RULES = Object.freeze({ minLength: 2, maxLength: 20 });
// 허용 문자 전체 (스페이스는 U+0020만. 탭·줄바꿈·전각 공백은 여기에 없으므로 불허)
export const NICKNAME_ALLOWED_PATTERN = /^[가-힣A-Za-z0-9 \-_!#]+$/;
// 반드시 1자 이상 포함해야 하는 문자 (한글 완성형·영문·숫자)
export const NICKNAME_REQUIRED_PATTERN = /[가-힣A-Za-z0-9]/;
export const NICKNAME_CONSECUTIVE_SPACES = / {2,}/;
export const NICKNAME_HELP_TEXT = "한글, 영문, 숫자, 공백, - _ ! # 사용 가능 (2~20자)";
export const NICKNAME_MESSAGES = Object.freeze({
  empty: "닉네임을 입력해 주세요.",
  length: `닉네임은 ${NICKNAME_RULES.minLength}~${NICKNAME_RULES.maxLength}자로 입력해 주세요.`,
  invalidChar: "사용할 수 없는 문자가 있어요. 한글, 영문, 숫자, 공백, - _ ! #만 쓸 수 있어요.",
  consecutiveSpaces: "공백은 한 칸씩만 쓸 수 있어요.",
  needLetter: "한글, 영문, 숫자를 1자 이상 포함해 주세요.",
  same: "현재 닉네임과 같아요.",
});

// 길이는 앞뒤 공백을 뺀 글자 수로 센다 (허용 문자는 모두 한 글자가 한 칸이다).
export function nicknameLength(value) {
  return [...String(value ?? "").trim()].length;
}

// { ok, value(앞뒤 공백 제거), code, message }. 검사 순서: 빈 값 → 허용 문자 → 연속 공백 → 길이 → 한글·영문·숫자 포함 → 현재와 같음.
// code: "empty" | "invalidChar" | "consecutiveSpaces" | "length" | "needLetter" | "same" | ""
export function validateNickname(value, { current = "" } = {}) {
  const nickname = typeof value === "string" ? value.trim() : "";
  const fail = (code) => ({ ok: false, value: nickname, code, message: NICKNAME_MESSAGES[code] });
  const length = [...nickname].length;
  if (!length) return fail("empty");
  if (!NICKNAME_ALLOWED_PATTERN.test(nickname)) return fail("invalidChar");
  if (NICKNAME_CONSECUTIVE_SPACES.test(nickname)) return fail("consecutiveSpaces");
  if (length < NICKNAME_RULES.minLength || length > NICKNAME_RULES.maxLength) return fail("length");
  if (!NICKNAME_REQUIRED_PATTERN.test(nickname)) return fail("needLetter");
  if (nickname === String(current ?? "").trim()) return fail("same");
  return { ok: true, value: nickname, code: "", message: "" };
}

// 닉네임 저장. 성공하면 저장된 닉네임을 돌려주고, 실패하면 { message }가 있는 오류를 던진다.
// TODO(닉네임 저장): js/api.js에 닉네임 변경 API(예: PATCH /api/auth/me { name })를 추가해 호출하고,
//   성공하면 auth.js setUser로 헤더까지 갱신한다. API 명세(docs/api-spec.md)와 검증 규칙(NICKNAME_RULES)은 백엔드와 확정한다.
export async function saveNickname(nickname) {
  await new Promise((resolve) => setTimeout(resolve, 400)); // 저장 중 상태를 보이기 위한 mock 지연
  return nickname;
}

// --- 로그인 제공자 ---

export function providerLabel(provider) {
  return { google: "Google 계정으로 이용 중", kakao: "카카오 계정으로 이용 중", email: "이메일로 이용 중" }[provider] ?? "길잇 계정으로 이용 중";
}

export function avatarInitial(name) {
  return [...String(name ?? "").trim()][0] ?? "길";
}

// --- 즐겨찾기 ---

export const MAX_MYPAGE_FAVORITES = 3;
export const MISSING_ADDRESS_TEXT = "주소 정보 없음";

const MOCK_FAVORITES = [
  { id: "mock-1", name: "집", type: "집", address: "경상남도 김해시 내외중앙로 47", lat: 35.2342, lng: 128.8811 },
  { id: "mock-2", name: "동의대학교", type: "학교", address: "부산광역시 부산진구 엄광로 176", lat: 35.1441, lng: 129.0336 },
  { id: "mock-3", name: "센텀시티 오피스", type: "회사", address: "부산광역시 해운대구 센텀중앙로 90", lat: 35.1691, lng: 129.1311 },
  { id: "mock-4", name: "부산역", type: "기타", address: null, lat: 35.1151, lng: 129.0422 },
];

// TODO(즐겨찾기 조회): js/api.js의 getFavorites()(GET /api/favorites)로 바꾼다. 응답 형식은 같다 ({ id, name, type, address, lat, lng }).
export async function loadFavorites() {
  return MOCK_FAVORITES.map((place) => ({ ...place }));
}

function isCoordinate(value, limit) {
  return typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= limit;
}

// 카드에 쓸 값. 주소가 없거나("null" 문자열 포함) 비면 대체 문구, 좌표는 둘 다 올바를 때만 남긴다.
export function favoriteCardModel(place = {}) {
  const name = typeof place.name === "string" && place.name.trim() ? place.name.trim() : "이름 없는 장소";
  const rawAddress = typeof place.address === "string" ? place.address.trim() : "";
  const hasAddress = Boolean(rawAddress) && rawAddress.toLowerCase() !== "null";
  const located = isCoordinate(place.lat, 90) && isCoordinate(place.lng, 180);
  return {
    id: place.id == null ? "" : String(place.id),
    name,
    type: typeof place.type === "string" ? place.type : "기타",
    address: hasAddress ? rawAddress : "",
    addressText: hasAddress ? rawAddress : MISSING_ADDRESS_TEXT,
    hasAddress,
    lat: located ? place.lat : null,
    lng: located ? place.lng : null,
  };
}

export function pickFavorites(list, limit = MAX_MYPAGE_FAVORITES) {
  return (Array.isArray(list) ? list : []).slice(0, limit).map(favoriteCardModel);
}

// --- 주간 이용 통계 (최근 7일, KST, 오늘 포함) ---

export function kstDateKey(date) {
  return new Date(date.getTime() + KST_OFFSET_MS).toISOString().slice(0, 10);
}

// 오래된 날부터 오늘 순. [{ date: "YYYY-MM-DD", weekday: "월", month, day }]
export function lastSevenDays(now = new Date()) {
  return Array.from({ length: 7 }, (_, index) => {
    const shifted = new Date(now.getTime() + KST_OFFSET_MS - (6 - index) * DAY_MS);
    return {
      date: shifted.toISOString().slice(0, 10),
      weekday: WEEKDAYS[shifted.getUTCDay()],
      month: shifted.getUTCMonth() + 1,
      day: shifted.getUTCDate(),
    };
  });
}

function toCount(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : 0;
}

// daily: [{ date: "YYYY-MM-DD", count }] (순서·누락 상관없음). 최근 7일 밖의 날짜는 버리고, 없는 날은 0.
export function buildWeeklySeries(daily, now = new Date()) {
  const counts = new Map();
  for (const item of Array.isArray(daily) ? daily : []) {
    if (item && typeof item.date === "string") counts.set(item.date, (counts.get(item.date) ?? 0) + toCount(item.count));
  }
  return lastSevenDays(now).map((day) => ({ ...day, count: counts.get(day.date) ?? 0 }));
}

export function weeklyTotal(series) {
  return (Array.isArray(series) ? series : []).reduce((sum, day) => sum + toCount(day?.count), 0);
}

// 막대 높이 기준값(px, 배율 1). 화면에서는 이 값에 대한 비율만 쓰고 실제 높이는 CSS(--my-s 배율)가 정한다.
export const BAR_MAX_HEIGHT = 77;

// 막대 높이(px). 가장 큰 값이 maxHeight, 0회는 0(빈 막대), 1회 이상은 최소 minHeight.
export function barHeights(series, { maxHeight = BAR_MAX_HEIGHT, minHeight = 6 } = {}) {
  const counts = (Array.isArray(series) ? series : []).map((day) => toCount(day?.count));
  const max = Math.max(0, ...counts);
  return counts.map((count) => (count && max ? Math.max(minHeight, Math.round((count / max) * maxHeight)) : 0));
}

// "11월 13일 ~ 11월 19일" (최근 7일 범위, KST)
export function periodLabel(series) {
  const days = Array.isArray(series) && series.length ? series : lastSevenDays();
  const first = days[0], last = days.at(-1);
  return `${first.month}월 ${first.day}일 ~ ${last.month}월 ${last.day}일`;
}

export function weeklySummary(stats = {}, now = new Date()) {
  const series = buildWeeklySeries(stats.daily, now);
  const total = weeklyTotal(series);
  const topPlace = total && typeof stats.topPlace === "string" && stats.topPlace.trim() ? stats.topPlace.trim() : null;
  return { series, total, topPlace, heights: barHeights(series), period: periodLabel(series), empty: total === 0 };
}

// mock: 오늘 기준 최근 7일 (날짜는 실행 시점에 만든다). 마지막 값이 오늘이다.
const MOCK_WEEKLY_COUNTS = [4, 7, 5, 9, 6, 11, 8];

// 기존 통계 화면처럼 USE_MOCK_STATS로 mock과 실제를 나눈다 (stats.js → api.getStats와 같은 기준).
// TODO(통계 API): 사용자별 주간 통계 API(예: GET /api/me/stats?days=7 → { daily: [{ date, count }], topPlace })를
//   js/api.js에 추가하고 USE_MOCK_STATS가 false일 때 그것을 호출한다. "가장 많이 간 곳"의 기준(목적지 이름)도 함께 확정한다.
export async function loadWeeklyStats(now = new Date()) {
  if (!USE_MOCK_STATS) throw Object.assign(new Error("이용 통계는 아직 서버와 연결되지 않았어요."), { status: 501 });
  return {
    daily: lastSevenDays(now).map((day, index) => ({ date: day.date, count: MOCK_WEEKLY_COUNTS[index] })),
    topPlace: "동의대학교",
  };
}

// --- 즐겨찾기 카드 클릭 ---

// TODO(즐겨찾기 → 길찾기): 길찾기 화면에 이 장소를 목적지로 넘긴다 (예: /pages/search.html?to=…&toLat=…&toLng=…&toAddress=…).
//   search.js의 쿼리 복원(queryCoordinates·placeAddress)과 같은 규칙으로 만든다. 다음 작업에서 연결한다.
export function openFavoriteInSearch(place, { notify } = {}) {
  notify?.(`${place.name}: 길찾기 연결은 준비 중이에요.`);
  return null;
}
