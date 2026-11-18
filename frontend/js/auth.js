import { USE_MOCK } from "/js/config.js";
import { getSessionUser, getSocialLoginUrl } from "/js/api.js";

const AUTH_CHANGE_EVENT = "gilit:authchange";
const MOCK_SESSION = "gilit:mock:session";
const RETURN_KEY = "gilit:auth:return";
// 로그인에 성공하면 가는 메인 화면 (헤더 로고가 가리키는 홈). 보호된 화면 접근 등 이동할 곳을 정해 둔 로그인만 예외다.
export const HOME_PATH = "/index.html";
const HOME_PATHS = ["/", "/index.html"];
// 결과 화면에서 로그인하면(별을 누르려다 로그인하는 경우가 많다) 메인으로 가지 않고 그 결과 화면에 머문다.
const RESULT_PATH = "/pages/result.html";
// 복귀 주소 최대 길이. 결과 화면 쿼리(장소 이름·좌표·주소)를 담기에 충분하고, 그보다 길면 메인으로 보낸다.
const MAX_RETURN_PATH_LENGTH = 2048;
let user = null;
let initialization;
let redirecting = false;
let authMessage = "";
let authVersion = 0;

export function getUser() { return user; }

export function setUser(value) {
  if (!value || typeof value.id !== "string" || !value.id) throw new Error("사용자 응답을 확인해 주세요.");
  authVersion++;
  user = { ...value, name: typeof value.name === "string" && value.name.trim() ? value.name.trim() : "길잇 사용자" };
  // 기존 표시용 캐시를 인증 근거로 읽지 않는다. Mock 세션은 별도 저장한다.
  try {
    localStorage.removeItem("gilit:user");
    if (USE_MOCK) sessionStorage.setItem(MOCK_SESSION, JSON.stringify(user));
  } catch { /* 저장소가 차단되어도 현재 화면은 동작한다. */ }
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
}

// 복귀 주소는 이 사이트의 알려진 화면만 허용한다. 그 밖의 값은 메인 화면으로.
export function safeReturnPath(value) {
  try {
    if (typeof value !== "string" || value.length > MAX_RETURN_PATH_LENGTH || !value.startsWith("/") || value.startsWith("//")) return HOME_PATH;
    const url = new URL(value, location.origin);
    if (url.origin !== location.origin || !["/", "/index.html", "/pages/search.html", RESULT_PATH, "/pages/favorites.html", "/pages/stats.html"].includes(url.pathname)) return HOME_PATH;
    url.searchParams.delete("auth_result");
    const path = url.pathname + url.search + url.hash;
    return path.length > MAX_RETURN_PATH_LENGTH ? HOME_PATH : path;
  } catch { return HOME_PATH; }
}

export function isHomePage() { return HOME_PATHS.includes(location.pathname); }

// 로그인해도 이동하지 않고 상태만 갱신하는 화면: 메인 화면과 결과 화면.
function staysAfterLogin() { return isHomePage() || location.pathname === RESULT_PATH; }

// 소셜 로그인 시작. returnTo는 이동할 곳을 정해 둔 로그인(보호된 화면 접근, guard.js)이 넘긴다.
// 결과 화면에서 시작하면 그 결과 화면 전체 주소(쿼리 포함)를 복귀 주소로 남긴다.
// 둘 다 아니면 저장된 이전 값도 지워, 콜백 복귀(auth_result=success) 뒤 메인 화면으로 간다.
export function login(provider, returnTo) {
  if (redirecting) return;
  const url = getSocialLoginUrl(provider); // 미설정일 때 이동/성공 처리하지 않는다.
  if (!returnTo && location.pathname === RESULT_PATH) returnTo = location.pathname + location.search + location.hash;
  if (returnTo) sessionStorage.setItem(RETURN_KEY, safeReturnPath(returnTo));
  else sessionStorage.removeItem(RETURN_KEY);
  redirecting = true;
  try { location.assign(url); } catch (error) { redirecting = false; throw error; }
}

