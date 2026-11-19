// 마이페이지 화면. 데이터·계산은 /js/mypage.js에 있고, 이 파일은 화면 그리기와 이벤트만 맡는다.
// 공유 상태가 있는 모듈(auth.js 등)은 다른 화면과 같은 인스턴스를 써야 하므로 ?v=를 붙이지 않는다.
import { getUser, onAuthChange, recheckAuth } from "/js/auth.js";
import { requirePageAccess } from "/js/guard.js";
import { icon, renderIcons } from "/js/components/icon.js";
import { openModal } from "/js/components/modal.js";
import { showToast } from "/js/components/toast.js";
import { escapeHtml } from "/js/utils.js";
import {
  BAR_MAX_HEIGHT,
  NICKNAME_HELP_TEXT,
  NICKNAME_RULES,
  avatarInitial,
  loadFavorites,
  loadWeeklyStats,
  nicknameLength,
  openFavoriteInSearch,
  pickFavorites,
  providerLabel,
  saveNickname,
  validateNickname,
  weeklySummary,
} from "/js/mypage.js?v=mypage-20261119-4";

const PLACE_ICONS = { 집: "home", 회사: "wallet", 학교: "star" };

const greeting = document.getElementById("mypage-greeting");
const profile = document.getElementById("mypage-profile");
const favoritesBox = document.getElementById("mypage-favorites");
const statsBox = document.getElementById("mypage-stats");
const periodEl = document.getElementById("mypage-period");

// 이 화면에서 바꾼 닉네임 (저장이 서버와 연결되기 전에는 화면에만 반영한다)
let nickname = "";
let ownerId = null;

// --- 공통: 섹션별 로딩·오류·재시도 ---

function loadingHtml(text) {
  return `<div class="my-section-state" role="status"><span class="my-spinner" aria-hidden="true"></span>${escapeHtml(text)}</div>`;
}

function errorHtml(text) {
  return `<div class="my-section-state is-error" role="alert">${icon("close", { size: 16 })}<span>${escapeHtml(text)}</span><button class="btn btn-secondary my-retry" type="button" data-retry>다시 시도</button></div>`;
}

// 섹션마다 따로 불러오고 따로 실패한다. 늦게 도착한 이전 요청(재시도·계정 전환)의 결과는 버린다.
function sectionLoader(container, { load, render, loadingText, errorText }) {
  let generation = 0;
  async function run() {
    const current = ++generation;
    container.setAttribute("aria-busy", "true");
    container.innerHTML = loadingHtml(loadingText);
    try {
      const data = await load();
      if (current !== generation) return;
      render(data);
    } catch (error) {
      if (current !== generation) return;
      container.innerHTML = errorHtml(error?.status >= 400 && error.status < 500 && error.message ? error.message : errorText);
      container.querySelector("[data-retry]").addEventListener("click", run);
    } finally {
      if (current === generation) container.setAttribute("aria-busy", "false");
    }
  }
  run.cancel = () => { generation++; };
  return run;
}

// --- 01 닉네임 ---

function renderProfile() {
  const user = getUser();
  greeting.textContent = `안녕하세요, ${nickname}님`;
  profile.innerHTML = `
    <span class="profile-large-avatar" aria-hidden="true">${escapeHtml(avatarInitial(nickname))}</span>
    <div class="profile-identity">
      <small>현재 닉네임</small>
      <strong id="mypage-nickname">${escapeHtml(nickname)}</strong>
      <span>${escapeHtml(providerLabel(user?.provider))}</span>
    </div>
    <button class="btn btn-secondary edit-profile-button" type="button" data-action="edit-nickname" aria-haspopup="dialog">닉네임 변경</button>
  `;
  profile.querySelector('[data-action="edit-nickname"]').addEventListener("click", (event) => openNicknameModal(event.currentTarget));
}

