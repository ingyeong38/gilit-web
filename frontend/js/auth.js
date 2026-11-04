// 로그인한 사용자 정보를 localStorage에 둔다. 소셜 로그인은 아직 연동 전 임시 구현이다.
const STORAGE_KEY = "gilit:user";
const PROVIDER_NAMES = { google: "Google 사용자", kakao: "카카오 사용자" };
const AUTH_CHANGE_EVENT = "gilit:authchange";

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

// 이메일 로그인: 서버(또는 mock)가 돌려준 사용자 정보를 저장한다.
export function setUser(user) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
}

export function login(provider) {
  setUser({ name: PROVIDER_NAMES[provider], provider });
}

export function logout() {
  localStorage.removeItem(STORAGE_KEY);
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
}

// 로그인·로그아웃할 때마다 부른다. 헤더 갱신과 접근 권한 처리에 쓴다.
export function onAuthChange(listener) {
  window.addEventListener(AUTH_CHANGE_EVENT, listener);
}
