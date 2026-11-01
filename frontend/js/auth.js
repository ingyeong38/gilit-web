// 소셜 로그인 연동 전 임시 구현. 로그인 상태를 localStorage에만 저장한다.
const STORAGE_KEY = "gilit:user";
const PROVIDER_NAMES = { google: "Google 사용자", kakao: "카카오 사용자" };

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

export function login(provider) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ name: PROVIDER_NAMES[provider], provider }));
}

export function logout() {
  localStorage.removeItem(STORAGE_KEY);
}