function openNicknameModal(trigger) {
  const { maxLength } = NICKNAME_RULES;
  let saving = false;
  const restoreFocus = () => { if (trigger?.isConnected) trigger.focus(); else profile.querySelector('[data-action="edit-nickname"]')?.focus(); };
  const { element, close } = openModal({
    className: "modal nickname-modal",
    onDismiss: restoreFocus,
    content: `
      <div class="modal-title" id="nickname-title">닉네임 변경</div>
      <p id="nickname-desc">서비스에서 사용할 이름이에요. ${escapeHtml(NICKNAME_HELP_TEXT)}</p>
      <form class="nickname-form" novalidate>
        <label class="field" for="nickname-input"><span>새 닉네임</span></label>
        <div class="input-wrap">${icon("user", { size: 18 })}<input id="nickname-input" name="nickname" autocomplete="nickname" placeholder="${escapeHtml(NICKNAME_HELP_TEXT)}" aria-describedby="nickname-desc nickname-count nickname-error" /></div>
        <div class="nickname-meta"><span class="nickname-error" id="nickname-error" role="alert"></span><small id="nickname-count" aria-live="polite"></small></div>
        <div class="modal-actions">
          <button class="btn btn-secondary" type="button" data-action="cancel">취소</button>
          <button class="btn btn-primary" type="submit" data-action="save">저장</button>
        </div>
      </form>
    `,
  });
  const dialog = element.querySelector(".modal");
  dialog.setAttribute("aria-labelledby", "nickname-title");
  const form = element.querySelector(".nickname-form");
  const input = form.elements.nickname;
  const count = element.querySelector("#nickname-count");
  const errorEl = element.querySelector("#nickname-error");
  const saveButton = form.querySelector('[data-action="save"]');
  const cancelButton = form.querySelector('[data-action="cancel"]');
  input.value = nickname;

  // 규칙은 바꿀 때만 검사한다: 모달을 연 직후(현재 닉네임)에는 오류를 보이지 않고, 입력을 고친 뒤부터 알린다.
  // 입력 중에는 규칙 위반(문자·연속 공백·길이·한글/영문/숫자 포함)을 바로 알리고, 빈 값·같은 값은 저장 버튼을 막는 것으로 알린다.
  let edited = false;
  const LIVE_CODES = ["invalidChar", "consecutiveSpaces", "length", "needLetter"];
  const update = ({ showAll = false } = {}) => {
    const length = nicknameLength(input.value);
    const result = validateNickname(input.value, { current: nickname });
    count.textContent = `${length}/${maxLength}자`;
    count.classList.toggle("over", length > maxLength);
    const message = !result.ok && (showAll || (edited && LIVE_CODES.includes(result.code))) ? result.message : "";
    errorEl.textContent = message;
    input.setAttribute("aria-invalid", String(Boolean(message)));
    saveButton.disabled = saving || !result.ok;
    return result;
  };
  const setSaving = (value) => {
    saving = value;
    dialog.setAttribute("aria-busy", String(value));
    input.disabled = value;
    cancelButton.disabled = value;
    saveButton.textContent = value ? "저장 중…" : "저장";
    update();
  };

  input.addEventListener("input", () => { edited = true; update(); });
  cancelButton.addEventListener("click", () => { close(); restoreFocus(); });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving) return;
    const result = update({ showAll: true });
    if (!result.ok) { input.focus(); return; }
    setSaving(true);
    try {
      const saved = await saveNickname(result.value);
      nickname = typeof saved === "string" && saved.trim() ? saved.trim() : result.value;
      renderProfile();
      if (element.isConnected) close();
      restoreFocus();
      showToast("닉네임을 변경했어요. 서버 저장은 아직 연결 전이라 이 화면에만 반영돼요.");
    } catch (error) {
      if (!element.isConnected) return;
      setSaving(false);
      errorEl.textContent = error?.message || "닉네임을 저장하지 못했어요. 다시 시도해 주세요.";
      input.setAttribute("aria-invalid", "true");
      input.focus();
    }
  });

  update();
  input.focus();
  input.select();
}

// --- 02 즐겨찾기 ---

