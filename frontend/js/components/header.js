// 경로 결과 화면은 길찾기 흐름의 일부이므로 "길찾기" 메뉴를 강조한다.
const MENU = [
  { label: "길찾기", href: "/pages/search.html", activePaths: ["/pages/search.html", "/pages/result.html"] },
  { label: "즐겨찾기·기록", href: "/pages/favorites.html", activePaths: ["/pages/favorites.html"] },
  { label: "이용 통계", href: "/pages/stats.html", activePaths: ["/pages/stats.html"] },
];

function renderHeader() {
  const header = document.getElementById("site-header");
  if (!header) return;

  const links = MENU.map(({ label, href, activePaths }) => {
    const isActive = activePaths.includes(location.pathname);
    const activeAttrs = isActive ? ' aria-current="page"' : "";
    return `<a class="site-header__link${isActive ? " is-active" : ""}" href="${href}"${activeAttrs}>${label}</a>`;
  }).join("");

  header.innerHTML = `
    <div class="site-header__inner">
      <a class="site-header__logo" href="/index.html">길잇</a>
      <nav class="site-header__menu">${links}</nav>
      <button class="btn site-header__login" type="button">로그인</button>
    </div>
  `;
}

renderHeader();
