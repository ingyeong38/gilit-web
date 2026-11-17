import { normalizeRouteGraphs } from "/js/components/durationGraph.js?v=card530-20261114-6";
import { USE_MOCK as USE_MOCK_FAVORITES, USE_MOCK_ROUTES as USE_MOCK } from "/js/config.js";
import { getUser, initializeAuth, onAuthChange } from "/js/auth.js";
import { addFavorite, getFavorites, getRouteGraph, getRoutes, removeFavorite, searchPlaces } from "/js/api.js";
import { renderDurationChart } from "/js/components/charts.js?v=card530-20261114-6";
import { icon, renderIcons } from "/js/components/icon.js";
import { renderRouteMap } from "/js/components/map.js";
import { showToast } from "/js/components/toast.js";
import {
  ROUTE_COLORS,
  dateOf,
  escapeHtml,
  formatBuffer,
  formatFullDate,
  formatRouteLabel,
  formatWon,
  validateSearchConditions,
  timeOf,
  toIsoTime,
} from "/js/utils.js";

const page = document.querySelector(".results-page");

function readSearchQuery() {
  const query = new URLSearchParams(location.search);
  const from = query.get("from")?.trim();
  const to = query.get("to")?.trim();
  const date = query.get("date");
  const time = query.get("time");
  const buffer = Number(query.get("buffer") ?? 0);
  const coordinates = {};
  for (const key of ["fromLat", "fromLng", "toLat", "toLng"]) {
    if (query.has(key)) coordinates[key] = query.get(key);
  }
  return { from, to, date, time, buffer, ...coordinates };
}

function renderMessage({ title, text }) {
  page.innerHTML = `
    <div class="results-shell">
      <div class="empty-state">
        <span>${icon("search", { size: 24 })}</span>
        <b>${escapeHtml(title)}</b>
        <p>${escapeHtml(text)}</p>
        <a class="btn btn-primary" href="/pages/search.html${escapeHtml(location.search)}">조건 수정</a>
      </div>
    </div>
  `;
}

function renderSummary({ from, to, date, time, buffer }) {
  document.getElementById("summary-from").textContent = from;
  document.getElementById("summary-to").textContent = to;
  document.getElementById("summary-date").textContent = formatFullDate(date);
  document.getElementById("summary-time").textContent = time;
  document.getElementById("summary-buffer").textContent = `여유 ${formatBuffer(buffer)}`;
  document.getElementById("edit-link").href = `/pages/search.html${location.search}`;
}

// 서버는 지금 출발해도 여유를 둘 수 없으면 여유 없이 계산하고 bufferApplied=false를 준다 (여유 0분 요청도 false).
// 목업(routes.json)에는 이 필드가 없으므로 없으면 반영된 것으로 본다.
function renderBufferNote(route, buffer) {
  if (buffer > 0 && route.bufferApplied === false) {
    return '<span class="buffer-missed">여유시간 미반영</span>';
  }
  return `<span>여유 ${formatBuffer(buffer)}</span>`;
}

function renderRouteCard(route, index, { date, buffer }) {
  const isPreviousDay = dateOf(route.departTime) !== date;
  return `
    <article class="route-card" role="button" tabindex="0" aria-pressed="false" data-index="${index}">
      <div class="route-card-head">
        <span class="route-tag tag-${index}">${index === 0 ? icon("spark", { size: 13 }) : ""}${escapeHtml(formatRouteLabel(route))}</span>
      </div>
      <div class="route-name">${escapeHtml(route.name)}</div>
      <div class="departure-label">권장 출발${isPreviousDay ? " (전날)" : ""}</div>
      <div class="departure-time">${timeOf(route.departTime)}</div>
      <div class="route-details">
        ${[
          ["예상 소요시간", typeof route.durationMin === "number" ? `${route.durationMin}분` : "미제공"],
          ["거리", typeof route.distanceKm === "number" ? `${route.distanceKm}km` : "미제공"],
          ["통행료", route.toll == null ? "미제공" : formatWon(route.toll)],
        ].map(([title, value]) => `<div class="route-metric"><small>${title}</small><b>${escapeHtml(value)}</b></div>`).join("")}
      </div>
      <div class="arrival-info"><div class="arrival-main">${icon("check", { size: 20 })}<b>${escapeHtml(timeOf(route.arriveTime))} 도착 예정</b></div>${renderBufferNote(route, buffer)}</div>
    </article>
  `;
}

const PLACE_REQUIRED = "목적지 위치를 알 수 없어요. 장소를 검색해서 선택해 주세요.";

// 즐겨찾기는 장소 단위라 별은 요약 바의 도착지 이름(#summary-to) 바로 옆에 하나만 둔다 (result.html #destination-star).
// id는 서버 생성 응답이나 목록에서 받은 값이고, 해제(DELETE ?id=)에 쓴다. null이면 저장 안 됨.
let destinationFavoriteId = null;
let favoriteGeneration = 0;
let favoriteBusy = false;

// URL 쿼리의 좌표(문자열). 비었거나 범위를 벗어나면 null.
function readCoordinate(value, limit) {
  if (typeof value !== "string" || !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) && Math.abs(number) <= limit ? number : null;
}

