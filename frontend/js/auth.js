import { USE_MOCK } from "/js/config.js";
import { getSessionUser, getSocialLoginUrl } from "/js/api.js";

const AUTH_CHANGE_EVENT = "gilit:authchange";
const MOCK_SESSION = "gilit:mock:session";
const RETURN_KEY = "gilit:auth:return";
let user = null;
let initialization;
let redirecting = false;
let authMessage = "";

export function getUser() { return user; }

export function setUser(value) {
  if (!value || typeof value.id !== "string" || !value.id) throw new Error("사용자 응답을 확인해 주세요.");
  user = { ...value, name: typeof value.name === "string" && value.name.trim() ? value.name.trim() : "길잇 사용자" };
  // 기존 표시용 캐시를 인증 근거로 읽지 않는다. Mock 세션은 별도 저장한다.
  try {
    localStorage.removeItem("gilit:user");
    if (USE_MOCK) sessionStorage.setItem(MOCK_SESSION, JSON.stringify(user));
  } catch { /* 저장소가 차단되어도 현재 화면은 동작한다. */ }
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
}

export function safeReturnPath(value) {
  try {
    if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return "/pages/search.html";
    const url = new URL(value, location.origin);
    if (url.origin !== location.origin || !["/", "/index.html", "/pages/search.html", "/pages/result.html", "/pages/favorites.html", "/pages/stats.html"].includes(url.pathname)) return "/pages/search.html";
    url.searchParams.delete("auth_result");
    return url.pathname + url.search + url.hash;
  } catch { return "/pages/search.html"; }
}

export function login(provider, returnTo = location.pathname + location.search + location.hash) {
  if (redirecting) return;
  const url = getSocialLoginUrl(provider); // 미설정일 때 이동/성공 처리하지 않는다.
  sessionStorage.setItem(RETURN_KEY, safeReturnPath(returnTo));
  redirecting = true;
  try { location.assign(url); } catch (error) { redirecting = false; throw error; }
}

export function logout() {
  user = null;
  try { localStorage.removeItem("gilit:user"); sessionStorage.removeItem(MOCK_SESSION); } catch { /* 메모리 상태는 종료 */ }
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
}

export function takeAuthMessage() { const message = authMessage; authMessage = ""; return message; }

export function initializeAuth() {
  if (initialization) return initialization;
  initialization = (async () => {
    const url = new URL(location.href);
    const result = url.searchParams.get("auth_result");
    if (result !== null) {
      url.searchParams.delete("auth_result");
      history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
    try {
      if (USE_MOCK) {
        const saved = sessionStorage.getItem(MOCK_SESSION);
        if (saved && !result) setUser(JSON.parse(saved));
      } else {
        setUser(await getSessionUser());
      }
    } catch (error) {
      user = null;
      if (error.status !== 401) authMessage = "로그인 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.";
    }
    if (result !== null) {
      let returnTo;
      try { returnTo = sessionStorage.getItem(RETURN_KEY); sessionStorage.removeItem(RETURN_KEY); } catch { /* 기본 현재 화면 */ }
      if (result === "success" && user && !USE_MOCK) {
        if (returnTo) location.replace(safeReturnPath(returnTo));
      } else {
        authMessage = result === "cancelled" ? "소셜 로그인이 취소되었습니다." : "소셜 로그인에 실패했습니다. 다시 시도해 주세요.";
      }
    }
  })();
  return initialization;
}

window.addEventListener("pageshow", () => { redirecting = false; });
export function onAuthChange(listener) { window.addEventListener(AUTH_CHANGE_EVENT, listener); }
