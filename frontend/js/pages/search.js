import { USE_MOCK_ROUTES as USE_MOCK } from "/js/config.js";
import { setupAutocomplete } from "/js/components/placeAutocomplete.js";
import { getFavorites, getHistory } from "/js/api.js";
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
  validateSearchConditions,
} from "/js/utils.js";

const DEFAULT_TIME = "09:00";
const DEFAULT_BUFFER = "10";
const QUICK_PLACE_ICONS = { 집: "home", 학교: "star", 회사: "wallet" };
const SEARCH_DELAY_MS = 300;

const form = document.getElementById("search-form");
const fromInput = form.elements.from;
const toInput = form.elements.to;
const dateInput = form.elements.date;
const timeInput = form.elements.time;
const submitButton = document.getElementById("search-submit");
const bufferButtons = document.querySelectorAll("[data-buffer]");

let buffer = DEFAULT_BUFFER;
let submitting = false;
let navigationTimer;
const autocompletes = [];

function setBuffer(value) {
  buffer = value;
  bufferButtons.forEach((button) => {
    const selected = button.dataset.buffer === value;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function setLoading(loading) {
  submitting = loading;
  submitButton.disabled = loading;
  form.setAttribute("aria-busy", String(loading));
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

function showValidation(error) {
  showToast(error.message, { error: true });
  const control = error.field === "buffer" ? bufferButtons[0] : form.elements[error.field];
  control.focus();
}

function goToResult(data) {
  if (submitting) return;
  const error = validateSearchConditions(data);
  if (error) { showValidation(error); return; }
  autocompletes.forEach((autocomplete) => autocomplete.close());
  setLoading(true);
  navigationTimer = setTimeout(() => {
    // 분 경계를 지난 경우에도 이미 지난 시각을 제출하지 않는다.
    const latestError = validateSearchConditions(data);
    if (latestError) { setLoading(false); showValidation(latestError); return; }
    location.assign(buildResultUrl(data));
  }, SEARCH_DELAY_MS);
}

function submit() {
  if (submitting) return;
  const from = fromInput.value.trim();
  const to = toInput.value.trim();
  fromInput.value = from;
  toInput.value = to;
  const coordinates = {};
  ["from", "to"].forEach((prefix, index) => {
    const place = autocompletes[index].getPlace();
    if (place && Number.isFinite(place.lat) && Number.isFinite(place.lng)) {
      coordinates[`${prefix}Lat`] = place.lat;
      coordinates[`${prefix}Lng`] = place.lng;
    }
  });
  goToResult({ from, to, date: dateInput.value, time: timeInput.value, buffer, ...coordinates });
}

function renderQuickPlaces(favorites) {
  const container = document.getElementById("quick-places");
  favorites.slice(0, 3).forEach((place) => {
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = `${icon(QUICK_PLACE_ICONS[place.type] ?? "location", { size: 15 })}${escapeHtml(place.name)}`;
    button.addEventListener("click", () => {
      autocompletes.forEach((autocomplete) => autocomplete.close());
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
      <div class="recent-main"><div><b>${escapeHtml(item.from)}</b>${icon("arrow", { size: 14 })}<b>${escapeHtml(item.to)}</b></div><span>${formatRelativeDate(dateOf(item.arriveTime))} · ${escapeHtml(time)} 도착</span></div>
      ${icon("arrow", { size: 18 })}
    `;
    button.addEventListener("click", () => {
      fromInput.value = item.from;
      toInput.value = item.to;
      timeInput.value = time;
      dateInput.value = nextDateForTime(time);
      submit();
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
autocompletes.push(setupAutocomplete(fromInput), setupAutocomplete(toInput));
const restoredQuery = new URLSearchParams(location.search);
["from", "to"].forEach((prefix, index) => {
  const lat = restoredQuery.get(`${prefix}Lat`), lng = restoredQuery.get(`${prefix}Lng`);
  if (lat !== null && lng !== null && lat.trim() && lng.trim() && Number.isFinite(Number(lat)) && Number.isFinite(Number(lng))) {
    autocompletes[index].setPlace({ name: form.elements[prefix].value, lat: Number(lat), lng: Number(lng) });
  }
});
if (USE_MOCK) {
  document.getElementById("place-search-hint").textContent = "예시 장소 검색: 김해·부산의 제공된 예시 장소에서 이름과 주소를 검색합니다. 장소명 직접 입력도 가능해요.";
}
loadSavedData();

bufferButtons.forEach((button) => {
  button.addEventListener("click", () => setBuffer(button.dataset.buffer));
});
document.getElementById("swap-button").addEventListener("click", () => {
  const selected = autocompletes.map((autocomplete) => autocomplete.getPlace());
  autocompletes.forEach((autocomplete) => autocomplete.close());
  [fromInput.value, toInput.value] = [toInput.value, fromInput.value];
  autocompletes[0].setPlace(selected[1]);
  autocompletes[1].setPlace(selected[0]);
});
form.addEventListener("submit", (event) => {
  event.preventDefault();
  submit();
});
// 뒤로 가기로 돌아왔을 때(bfcache) 로딩 표시가 남지 않게 한다.
window.addEventListener("pageshow", () => {
  clearTimeout(navigationTimer);
  setLoading(false);
});
window.addEventListener("pagehide", () => {
  clearTimeout(navigationTimer);
  autocompletes.forEach((autocomplete) => autocomplete.close());
});
