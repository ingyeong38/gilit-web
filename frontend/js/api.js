import { getUser } from "/js/auth.js";
import { GRAPH_DATA_SOURCE } from "/js/config.js";
import { loadGraphPresentation } from "/js/graphData.js";
// 서버 호출은 이 파일에만 둔다.
// USE_MOCK이면 js/mock/*.json을 읽고, 서버가 계산할 값(시각, 필터링, 저장)만 여기서 흉내 낸다.
import { USE_MOCK, USE_MOCK_STATS, USE_MOCK_ROUTES, BASE_URL, SOCIAL_AUTH_START_URLS } from "/js/config.js";
import { addMinutes, dateOf, daysFrom, minutesBetween, toDateString } from "/js/utils.js";

const MOCK_FAVORITES_KEY = "gilit:mock:favorites";
const MOCK_USERS_KEY = "gilit:mock:users";
const LOGIN_FAILED = "이메일 또는 비밀번호가 올바르지 않습니다.";

// 서버가 { "message": "..." }로 보낸 오류 문구를 화면에 그대로 보여 줄 수 있게 담는다.
// code는 서버가 함께 보낸 실패 코드다 (예: 닉네임 검증 "chars"). 없으면 undefined.
export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function buildUrl(path, params = {}) {
  const entries = Object.entries(params).filter(
    ([, value]) => value !== undefined && value !== null && value !== ""
  );
  const query = new URLSearchParams(entries).toString();
  return `${BASE_URL}${path}${query ? `?${query}` : ""}`;
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.message || `요청 실패: ${url} (${response.status})`, response.status,
      typeof body?.code === "string" ? body.code : undefined);
  }
  return response.status === 204 ? null : response.json();
}

// 공개 설정 (GET /api/config). 서버가 주는 값은 카카오 지도 JavaScript 키와 GA4 측정 ID 두 개뿐이다.
// 실패·시간 초과·형식 오류에도 예외를 던지지 않고 빈 값을 돌려준다 (js/runtimeConfig.js가 config.js 값으로 대체).
// 전체 Mock(USE_MOCK)은 서버 없이 쓰므로 부르지 않는다.
export const RUNTIME_CONFIG_TIMEOUT_MS = 5000;
const GA4_MEASUREMENT_ID_PATTERN = /^G-[A-Z0-9]+$/;

export function normalizeRuntimeConfig(value) {
  const text = (field) => (typeof field === "string" ? field.trim() : "");
  const measurementId = text(value?.ga4MeasurementId);
  return {
    kakaoJsKey: text(value?.kakaoJsKey),
    ga4MeasurementId: GA4_MEASUREMENT_ID_PATTERN.test(measurementId) ? measurementId : "",
  };
}

export async function getRuntimeConfig() {
  if (USE_MOCK) return normalizeRuntimeConfig(null);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), RUNTIME_CONFIG_TIMEOUT_MS);
  try {
    return normalizeRuntimeConfig(await requestJson(buildUrl("/config"), { cache: "no-store", signal: controller.signal }));
  } catch {
    return normalizeRuntimeConfig(null);
  } finally {
    clearTimeout(timer);
  }
}