function favoriteErrorMessage(error, fallback) {
  return error?.status >= 400 && error.status < 500 && error.message ? error.message : fallback;
}

function renderStar() {
  const star = document.getElementById("destination-star");
  if (!star) return;
  const active = destinationFavoriteId !== null;
  star.classList.toggle("active", active);
  star.setAttribute("aria-pressed", String(active));
}

// 로그인 계정이 바뀌면 이전 계정의 별 상태를 버리고 현재 계정 목록에서 다시 찾는다.
async function loadDestinationFavorite(name) {
  const current = ++favoriteGeneration;
  destinationFavoriteId = null;
  renderStar();
  if (!getUser()) return;
  try {
    const favorites = await getFavorites();
    if (current !== favoriteGeneration) return;
    destinationFavoriteId = favorites.find((place) => place.name === name)?.id ?? null;
    renderStar();
  } catch {
    // 별은 비어 있는 상태로 둔다. 누르면 다시 목록을 확인한다.
  }
}

// 이번 검색의 목적지를 저장한다. 같은 이름이 이미 있으면 그 항목을 돌려준다.
async function saveDestination({ to: name, toLat, toLng }) {
  const favorites = await getFavorites();
  const existing = favorites.find((place) => place.name === name);
  if (existing) return existing;
  const lat = readCoordinate(toLat, 90);
  const lng = readCoordinate(toLng, 180);
  const located = lat !== null && lng !== null;
  // 서버는 좌표가 없으면 이름으로 다시 찾다가 400을 낸다. 검색에서 고른 장소(좌표 있음)만 보낸다.
  if (!USE_MOCK_FAVORITES && !located) throw Object.assign(new Error(PLACE_REQUIRED), { status: 400 });
  const places = await searchPlaces(name);
  const address = places.find((place) => place.name === name)?.address ?? name;
  return addFavorite({ name, address, type: "기타", ...(located ? { lat, lng } : {}) });
}

async function toggleDestinationFavorite(search) {
  if (favoriteBusy) return;
  if (!getUser()) {
    showToast("로그인이 필요합니다.", { error: true });
    return;
  }
  const current = favoriteGeneration;
  const removing = destinationFavoriteId !== null;
  favoriteBusy = true;
  try {
    if (removing) {
      await removeFavorite(destinationFavoriteId);
      if (current !== favoriteGeneration) return;
      destinationFavoriteId = null;
      showToast("즐겨찾기에서 삭제했어요");
    } else {
      const saved = await saveDestination(search);
      if (current !== favoriteGeneration) return;
      destinationFavoriteId = saved.id;
      showToast("즐겨찾기에 저장했어요");
    }
    renderStar();
  } catch (error) {
    if (current !== favoriteGeneration) return;
    // 다른 화면에서 이미 지운 경우 (404) 별을 비운다.
    if (removing && error?.status === 404) {
      destinationFavoriteId = null;
      renderStar();
    }
    showToast(favoriteErrorMessage(error, removing ? "즐겨찾기를 해제하지 못했어요" : "즐겨찾기에 저장하지 못했어요"), { error: true });
  } finally {
    favoriteBusy = false;
  }
}

// 경로 카드가 나온 뒤에만 요약 바의 별을 보인다 (경로를 못 찾으면 화면 전체가 안내 문구로 바뀐다).
// 도착지 이름은 renderSummary가 #summary-to에 넣는다. 말줄임될 때를 위해 title에도 넣는다.
function watchDestinationFavorite(search) {
  const name = search.to;
  const label = document.getElementById("summary-to");
  const star = document.getElementById("destination-star");
  if (label) label.title = name; // 요약 바에서 말줄임될 때 전체 이름
  if (star) {
    star.hidden = false;
    star.addEventListener("click", () => toggleDestinationFavorite(search));
  }
  renderStar();
  initializeAuth().then(() => {
    loadDestinationFavorite(name);
    onAuthChange(() => loadDestinationFavorite(name));
  });
}

async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // http 배포 환경처럼 Clipboard API를 못 쓸 때의 대체 경로
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.append(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("복사 실패");
}

function setupShareButton() {
  document.getElementById("share-button").addEventListener("click", async () => {
    try {
      await copyToClipboard(location.href);
      showToast("경로 링크를 복사했어요");
    } catch {
      showToast("링크를 복사하지 못했어요", { error: true });
    }
  });
}

