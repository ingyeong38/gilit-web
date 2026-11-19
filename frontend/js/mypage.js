// 마이페이지의 데이터와 계산. 화면 연결은 js/pages/mypage.js가 한다.
// 닉네임 저장은 서버(PATCH /api/auth/me)와 연결돼 있다. 나머지 서버 연결 지점은 아래 TODO에 있다 (서버 호출은 js/api.js에만 둔다).
import { USE_MOCK_STATS } from "/js/config.js";
import { updateNickname } from "/js/api.js";

const DAY_MS = 24 * 60 * 60 * 1000;
const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

// --- 닉네임 ---

// 닉네임 규칙 (서버 backend/app/auth/nickname.py와 같다. 바꾸면 함께 고친다)
// - NFC 정규화 후 앞뒤 공백 제거, 길이 2~20자(글자 수 기준)
// - 허용 문자: 한글 완성형(가-힣), 영문(A-Za-z), 숫자(0-9), 공백(스페이스), 특수문자 - _ ! # 만
// - 한글·영문·숫자 중 최소 1자 포함, 연속 공백 불허
// - 불허: 그 외 문자, 이모지, 한글 자모 단독, 탭·줄바꿈 등 스페이스 이외의 공백 문자
// - 중복 닉네임 허용
// - 규칙은 변경 요청 값에만 적용한다(기존 닉네임은 검사하지 않는다)
// - 현재 닉네임과 같으면 화면에서 저장 버튼을 막는다 (서버는 같은 값도 200, 변경 없음)
// 실패 코드는 서버와 같다: empty, chars, spaces, length, required (화면 전용: same)
// 두 쪽의 결과가 같은지는 frontend/tests/fixtures/nickname-cases.json으로 확인한다.
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
  chars: "사용할 수 없는 문자가 있어요. 한글, 영문, 숫자, 공백, - _ ! #만 쓸 수 있어요.",
  spaces: "공백은 한 칸씩만 쓸 수 있어요.",
  required: "한글, 영문, 숫자를 1자 이상 포함해 주세요.",
  same: "현재 닉네임과 같아요.",
});

// NFC 정규화 후 앞뒤 공백 제거 (서버와 같다. 맥에서 복사한 NFD 한글도 완성형으로 맞춘다)
export function normalizeNickname(value) {
  return typeof value === "string" ? value.normalize("NFC").trim() : "";
}

// 길이는 정규화·앞뒤 공백 제거 뒤 글자 수로 센다 (허용 문자는 모두 한 글자가 한 칸이다).
export function nicknameLength(value) {
  return [...normalizeNickname(String(value ?? ""))].length;
}

// { ok, value(정규화·앞뒤 공백 제거), code, message }. 검사 순서: 빈 값 → 허용 문자 → 연속 공백 → 길이 → 한글·영문·숫자 포함 → 현재와 같음.
// code: "empty" | "chars" | "spaces" | "length" | "required" | "same" | ""
export function validateNickname(value, { current = "" } = {}) {
  const nickname = normalizeNickname(value);
  const fail = (code) => ({ ok: false, value: nickname, code, message: NICKNAME_MESSAGES[code] });
  const length = [...nickname].length;
  if (!length) return fail("empty");
  if (!NICKNAME_ALLOWED_PATTERN.test(nickname)) return fail("chars");
  if (NICKNAME_CONSECUTIVE_SPACES.test(nickname)) return fail("spaces");
  if (length < NICKNAME_RULES.minLength || length > NICKNAME_RULES.maxLength) return fail("length");
  if (!NICKNAME_REQUIRED_PATTERN.test(nickname)) return fail("required");
  if (nickname === normalizeNickname(String(current ?? ""))) return fail("same");
  return { ok: true, value: nickname, code: "", message: "" };
}

// 서버 오류를 모달 문구로 바꾼다. 닉네임 규칙 실패(400 + code)는 같은 문구표(NICKNAME_MESSAGES)를 쓰고,
// 그 밖의 4xx는 서버 문구, 5xx·네트워크 오류는 기본 문구.
export function nicknameErrorMessage(error) {
  if (error?.code && Object.hasOwn(NICKNAME_MESSAGES, error.code)) return NICKNAME_MESSAGES[error.code];
  if (error?.status >= 400 && error.status < 500 && error.message) return error.message;
  return "닉네임을 저장하지 못했어요. 잠시 후 다시 시도해 주세요.";
}

// 닉네임 저장 (PATCH /api/auth/me). 성공하면 갱신된 사용자({ id, name, email, provider })를 돌려준다.
// 실패하면 화면에 보여 줄 문구(message)와 원래 status·code를 가진 오류를 던진다. mock은 api.js가 USE_MOCK일 때만 쓴다.
export async function saveNickname(nickname, { update = updateNickname } = {}) {
  try {
    return await update(nickname);
  } catch (error) {
    throw Object.assign(new Error(nicknameErrorMessage(error)), { status: error?.status, code: error?.code });
  }
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