function postJson(path, body) {
  return requestJson(buildUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function readMock(file) {
  return requestJson(`/js/mock/${file}`);
}

// mock의 가장 최근 날짜가 오늘이 되도록 옮길 일수
function daysToToday(latestDate) {
  return Math.round(minutesBetween(`${latestDate}T00:00:00Z`, `${toDateString()}T00:00:00Z`) / 1440);
}

export async function getRoutes({ from, to, arrive, buffer, fromLat, fromLng, toLat, toLng } = {}) {
  if (!USE_MOCK_ROUTES) return requestJson(buildUrl("/routes", { from, to, arrive, buffer, fromLat, fromLng, toLat, toLng }));

  const routes = await readMock("routes.json");
  if (!arrive) return routes;
  const arriveTime = addMinutes(arrive, -(Number(buffer) || 0));
  return routes.map((route) => ({
    ...route,
    arriveTime,
    departTime: addMinutes(arriveTime, -route.durationMin),
  }));
}

// routes: 같은 검색의 getRoutes 결과. 카드의 id·departTime을 card 파라미터로 보낸다.
export function getRouteGraph(search = {}, routes = []) {
  return loadGraphPresentation({ search, routes, mode: GRAPH_DATA_SOURCE, baseUrl: BASE_URL, hostname: location.hostname });
}

// AI 경로 요약 (POST /api/routes/summary). 요청에는 도착 희망 시각·여유시간·카드 6개 필드만 담는다.
// 장소 이름·좌표·사용자 정보는 보내지 않는다. 서버는 Gemini가 실패해도 200(source: "rule")을 준다.
export const SUMMARY_ROUTE_FIELDS = Object.freeze(["id", "departTime", "arriveTime", "durationMin", "distanceKm", "toll"]);
export const SUMMARY_TIMEOUT_MS = 10000;
const SUMMARY_ROUTE_LIMIT = 4;

export function summaryRequestBody({ arrive, buffer } = {}, routes = []) {
  const cards = (Array.isArray(routes) ? routes : [])
    .filter((route) => typeof route?.id === "string" && route.id && typeof route.departTime === "string")
    .slice(0, SUMMARY_ROUTE_LIMIT)
    .map((route) => Object.fromEntries(SUMMARY_ROUTE_FIELDS.map((key) => [key, route[key] ?? null])));
  return { arrive, buffer: Number(buffer) || 0, routes: cards };
}

export async function getRouteSummary(search = {}, routes = []) {
  const body = summaryRequestBody(search, routes);
  if (USE_MOCK_ROUTES) {
    // 목업 카드(getRoutes)는 출발시각을 도착 희망 시각에 맞춰 옮기므로, 요약의 시각도 같은 카드 값으로 맞춘다.
    const summary = await readMock("routeSummary.json");
    const departOf = new Map(body.routes.map((route) => [route.id, route.departTime]));
    return {
      ...summary,
      recommendedDepartTime: departOf.get(summary.recommendedRouteId) ?? summary.recommendedDepartTime,
      comparison: summary.comparison.map((row) => ({ ...row, departTime: departOf.get(row.routeId) ?? row.departTime })),
    };
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SUMMARY_TIMEOUT_MS);
  try {
    return await requestJson(buildUrl("/routes/summary"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

export async function searchPlaces(q = "") {
  q = q.trim();
  if (!USE_MOCK_ROUTES) return requestJson(buildUrl("/places", { q }));

  const places = await readMock("places.json");
  const keyword = q.toLocaleLowerCase("ko-KR");
  return keyword ? places.filter((place) => [place.name, place.address]
    .some((value) => String(value ?? "").toLocaleLowerCase("ko-KR").includes(keyword))) : places;
}

// 소유자를 알 수 없는 기존 공용 저장값은 보존하되 어떤 계정에도 배정하지 않는다.
function favoriteSession() {
  const owner = getUser();
  if (!owner) throw new ApiError("로그인이 필요합니다.", 401);
  return {
    key: `${MOCK_FAVORITES_KEY}:${encodeURIComponent(owner.id)}`,
    check() {
      if (getUser() !== owner) throw new ApiError("로그인 계정이 변경되었습니다. 다시 시도해 주세요.", 409);
    },
  };
}

function readMockFavorites(session) {
  const saved = localStorage.getItem(session.key);
  return saved ? JSON.parse(saved) : [];
}

export async function getFavorites() {
  const session = favoriteSession();
  const favorites = USE_MOCK ? readMockFavorites(session)
    : await requestJson(buildUrl("/favorites"), { cache: "no-store" });
  session.check();
  return favorites;
}

// 서버는 좌표를 숫자로만 받는다 ("35.1" 같은 문자열은 400). 쿼리에서 온 문자열 좌표도 숫자로 바꾼다.
function toCoordinate(value) {
  const number = typeof value === "string" && value.trim() ? Number(value) : value;
  return typeof number === "number" && Number.isFinite(number) ? number : null;
}

// POST /api/favorites 본문 (docs/api-spec.md). 좌표는 둘 다 있을 때만 보낸다. 없으면 서버가 주소로 찾는다.
function favoriteBody({ name, address, type, lat, lng }) {
  const body = { name, address, type };
  const latitude = toCoordinate(lat);
  const longitude = toCoordinate(lng);
  if (latitude !== null && longitude !== null) Object.assign(body, { lat: latitude, lng: longitude });
  return body;
}

export async function addFavorite(place) {
  const session = favoriteSession();
  if (!USE_MOCK) {
    const created = await postJson("/favorites", favoriteBody(place));
    session.check();
    return created;
  }
  const favorites = readMockFavorites(session);
  const created = { ...place, id: crypto.randomUUID() };
  session.check();
  localStorage.setItem(session.key, JSON.stringify([...favorites, created]));
  return created;
}

export async function removeFavorite(id) {
  const session = favoriteSession();
  if (!USE_MOCK) {
    await requestJson(buildUrl("/favorites", { id }), { method: "DELETE" });
    session.check();
    return;
  }
  const favorites = readMockFavorites(session);
  session.check();
  localStorage.setItem(session.key, JSON.stringify(favorites.filter((place) => place.id !== id)));
}

export async function getHistory() {
  // 계정을 바꾼 뒤 이전 계정의 응답이 브라우저 캐시에서 나오지 않게 한다 (getFavorites와 같다).
  if (!USE_MOCK) return requestJson(buildUrl("/history"), { cache: "no-store" });

  const history = await readMock("history.json");
  const latest = history.map((item) => dateOf(item.arriveTime)).sort().at(-1);
  const shift = daysToToday(latest);
  return history.map((item) => ({
    ...item,
    arriveTime: `${daysFrom(dateOf(item.arriveTime), shift)}${item.arriveTime.slice(10)}`,
  }));
}

export async function getStats(days = 7) {
  if (!USE_MOCK_STATS) return requestJson(buildUrl("/stats", { days }), { cache: "no-store" });

  const stats = await readMock("stats.json");
  const to = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", dateStyle: "short" }).format(new Date());
  const from = daysFrom(to, 1 - days);
  const dailyVisitors = Array.from({ length: days }, (_, index) => ({
    date: daysFrom(from, index),
    count: stats.dailyVisitors.at(index - days)?.count ?? null,
  }));
  const hasSample = days === 7;
  return {
    ...stats, from, to, days, dailyVisitors,
    periodVisitors: hasSample ? stats.weekVisitors : days === 1 ? stats.todayVisitors : null,
    periodChangePct: hasSample ? stats.weekChangePct : days === 1 ? stats.dayChangePct : null,
    totalSearches: hasSample ? stats.totalSearches : null,
    popularOrigins: hasSample ? stats.popularOrigins : [],
    popularDestinations: hasSample ? stats.popularDestinations : [],
  };
}

// 내 이용 통계 (GET /api/stats/me?range=week, docs/api-spec.md "내 이용 통계"). 마이페이지가 쓴다.
// 응답: { range, from, to, daily: [{ date: "YYYY-MM-DD", count }] 7개(오래된 날 → 오늘, KST), total, topPlace(없으면 null) }
// mock을 돌려주는 유일한 조건은 USE_MOCK(전체 mock 스위치)이 true일 때다. 그 밖에는 항상 실제 API를 부른다.
// USE_MOCK_STATS는 보지 않는다. 그 값은 사이트 전체 통계(getStats, GET /api/stats, 통계 화면)에만 쓴다.
// now는 mock 날짜에만 쓴다.
const MOCK_WEEKLY_COUNTS = [4, 7, 5, 9, 6, 11, 8];
const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

export async function getMyStats(now = new Date()) {
  if (!USE_MOCK) return requestJson(buildUrl("/stats/me", { range: "week" }), { cache: "no-store" });

  // mock: 오늘(KST) 기준 최근 7일. 마지막 값이 오늘이다.
  const daily = MOCK_WEEKLY_COUNTS.map((count, index) => ({
    date: new Date(now.getTime() + KST_OFFSET_MS - (6 - index) * DAY_MS).toISOString().slice(0, 10),
    count,
  }));
  const total = daily.reduce((sum, day) => sum + day.count, 0);
  return { range: "week", from: daily[0].date, to: daily.at(-1).date, daily, total, topPlace: "동의대학교" };
}

// mock 계정은 이 브라우저의 localStorage에만 있다. 비밀번호는 평문 대신 SHA-256 값으로 둔다.
// 실제 서버는 bcrypt로 해시한다 (docs/api-spec.md).
function readMockUsers() {
  return JSON.parse(localStorage.getItem(MOCK_USERS_KEY) || "[]");
}

async function hashForMock(password) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(password));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function normalizeEmail(email) {
  return email.trim().toLowerCase();
}

export async function signup({ name, email, password, agreeTerms, agreePrivacy }) {
  if (!USE_MOCK) return postJson("/auth/signup", { name, email, password, agreeTerms, agreePrivacy });

  const users = readMockUsers();
  const normalized = normalizeEmail(email);
  if (users.some((user) => user.email === normalized)) {
    throw new ApiError("이미 가입된 이메일입니다.", 409);
  }
  const user = { id: `user-${Date.now()}`, name: name.trim(), email: normalized, provider: "email" };
  const passwordHash = await hashForMock(password);
  localStorage.setItem(MOCK_USERS_KEY, JSON.stringify([...users, { ...user, passwordHash }]));
  return user;
}

export async function loginWithEmail({ email, password }) {
  if (!USE_MOCK) return postJson("/auth/login", { email, password });

  const found = readMockUsers().find((user) => user.email === normalizeEmail(email));
  if (!found || found.passwordHash !== (await hashForMock(password))) {
    throw new ApiError(LOGIN_FAILED, 401);
  }
  const { passwordHash, ...user } = found;
  return user;
}

export async function logoutSession() {
  if (!USE_MOCK) await requestJson(buildUrl("/auth/logout"), { method: "POST" });
}

// 인증은 실제 서버 세션으로만 확인한다. 소셜 인증 mock은 제공하지 않는다.
export function getSessionUser() {
  return requestJson(buildUrl("/auth/me"));
}

// 닉네임 변경 (PATCH /api/auth/me { name }). 갱신된 사용자({ id, name, email, provider })를 돌려준다.
// 규칙 위반은 400 + { message, code }다 (docs/api-spec.md "닉네임 변경"). 화면은 code로 문구를 고른다.
export async function updateNickname(name) {
  if (!USE_MOCK) {
    return requestJson(buildUrl("/auth/me"), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  }
  // mock: 이 브라우저의 mock 계정 목록에 저장한다. 검증은 화면(mypage.js validateNickname)이 이미 했다.
  const current = getUser();
  if (!current) throw new ApiError("로그인이 필요합니다.", 401);
  const nickname = String(name).normalize("NFC").trim();
  const users = readMockUsers().map((user) => (user.id === current.id ? { ...user, name: nickname } : user));
  localStorage.setItem(MOCK_USERS_KEY, JSON.stringify(users));
  return { ...current, name: nickname };
}

export function getSocialLoginUrl(provider) {
  if (!["google", "kakao"].includes(provider)) throw new ApiError("지원하지 않는 로그인입니다.", 400);
  const configured = SOCIAL_AUTH_START_URLS[provider];
  if (USE_MOCK || !configured) throw new ApiError("소셜 로그인은 백엔드 API 연동 대기 중입니다." + (USE_MOCK ? " 현재 이메일 Mock 로그인만 시험할 수 있습니다." : ""), 503);
  const url = new URL(configured, location.origin);
  if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) throw new ApiError("소셜 로그인 시작 URL 설정을 확인해 주세요.", 400);
  return url.href;
}
