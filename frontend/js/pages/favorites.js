import { getUser, onAuthChange } from "/js/auth.js";
import { addFavorite, getFavorites, getHistory, removeFavorite } from "/js/api.js";
import { openAddPlaceModal } from "/js/components/addPlaceModal.js";
import { icon, renderIcons } from "/js/components/icon.js";
import { showToast } from "/js/components/toast.js";
import { requirePageAccess } from "/js/guard.js";
import {
  buildResultUrl,
  dateOf,
  escapeHtml,
  formatRelativeDate,
  nextDateForTime,
  timeOf,
} from "/js/utils.js";

const PLACE_ICONS = { 집: "home", 회사: "wallet", 학교: "star" };
const REPEAT_BUFFER = 10;

const content = document.getElementById("saved-content");
const addButton = document.getElementById("add-place-button");
const newSearchLink = document.getElementById("new-search-link");
const tabButtons = document.querySelectorAll("[data-tab]");

let tab = new URLSearchParams(location.search).get("tab") === "history" ? "history" : "favorites";
let generation = 0;
let favorites = [];
let history = [];

function renderPlaceCard(place) {
  const name = escapeHtml(place.name);
  return `
    <article class="saved-card place-card">
      <span class="saved-icon">${icon(PLACE_ICONS[place.type] ?? "location", { size: 20 })}</span>
      <div class="saved-info"><div class="saved-title">${name}<span class="place-type">${escapeHtml(place.type)}</span></div><span>${icon("location", { size: 14 })} ${escapeHtml(place.address)}</span></div>
      <a class="saved-search" href="/pages/search.html?${new URLSearchParams({ from: place.name })}">여기서 출발 ${icon("arrow", { size: 15 })}</a>
      <button class="delete-button" type="button" data-delete="${escapeHtml(place.id)}" aria-label="${name} 삭제">${icon("close", { size: 17 })}</button>
    </article>
  `;
}

function renderHistoryCard(item) {
  const time = timeOf(item.arriveTime);
  const repeatUrl = buildResultUrl({
    from: item.from,
    to: item.to,
    date: nextDateForTime(time),
    time,
    buffer: REPEAT_BUFFER,
  });
  return `
    <article class="saved-card">
      <span class="saved-icon history">${icon("clock", { size: 20 })}</span>
      <div class="saved-info"><div class="history-route"><b>${escapeHtml(item.from)}</b>${icon("arrow", { size: 15 })}<b>${escapeHtml(item.to)}</b></div><span>${icon("clock", { size: 14 })} ${formatRelativeDate(dateOf(item.arriveTime))} · ${time} 도착</span></div>
      <span class="history-arrival"><small>도착 희망 시각</small><b>${time}</b></span>
      <a class="saved-search" href="${escapeHtml(repeatUrl)}">다시 검색 ${icon("arrow", { size: 15 })}</a>
    </article>
  `;
}

function renderEmptyState() {
  return `
    <div class="empty-state">
      <span>${icon("star", { size: 24 })}</span>
      <b>저장된 장소가 없어요</b>
      <p>자주 가는 장소를 추가해 더 빠르게 길을 찾아보세요.</p>
      <button class="btn btn-primary" type="button" data-action="add">장소 추가</button>
    </div>
  `;
}

function render() {
  tabButtons.forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
  document.getElementById("favorites-count").textContent = favorites.length;
  document.getElementById("history-count").textContent = history.length;
  addButton.hidden = tab !== "favorites";
  newSearchLink.hidden = tab !== "history";

  if (tab === "history") {
    content.innerHTML = history.map(renderHistoryCard).join("");
  } else {
    content.innerHTML = favorites.length > 0 ? favorites.map(renderPlaceCard).join("") : renderEmptyState();
  }
}

function openAddModal() {
  const owner = getUser();
  const current = generation;
  openAddPlaceModal({
    onAdd: async (place) => {
      if (!owner || owner !== getUser() || current !== generation) return;
      try {
        const created = await addFavorite(place);
        if (current !== generation) return;
        favorites = [...favorites, created];
        render();
      } catch {
        showToast("장소를 저장하지 못했어요", { error: true });
      }
    },
  });
}

async function deletePlace(id) {
  const current = generation;
  if (!getUser()) return;
  try {
    await removeFavorite(id);
    if (current !== generation) return;
    favorites = favorites.filter((place) => place.id !== id);
    render();
  } catch {
    showToast("장소를 삭제하지 못했어요", { error: true });
  }
}

async function init() {
  const current = ++generation;
  if (!getUser()) return;
  renderIcons();
  render();

  const [favoritesResult, historyResult] = await Promise.allSettled([getFavorites(), getHistory()]);
  if (current !== generation) return;
  if (favoritesResult.status === "fulfilled") favorites = favoritesResult.value;
  if (historyResult.status === "fulfilled") history = historyResult.value;
  if (favoritesResult.status === "rejected" || historyResult.status === "rejected") {
    showToast("저장된 정보를 불러오지 못했어요", { error: true });
  }
  render();
}

tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    tab = button.dataset.tab;
    render();
  });
});
addButton.addEventListener("click", openAddModal);
content.addEventListener("click", (event) => {
  const deleteButton = event.target.closest("[data-delete]");
  if (deleteButton) deletePlace(deleteButton.dataset.delete);
  if (event.target.closest('[data-action="add"]')) openAddModal();
});

requirePageAccess().then(init);

// 메모리와 BFCache의 화면도 인증 경계에서 폐기한다. 저장된 데이터는 지우지 않는다.
function clearFavoriteView() {
  generation++;
  favorites = [];
  render();
}
onAuthChange(() => {
  clearFavoriteView();
  if (getUser()) init();
});
window.addEventListener("pagehide", clearFavoriteView);
window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    clearFavoriteView();
    location.reload(); // 초기 인증 검사를 다시 수행한 뒤 현재 계정 목록을 조회한다.
  }
});
