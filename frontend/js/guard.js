// 화면 접근 권한을 한 곳에서 처리한다.
// 이 검사는 화면 흐름(UX)을 위한 것일 뿐 보안 장치가 아니다. localStorage는 사용자가 고칠 수 있으므로,
// 보호된 화면이 부르는 API(/api/favorites, /api/history, /api/stats)는 서버에서도 세션을 확인해 401을 돌려줘야 한다.
import { getUser, onAuthChange, initializeAuth } from "/js/auth.js";
import { openAuthModal } from "/js/components/authModal.js";

// 로그인해야 들어갈 수 있는 화면. 추가하거나 뺄 때는 이 배열을 고친다.
// 새로 추가한 화면은 HTML 본문 영역에 data-auth-content hidden을 달고,
// 페이지 스크립트에서 데이터를 불러오기 전에 requirePageAccess()를 기다린다.
export const PROTECTED_PATHS = ["/pages/favorites.html", "/pages/stats.html"];

// 로그인 없이 보호된 화면에 직접 들어왔다가 모달을 닫으면 보내는 곳
const FALLBACK_PATH = "/pages/search.html";

const isProtected = (pathname) => PROTECTED_PATHS.includes(pathname);
const isLoggedIn = () => Boolean(getUser());

// 보호된 화면으로 가는 링크를 누르면 이동하지 않고 로그인 모달을 띄운다.
// 로그인하면 그 화면으로 이동하고, 모달을 닫으면 지금 화면에 머문다.
export function installAuthGuard() {
  document.addEventListener("click", (event) => {
    // 새 탭으로 여는 클릭은 그대로 둔다. 새 탭에서 requirePageAccess가 처리한다.
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    const link = event.target.closest("a[href]");
    if (!link || link.origin !== location.origin || !isProtected(link.pathname) || isLoggedIn()) return;

    event.preventDefault();
    openAuthModal({ returnTo: link.pathname + link.search + link.hash, onLogin: () => location.assign(link.href) });
  });

  // 보호된 화면에서 로그아웃하면 길찾기로 보낸다.
  onAuthChange(() => {
    if (!isLoggedIn() && isProtected(location.pathname)) location.replace(FALLBACK_PATH);
  });
}

// 보호된 화면의 페이지 스크립트가 데이터를 불러오기 전에 기다린다.
// 로그인 상태이면 바로 끝나고, 아니면 본문을 숨긴 채 로그인 모달을 띄운다.
export async function requirePageAccess() {
  await initializeAuth();
  const content = document.querySelector("[data-auth-content]");
  const showContent = () => {
    if (content) content.hidden = false;
  };

  if (!isProtected(location.pathname) || isLoggedIn()) {
    showContent();
    return Promise.resolve();
  }

  if (content) content.hidden = true;
  return new Promise((resolve) => {
    openAuthModal({
      onLogin: () => {
        showContent();
        resolve();
      },
      // 직접 들어온 경우 돌아갈 이전 화면이 없으므로 길찾기로 보낸다. 뒤로 가기로 다시 오지 않게 replace를 쓴다.
      onDismiss: () => location.replace(FALLBACK_PATH),
    });
  });
}