function renderFavorites(list) {
  const places = pickFavorites(list);
  if (!places.length) {
    favoritesBox.innerHTML = `
      <div class="empty-state my-empty">
        <span>${icon("star", { size: 22 })}</span>
        <b>저장된 장소가 없어요</b>
        <p>자주 가는 장소를 추가하면 여기에서 바로 확인할 수 있어요.</p>
        <a class="btn btn-primary" href="/pages/favorites.html">장소 추가하러 가기</a>
      </div>`;
    return;
  }
  favoritesBox.innerHTML = `<ul class="my-favorites-grid" aria-label="즐겨찾기 장소 (최대 3개)">${places.map((place) => `
    <li><button class="my-favorite-card" type="button"
        data-name="${escapeHtml(place.name)}" data-address="${escapeHtml(place.address)}"
        data-lat="${place.lat ?? ""}" data-lng="${place.lng ?? ""}"
        aria-label="${escapeHtml(`${place.name}, ${place.addressText}`)}">
      <span aria-hidden="true">${icon(PLACE_ICONS[place.type] ?? "location", { size: 20 })}</span>
      <div><b>${escapeHtml(place.name)}</b><small class="${place.hasAddress ? "" : "is-missing"}">${escapeHtml(place.addressText)}</small></div>
      ${icon("arrow", { size: 17 })}
    </button></li>`).join("")}</ul>`;
  favoritesBox.querySelectorAll(".my-favorite-card").forEach((card, index) => {
    card.addEventListener("click", () => openFavoriteInSearch(places[index], { notify: (message) => showToast(message) }));
  });
}

// --- 03 이용 통계 ---

function renderStats(stats) {
  const summary = weeklySummary(stats);
  periodEl.textContent = `최근 7일 · ${summary.period}`;
  const bars = summary.series.map((day, index) => `
    <li class="${index === summary.series.length - 1 ? "is-today" : ""}">
      <span class="my-bar" style="--h:${(summary.heights[index] / BAR_MAX_HEIGHT).toFixed(4)}">${day.count ? `<i aria-hidden="true">${day.count}</i>` : ""}</span>
      <small aria-hidden="true">${index === summary.series.length - 1 ? "오늘" : day.weekday}</small>
      <span class="my-sr-only">${day.month}월 ${day.day}일 ${day.weekday}요일 ${day.count}회</span>
    </li>`).join("");
  statsBox.innerHTML = `
    <div class="my-usage-layout">
      <div class="my-stat-list">
        <div><span class="my-stat-icon blue">${icon("search", { size: 19 })}</span><p><small>길찾기 검색</small><strong>${summary.empty ? "–" : `${summary.total.toLocaleString("ko-KR")}회`}</strong></p></div>
        <div><span class="my-stat-icon orange">${icon("location", { size: 19 })}</span><p><small>가장 많이 간 곳</small><strong title="${escapeHtml(summary.topPlace ?? "")}">${escapeHtml(summary.topPlace ?? "–")}</strong></p></div>
      </div>
      <div class="my-usage-chart">
        <div class="my-chart-head"><div><b id="weekly-chart-title">주간 검색 횟수</b><small>최근 7일 · 오늘 포함</small></div><strong>총 ${summary.total.toLocaleString("ko-KR")}회</strong></div>
        <ol class="my-bars${summary.empty ? " is-empty" : ""}" aria-labelledby="weekly-chart-title">${bars}</ol>
        ${summary.empty ? '<p class="my-chart-empty" role="status">최근 7일 동안 검색 기록이 없어요. 길찾기를 하면 여기에 쌓여요.</p>' : ""}
      </div>
    </div>`;
}

// --- 시작·계정 전환 ---

const loadFavoritesSection = sectionLoader(favoritesBox, {
  load: loadFavorites, render: renderFavorites,
  loadingText: "즐겨찾기를 불러오는 중이에요…", errorText: "즐겨찾기를 불러오지 못했어요.",
});
const loadStatsSection = sectionLoader(statsBox, {
  load: () => loadWeeklyStats(), render: renderStats,
  loadingText: "이용 통계를 불러오는 중이에요…", errorText: "이용 통계를 불러오지 못했어요.",
});

function init() {
  const user = getUser();
  if (!user) return;
  ownerId = user.id;
  nickname = user.name || "길잇 사용자";
  renderIcons();
  renderProfile();
  loadFavoritesSection();
  loadStatsSection();
}

requirePageAccess().then(init);

// 다른 계정으로 바뀌면 이전 계정 화면을 버리고 다시 그린다. 로그아웃은 guard.js가 길찾기로 보낸다.
onAuthChange(() => {
  const user = getUser();
  if (!user) {
    loadFavoritesSection.cancel();
    loadStatsSection.cancel();
    return;
  }
  if (user.id !== ownerId) init();
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted) location.reload(); // 즐겨찾기 화면과 같은 방식: 초기 인증 검사부터 다시
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") recheckAuth();
});