function setupResults(search, routes, graph = []) {
  let selectedIndex = 0;
  let graphs = normalizeRouteGraphs(graph, routes);
  let graphMessage = "소요시간 그래프를 불러오는 중입니다.";
  let exampleRoutes = [];
  let exampleId = null;
  let isExampleGraph = false;
  let exampleSelect = null;
  const list = document.getElementById("route-list");
  list.innerHTML = routes.map((route, index) => renderRouteCard(route, index, search)).join("");
  const cards = list.querySelectorAll(".route-card");
  const drawGraph = () => {
    const route = isExampleGraph ? exampleRoutes.find(route => route.id === exampleId) : routes[selectedIndex];
    const normalized = route && graphs.get(route.id);
    const durations = [...graphs.values()].flatMap(value => value.points.map(point => point.durationMin));
    const range = durations.length ? { min: Math.min(...durations), max: Math.max(...durations) } : undefined;
    const chart = document.getElementById("duration-chart");
    chart.setAttribute("aria-busy", String(graphMessage.includes("불러오는 중")));
    renderDurationChart(chart, { points: normalized?.points ?? [], discarded: normalized?.discarded ?? 0,
      color: isExampleGraph ? "#2563EB" : ROUTE_COLORS[selectedIndex % ROUTE_COLORS.length], recommendedTime: route?.departTime,
      range, routeName: isExampleGraph ? `개발용 예시 · 김해시청 → 동의대학교 · ${route?.name ?? "데이터 없음"} · 실제 선택 경로와 무관` : `${formatRouteLabel(route)} · ${route.name}`, routeId: route?.id ?? "", isExample: isExampleGraph,
      routeTag: route ? formatRouteLabel(route) : "", message: graphMessage || "선택 경로와 일치하는 유효한 그래프 데이터가 없습니다." });
  };

  const select = (index) => {
    selectedIndex = index;
    const route = routes[index];
    const color = ROUTE_COLORS[index % ROUTE_COLORS.length];
    cards.forEach((card, cardIndex) => {
      card.classList.toggle("selected", cardIndex === index);
      card.setAttribute("aria-pressed", String(cardIndex === index));
    });
    renderRouteMap(document.getElementById("route-map"), {
      route,
      routeIndex: index,
      color,
      from: USE_MOCK ? "김해시청" : search.from,
      to: USE_MOCK ? "동의대학교" : search.to,
      isExample: USE_MOCK,
    });
    drawGraph();
    document.querySelector(".ai-label").textContent = USE_MOCK ? "AI 경로 추천 요약" : "카카오 경로 안내";
    document.getElementById("ai-title").textContent = route.aiSummary.title;
    document.getElementById("ai-text").textContent = route.aiSummary.text;
  };

  cards.forEach((card, index) => {
    card.addEventListener("click", () => select(index));
    card.addEventListener("keydown", (event) => {
      if (event.target === card && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        select(index);
      }
    });
  });

  select(0);
  return ({ graphs: data = [], routes: samples = [], isExample = false, message = "" } = {}) => {
    isExampleGraph = isExample;
    exampleRoutes = samples;
    exampleId = samples[0]?.id ?? null;
    graphs = normalizeRouteGraphs(data, isExample ? samples : routes);
    graphMessage = message;
    exampleSelect?.remove();
    if (isExample && samples.length) {
      exampleSelect = document.createElement("label");
      exampleSelect.textContent = "개발용 예시 경로 (실제 경로와 별도) ";
      const select = document.createElement("select");
      select.setAttribute("aria-label", "개발용 예시 그래프 경로");
      samples.forEach(route => { const option = document.createElement("option"); option.value = route.id; option.textContent = `${route.label} · ${route.name}`; select.append(option); });
      select.addEventListener("change", () => { exampleId = select.value; drawGraph(); });
      exampleSelect.append(select);
      document.getElementById("duration-chart").before(exampleSelect);
    }
    drawGraph(); // 데이터 수신 때 지도를 다시 생성하거나 선택 경로를 초기화하지 않는다.
  };
}

async function init() {
  const search = readSearchQuery();
  const error = validateSearchConditions(search);
  if (error) {
    renderMessage({ title: "검색 조건을 확인해 주세요", text: error.message });
    return;
  }

  renderIcons();
  renderSummary(search);
  setupShareButton();
  if (USE_MOCK) document.querySelector(".results-heading p").textContent = "예시 데이터입니다. 지도는 김해시청 → 동의대학교 예시 경로를 표시합니다.";

  if (!USE_MOCK) document.querySelector(".results-heading p").textContent = "카카오 상세 도로 좌표와 해당 출발시각의 예상 소요시간을 표시합니다.";

  try {
    const arrive = toIsoTime(search.date, search.time);
    const routes = await getRoutes({ ...search, arrive });
    if (routes.length === 0) {
      renderMessage({ title: "경로를 찾지 못했어요", text: "출발지와 목적지를 다시 확인해 주세요." });
      return;
    }
    const updateGraph = setupResults(search, routes);
    watchDestinationFavorite(search);
    // 전체 검색당 그래프 요청은 한 번. 카드 전환은 받은 데이터만 사용한다.
    // 카드가 0개면 위에서 끝나므로 그래프를 요청하지 않는다. 카드의 id·departTime을 함께 보낸다.
    getRouteGraph({ ...search, arrive }, routes).then(updateGraph).catch(() => {
      updateGraph({ message: "소요시간 그래프를 불러오지 못했습니다. 실제 경로 카드와 지도는 계속 사용할 수 있습니다." });
    });
  } catch (error) {
    renderMessage({ title: "경로를 불러오지 못했어요", text: error.status >= 400 && error.status < 500 ? error.message : "실제 경로 조회에 실패했어요. 서버와 API 연결을 확인한 뒤 다시 시도해 주세요." });
  }
}

init();
