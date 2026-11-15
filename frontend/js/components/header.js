import { showToast } from "/js/components/toast.js";
import { logoutSession } from "/js/api.js";
import { getUser, logout, onAuthChange, initializeAuth, takeAuthMessage } from "/js/auth.js";
import { openAuthModal } from "/js/components/authModal.js";
import { icon } from "/js/components/icon.js";
import { installAuthGuard } from "/js/guard.js";
import { escapeHtml } from "/js/utils.js";

// 경로 결과 화면은 길찾기 흐름의 일부이므로 "길찾기" 메뉴를 강조한다.
const MENU = [
  { label: "길찾기", href: "/pages/search.html", activePaths: ["/pages/search.html", "/pages/result.html"] },
  { label: "즐겨찾기·기록", href: "/pages/favorites.html", activePaths: ["/pages/favorites.html"] },
  { label: "이용 통계", href: "/pages/stats.html", activePaths: ["/pages/stats.html"] },
];

function renderAccount(user) {
  if (!user) {
    return `
      <div class="account-actions">
        <button class="btn btn-secondary" type="button" data-auth-view="login">로그인</button>
        <button class="btn btn-primary" type="button" data-auth-view="signup">회원가입</button>
      </div>
    `;
  }
  const name = escapeHtml(user.name || "길잇 사용자");
  return `
    <button class="profile-button" type="button" data-action="profile" aria-label="프로필 메뉴">
      <span class="avatar">${escapeHtml((user.name || "길잇 사용자").charAt(0))}</span>
      <span>${name}</span>
      ${icon("chevron", { size: 16 })}
    </button>
    <div class="profile-menu" hidden>
      <button type="button">${icon("user", { size: 17 })} 내 정보</button>
      <button type="button" data-action="logout">${icon("logout", { size: 17 })} 로그아웃</button>
    </div>
  `;
}

function renderHeader() {
  const header = document.getElementById("site-header");
  if (!header) return;

  const links = MENU.map(({ label, href, activePaths }) => {
    const isActive = activePaths.includes(location.pathname);
    return `<a class="${isActive ? "active" : ""}" href="${href}"${isActive ? ' aria-current="page"' : ""}>${label}</a>`;
  }).join("");

  header.innerHTML = `
    <div class="nav-shell">
      <a class="logo" href="/index.html" aria-label="길잇 홈으로 이동">
        <span class="logo-mark">${icon("route", { size: 21 })}</span>
        <span>길잇</span>
        <span class="logo-sub">Gilit</span>
      </a>
      <nav class="nav-menu">${links}</nav>
      <div class="account">${renderAccount(getUser())}</div>
    </div>
  `;

  header.querySelectorAll("[data-auth-view]").forEach((button) => {
    button.addEventListener("click", () => {
      openAuthModal({ view: button.dataset.authView });
    });
  });
  header.querySelector('[data-action="profile"]')?.addEventListener("click", () => {
    const menu = header.querySelector(".profile-menu");
    menu.hidden = !menu.hidden;
  });
  header.querySelector('[data-action="logout"]')?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = "로그아웃 중…";
    try { await logoutSession(); logout(); }
    catch { showToast("로그아웃하지 못했습니다. 다시 시도해 주세요.", { error: true }); button.disabled = false; button.textContent = "로그아웃"; }
  });
}

// 로그인·로그아웃은 어디서 일어나든 이 이벤트로 헤더에 반영한다.
onAuthChange(renderHeader);
installAuthGuard();
renderHeader();

initializeAuth().then(() => {
  renderHeader();
  const message = takeAuthMessage();
  if (message) showToast(message, { error: true });
});
