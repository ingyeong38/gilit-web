import { getUser } from "/js/auth.js";
import { GRAPH_DATA_SOURCE } from "/js/config.js";
import { loadGraphPresentation } from "/js/graphData.js";
// 서버 호출은 이 파일에만 둔다.
// USE_MOCK이면 js/mock/*.json을 읽고, 서버가 계산할 값(시각, 필터링, 저장)만 여기서 흉내 낸다.
import { USE_MOCK, USE_MOCK_ROUTES, BASE_URL, SOCIAL_AUTH_START_URLS } from "/js/config.js";
import { addMinutes, dateOf, daysFrom, minutesBetween, toDateString } from "/js/utils.js";

const MOCK_FAVORITES_KEY = "gilit:mock:favorites";
const MOCK_USERS_KEY = "gilit:mock:users";
const LOGIN_FAILED = "이메일 또는 비밀번호가 올바르지 않습니다.";

// 서버가 { "message": "..." }로 보낸 오류 문구를 화면에 그대로 보여 줄 수 있게 담는다.
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
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
    throw new ApiError(body?.message || `요청 실패: ${url} (${response.status})`, response.status);
  }
  return response.status === 204 ? null : response.json();
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

export function getRouteGraph(search = {}) {
  return loadGraphPresentation({ search, mode: GRAPH_DATA_SOURCE, baseUrl: BASE_URL, hostname: location.hostname });
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

export async function addFavorite(place) {
  const session = favoriteSession();
  if (!USE_MOCK) {
    const created = await postJson("/favorites", place);
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
  if (!USE_MOCK) return requestJson(buildUrl("/history"));

  const history = await readMock("history.json");
  const latest = history.map((item) => dateOf(item.arriveTime)).sort().at(-1);
  const shift = daysToToday(latest);
  return history.map((item) => ({
    ...item,
    arriveTime: `${daysFrom(dateOf(item.arriveTime), shift)}${item.arriveTime.slice(10)}`,
  }));
}

export async function getStats() {
  if (!USE_MOCK) return requestJson(buildUrl("/stats"));

  const stats = await readMock("stats.json");
  const shift = daysToToday(stats.dailyVisitors.at(-1).date);
  return {
    ...stats,
    dailyVisitors: stats.dailyVisitors.map((day) => ({ ...day, date: daysFrom(day.date, shift) })),
  };
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

export function getSocialLoginUrl(provider) {
  if (!["google", "kakao"].includes(provider)) throw new ApiError("지원하지 않는 로그인입니다.", 400);
  const configured = SOCIAL_AUTH_START_URLS[provider];
  if (USE_MOCK || !configured) throw new ApiError("소셜 로그인은 백엔드 API 연동 대기 중입니다." + (USE_MOCK ? " 현재 이메일 Mock 로그인만 시험할 수 있습니다." : ""), 503);
  const url = new URL(configured, location.origin);
  if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) throw new ApiError("소셜 로그인 시작 URL 설정을 확인해 주세요.", 400);
  return url.href;
}
