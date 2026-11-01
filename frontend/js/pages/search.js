import { getFavorites, getHistory, searchPlaces } from "/js/api.js";
import { icon, renderIcons } from "/js/components/icon.js";
import { showToast } from "/js/components/toast.js";
import {
  buildResultUrl,
  dateOf,
  escapeHtml,
  formatRelativeDate,
  isValidDate,
  isValidTime,
  nextDateForTime,
  timeOf,
} from "/js/utils.js";

const DEFAULT_TIME = "09:00";
const DEFAULT_BUFFER = "10";
const QUICK_PLACE_ICONS = { 집: "home", 학교: "star", 회사: "wallet" };
const AUTOCOMPLETE_DELAY_MS = 150;
const SEARCH_DELAY_MS = 850;
const REPEAT_DELAY_MS = 650;

const form = document.getElementById("search-form");
const fromInput = form.elements.from;
const toInput = form.elements.to;
const dateInput = form.elements.date;
const timeInput = form.elements.time;
const submitButton = document.getElementById("search-submit");
const bufferButtons = document.querySelectorAll("[data-buffer]");

let buffer = DEFAULT_BUFFER;

function setBuffer(value) {
  buffer = value;
  bufferButtons.forEach((button) => button.classList.toggle("active", button.dataset.buffer === value));
}

function setLoading(loading) {
  submitButton.disabled = loading;
  submitButton.innerHTML = loading
    ? '<span class="spinner"></span> 최적의 출발시각을 찾는 중...'
    : `${icon("search", { size: 19 })} 출발시각 찾기`;
}

// 조건 수정이나 "여기서 출발"로 들어오면 쿼리 값으로 폼을 채운다.
function fillForm() {
  const query = new URLSearchParams(location.search);
  fromInput.value = query.get("from") ?? "";
  toInput.value = query.get("to") ?? "";
  const time = query.get("time");
  timeInput.value = isValidTime(time) ? time : DEFAULT_TIME;
  const date = query.get("date");
  dateInput.value = isValidDate(date) ? date : nextDateForTime(timeInput.value);
  const queryBuffer = query.get("buffer");
  const isKnownBuffer = [...bufferButtons].some((button) => button.dataset.buffer === queryBuffer);
  setBuffer(isKnownBuffer ? queryBuffer : DEFAULT_BUFFER);
}

function goToResult(data, delay) {
  setLoading(true);
  setTimeout(() => location.assign(buildResultUrl(data)), delay);
}

function submit() {
  const from = fromInput.value.trim();
  const to = toInput.value.trim();
  if (!from || !to) {
    showToast("출발지와 목적지를 입력해 주세요", { error: true });
    return;
  }
  if (!isValidDate(dateInput.value) || !isValidTime(timeInput.value)) {
    showToast("도착 날짜와 시각을 입력해 주세요", { error: true });
    return;
  }
  goToResult({ from, to, date: dateInput.value, time: timeInput.value, buffer }, SEARCH_DELAY_MS);
}

function setupAutocomplete(input) {
  const field = input.closest(".field");
  let requestId = 0;
  let timer = null;

  const close = () => {
    requestId += 1;
    clearTimeout(timer);
    field.querySelector(".autocomplete")?.remove();
  };

  const open = async () => {
    const currentRequest = ++requestId;
    let places;
    try {
      places = await searchPlaces(input.value.trim());
    } catch {
      return;
    }
    if (currentRequest !== requestId) return;

    field.querySelector(".autocomplete")?.remove();
    if (places.length === 0) return;
    const list = document.createElement("div");
    list.className = "autocomplete";
    list.innerHTML = `
      <div class="autocomplete-label">추천 장소</div>
      ${places.map((place) => `<button type="button" data-name="${escapeHtml(place.name)}"><span>${icon("location", { size: 17 })}</span><div><b>${escapeHtml(place.name)}</b><small>${escapeHtml(place.address)}</small></div></button>`).join("")}
    `;
    // 누르는 순간 입력칸의 포커스를 잃지 않게 해서 목록이 먼저 닫히지 않도록 한다.
    list.addEventListener("mousedown", (event) => event.preventDefault());
    list.addEventListener("click", (event) => {
      const button = event.target.closest("[data-name]");
      if (!button) return;
      event.preventDefault();
      input.value = button.dataset.name;
      close();
    });
    field.append(list);
  };

  input.addEventListener("focus", open);
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(open, AUTOCOMPLETE_DELAY_MS);
  });
  input.addEventListener("blur", (event) => {
    if (!field.contains(event.relatedTarget)) close();
  });
}

function renderQuickPlaces(favorites) {
  const container = document.getElementById("quick-places");
  favorites.slice(0, 3).forEach((place) => {
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = `${icon(QUICK_PLACE_ICONS[place.type] ?? "location", { size: 15 })}${escapeHtml(place.name)}`;
    button.addEventListener("click", () => {
      fromInput.value = place.name;
    });
    container.append(button);
  });
}

function renderRecent(history) {
  const grid = document.getElementById("recent-grid");
  history.forEach((item) => {
    const time = timeOf(item.arriveTime);
    const button = document.createElement("button");
    button.className = "recent-card";
    button.type = "button";
    button.innerHTML = `
      <span class="recent-icon">${icon("clock", { size: 18 })}</span>
      <div class="recent-main"><div><b>${escapeHtml(item.from)}</b>${icon("arrow", { size: 14 })}<b>${escapeHtml(item.to)}</b></div><span>${formatRelativeDate(dateOf(item.arriveTime))} · ${time} 도착</span></div>
      ${icon("arrow", { size: 18 })}
    `;
    button.addEventListener("click", () => {
      fromInput.value = item.from;
      toInput.value = item.to;
      timeInput.value = time;
      dateInput.value = nextDateForTime(time);
      goToResult({ from: item.from, to: item.to, date: dateInput.value, time, buffer }, REPEAT_DELAY_MS);
    });
    grid.append(button);
  });
}

async function loadSavedData() {
  const [favorites, history] = await Promise.allSettled([getFavorites(), getHistory()]);
  if (favorites.status === "fulfilled") renderQuickPlaces(favorites.value);
  if (history.status === "fulfilled") renderRecent(history.value);
  if (favorites.status === "rejected" || history.status === "rejected") {
    showToast("저장된 정보를 불러오지 못했어요", { error: true });
  }
}

renderIcons();
fillForm();
setLoading(false);
setupAutocomplete(fromInput);
setupAutocomplete(toInput);
loadSavedData();

bufferButtons.forEach((button) => {
  button.addEventListener("click", () => setBuffer(button.dataset.buffer));
});
document.getElementById("swap-button").addEventListener("click", () => {
  [fromInput.value, toInput.value] = [toInput.value, fromInput.value];
});
form.addEventListener("submit", (event) => {
  event.preventDefault();
  submit();
});
// 뒤로 가기로 돌아왔을 때(bfcache) 로딩 표시가 남지 않게 한다.
window.addEventListener("pageshow", () => setLoading(false));
