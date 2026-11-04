// 서버 호출은 이 파일에만 둔다.
// USE_MOCK이면 js/mock/*.json을 읽고, 서버가 계산할 값(시각, 필터링, 저장)만 여기서 흉내 낸다.
import { USE_MOCK, BASE_URL } from "/js/config.js";
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

export async function getRoutes({ from, to, arrive, buffer } = {}) {
  if (!USE_MOCK) return requestJson(buildUrl("/routes", { from, to, arrive, buffer }));

  const routes = await readMock("routes.json");
  if (!arrive) return routes;
  const arriveTime = addMinutes(arrive, -(Number(buffer) || 0));
  return routes.map((route) => ({
    ...route,
    arriveTime,
    departTime: addMinutes(arriveTime, -route.durationMin),
  }));
}

export async function getRouteGraph({ from, to, arrive } = {}) {
  if (!USE_MOCK) return requestJson(buildUrl("/routes/graph", { from, to, arrive }));

  const graph = await readMock("routeGraph.json");
  if (!arrive) return graph;
  // mock의 마지막 출발시각이 도착 희망 시각에 오도록 옮긴다.
  return graph.map(({ routeId, points }) => {
    const shift = minutesBetween(points.at(-1).departTime, arrive);
    return {
      routeId,
      points: points.map((point) => ({ ...point, departTime: addMinutes(point.departTime, shift) })),
    };
  });
}

export async function searchPlaces(q) {
  if (!USE_MOCK) return requestJson(buildUrl("/places", { q }));

  const places = await readMock("places.json");
  return q ? places.filter((place) => place.name.includes(q)) : places;
}

async function readMockFavorites() {
  const saved = localStorage.getItem(MOCK_FAVORITES_KEY);
  return saved ? JSON.parse(saved) : readMock("favorites.json");
}

function writeMockFavorites(favorites) {
  localStorage.setItem(MOCK_FAVORITES_KEY, JSON.stringify(favorites));
}

export function getFavorites() {
  return USE_MOCK ? readMockFavorites() : requestJson(buildUrl("/favorites"));
}

export async function addFavorite(place) {
  if (!USE_MOCK) {
    return postJson("/favorites", place);
  }
  const favorites = await readMockFavorites();
  const created = { ...place, id: `fav-${Date.now()}` };
  writeMockFavorites([...favorites, created]);
  return created;
}

export async function removeFavorite(id) {
  if (!USE_MOCK) {
    await requestJson(buildUrl("/favorites", { id }), { method: "DELETE" });
    return;
  }
  const favorites = await readMockFavorites();
  writeMockFavorites(favorites.filter((place) => place.id !== id));
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
