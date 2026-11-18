import { USE_MOCK_ROUTES as USE_MOCK } from "/js/config.js";
import { setupAutocomplete } from "/js/components/placeAutocomplete.js";
import { getFavorites, getHistory } from "/js/api.js";
import { getUser, initializeAuth, isRedirecting, onAuthChange, recheckAuth } from "/js/auth.js";
import { icon, renderIcons } from "/js/components/icon.js";
import { showToast } from "/js/components/toast.js";
import {
  buildResultUrl,
  dateOf,
  escapeHtml,
  formatRelativeDate,
  historyCoordinates,
  isValidDate,
  isValidTime,
  nextDateForTime,
  placeAddress,
  queryCoordinates,
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
  // 자동완성으로 고른 목적지는 주소를 안다. 결과 화면의 별 저장이 주소로 쓰도록 함께 넘긴다 (형식이 맞을 때만).
  const toAddress = placeAddress(autocompletes[1].getPlace()?.address);
  goToResult({ from, to, date: dateInput.value, time: timeInput.value, buffer, ...coordinates, ...(toAddress ? { toAddress } : {}) });
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
      // 즐겨찾기 좌표를 출발지 선택값으로 넣어 경로 조회가 이름 검색(422) 대신 좌표를 쓰게 한다. 없으면 이전 선택을 비운다.
      const { fromLat: lat, fromLng: lng } = historyCoordinates({ fromLat: place.lat, fromLng: place.lng });
      autocompletes[0].setPlace(lat === undefined ? null : { name: place.name, lat, lng });
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
      // 기록의 좌표를 선택된 장소로 넣어 submit이 결과 화면에 좌표를 넘기게 한다. 좌표가 없는 쪽은 선택을 비운다.
      const coordinates = historyCoordinates(item);
      ["from", "to"].forEach((prefix, index) => {
        const lat = coordinates[`${prefix}Lat`], lng = coordinates[`${prefix}Lng`];
        autocompletes[index].setPlace(lat === undefined ? null : { name: item[prefix], lat, lng });
      });
      submit();
    });
    grid.append(button);
  });
}

// 로그인 상태가 확정된 뒤(initializeAuth)와 로그인·로그아웃할 때마다 다시 그린다.
// 비로그인이면 서버를 부르지 않는다 (둘 다 401이라 토스트만 뜬다).
let savedDataGeneration = 0;
function clearSavedData() {
  const quickPlaces = document.getElementById("quick-places");
  quickPlaces.querySelectorAll("button").forEach((button) => button.remove());
  document.getElementById("recent-grid").replaceChildren();
}

async function loadSavedData() {
  const generation = ++savedDataGeneration;
  clearSavedData();
  const loggedIn = Boolean(getUser());
  document.getElementById("quick-places").hidden = !loggedIn;
  document.getElementById("recent-grid").hidden = !loggedIn;
  document.getElementById("recent-login-hint").hidden = loggedIn;
  if (!loggedIn || isRedirecting()) return;

  const [favorites, history] = await Promise.allSettled([getFavorites(), getHistory()]);
  // 응답을 기다리는 사이 로그아웃하거나 다른 계정으로 로그인했다면 버린다.
  if (generation !== savedDataGeneration) return;
  if (favorites.status === "fulfilled") renderQuickPlaces(favorites.value);
  if (history.status === "fulfilled") renderRecent(history.value);
  const failed = [favorites.status === "rejected" && "즐겨찾기를", history.status === "rejected" && "최근 검색을"].filter(Boolean);
  if (failed.length === 2) showToast("저장된 정보를 불러오지 못했어요", { error: true });
  else if (failed.length === 1) showToast(`${failed[0]} 불러오지 못했어요`, { error: true });
}

renderIcons();
fillForm();
setLoading(false);
autocompletes.push(setupAutocomplete(fromInput), setupAutocomplete(toInput));
const restoredQuery = new URLSearchParams(location.search);
// 쿼리 좌표(조건 수정, 즐겨찾기 "여기서 출발")를 선택된 장소로 복원한다. 범위 밖·숫자 아님은 무시한다.
// 입력칸을 고치면 자동완성이 선택을 풀고(getPlace는 이름이 같을 때만 돌려준다) 이전 좌표로 조회하지 않는다.
["from", "to"].forEach((prefix, index) => {
  const coordinate = queryCoordinates(restoredQuery, prefix);
  if (coordinate) {
    // "조건 수정"으로 돌아왔을 때 목적지 주소도 되살려 다시 제출할 때 잃지 않게 한다.
    const address = prefix === "to" ? placeAddress(restoredQuery.get("toAddress")) : null;
    autocompletes[index].setPlace({ name: form.elements[prefix].value, ...coordinate, ...(address ? { address } : {}) });
  }
});
if (USE_MOCK) {
  document.getElementById("place-search-hint").textContent = "예시 장소 검색: 김해·부산의 제공된 예시 장소에서 이름과 주소를 검색합니다. 장소명 직접 입력도 가능해요.";
}
initializeAuth().then(() => {
  loadSavedData();
  onAuthChange(loadSavedData);
});

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
// 복원된 화면은 떠날 때의 계정 상태 그대로라 세션을 다시 확인한다. 계정이 바뀌었거나 로그아웃됐으면
// recheckAuth가 인증 변경 이벤트를 내고, onAuthChange(loadSavedData)가 현재 계정의 데이터로 다시 그린다.
// 늦게 온 이전 계정 응답은 loadSavedData의 세대 번호로 버려진다.
window.addEventListener("pageshow", (event) => {
  clearTimeout(navigationTimer);
  setLoading(false);
  if (event.persisted) recheckAuth();
});
// 다른 탭에서 계정을 바꾸고 이 탭으로 돌아온 경우
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") recheckAuth();
});
window.addEventListener("pagehide", () => {
  clearTimeout(navigationTimer);
  autocompletes.forEach((autocomplete) => autocomplete.close());
});