// 이메일 로그인 성공 (authModal.js). 세션은 서버가 이미 만들었다. 메인 화면이 아니면 메인으로 이동하고,
// 메인이나 결과 화면이면 이동 없이 상태만 갱신한다 (redirecting은 켜지 않는다. 결과 화면은 인증 변경 이벤트로 별 상태를
// 다시 불러온다). 이동할 때는 setUser 전에 redirecting을 켜서 인증 변경 이벤트를 받은 화면이 저장 데이터를 요청하지 않게
// 한다 (isRedirecting). 이동했으면 true.
export function completeLogin(value) {
  const leaving = !staysAfterLogin();
  if (leaving) redirecting = true;
  try {
    setUser(value);
    if (leaving) location.assign(HOME_PATH);
  } catch (error) {
    redirecting = false;
    throw error;
  }
  return leaving;
}

export function logout() {
  authVersion++;
  user = null;
  try { localStorage.removeItem("gilit:user"); sessionStorage.removeItem(MOCK_SESSION); } catch { /* 메모리 상태는 종료 */ }
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
}

// 소셜 로그인 시작·복귀로 화면을 떠나는 중이면 true. 화면은 이때 데이터 요청을 시작하지 않는다.
export function isRedirecting() { return redirecting; }

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
    const version = authVersion;
    try {
      if (USE_MOCK) {
        const saved = sessionStorage.getItem(MOCK_SESSION);
        if (saved && !result) setUser(JSON.parse(saved));
      } else {
        const current = await getSessionUser();
        // 조회 중 로그아웃하거나 다른 계정으로 로그인했다면 이전 응답을 버린다.
        if (version !== authVersion) return;
        setUser(current);
      }
    } catch (error) {
      if (version !== authVersion) return;
      user = null;
      if (error.status !== 401) authMessage = "로그인 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.";
    }
    if (result !== null) {
      let returnTo;
      try { returnTo = sessionStorage.getItem(RETURN_KEY); sessionStorage.removeItem(RETURN_KEY); } catch { /* 기본 현재 화면 */ }
      if (result === "success" && user && !USE_MOCK) {
        // 콜백은 언제나 /pages/search.html로 돌아온다. 정해 둔 복귀 주소가 없으면 메인 화면으로 간다.
        redirecting = true;
        location.replace(returnTo ? safeReturnPath(returnTo) : HOME_PATH);
      } else {
        const messages = {
          cancelled: "소셜 로그인이 취소되었습니다.",
          email_exists: "이미 가입된 이메일입니다. 기존에 쓰던 방법으로 로그인해 주세요.",
        };
        authMessage = messages[result] || authMessage || "소셜 로그인에 실패했습니다. 다시 시도해 주세요.";
      }
    }
  })();
  return initialization;
}

// 화면이 다시 보일 때(bfcache 복원, 탭 복귀) 서버 세션을 다시 확인한다. 다른 탭에서 계정을 바꿨거나
// 로그아웃했으면 setUser/logout으로 인증 변경 이벤트를 내보내 화면이 현재 계정 데이터를 다시 불러오게 한다.
// 같은 계정이면 아무것도 하지 않는다. 확인 중 로그인·로그아웃이 일어나면 이 응답은 버린다.
// 네트워크 오류(401 이외)는 판단할 수 없으므로 지금 상태를 유지한다.
export async function recheckAuth() {
  await initializeAuth();
  if (redirecting) return;
  const version = authVersion;
  let current;
  try {
    if (USE_MOCK) {
      const saved = sessionStorage.getItem(MOCK_SESSION);
      current = saved ? JSON.parse(saved) : null;
    } else {
      current = await getSessionUser();
    }
  } catch (error) {
    if (error?.status !== 401) return;
    current = null;
  }
  if (version !== authVersion || redirecting) return;
  if (!current) { if (user) logout(); return; }
  if (current.id !== user?.id) setUser(current);
}

window.addEventListener("pageshow", () => { redirecting = false; });
export function onAuthChange(listener) { window.addEventListener(AUTH_CHANGE_EVENT, listener); }
