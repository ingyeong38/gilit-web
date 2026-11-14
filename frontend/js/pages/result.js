import { normalizeRouteGraphs } from "/js/components/durationGraph.js?v=card530-20261114-6";
import { USE_MOCK_ROUTES as USE_MOCK, GRAPH_API_ENABLED } from "/js/config.js";
import { addFavorite, getFavorites, getRouteGraph, getRoutes, searchPlaces } from "/js/api.js";
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
        <button class="star-button" type="button" aria-label="목적지를 즐겨찾기에 저장">${icon("star", { size: 19 })}</button>
      </div>
      <div class="route-name">${escapeHtml(route.name)}</div>
      <div class="departure-label">권장 출발${isPreviousDay ? " (전날)" : ""}</div>
      <div class="departure-time">${timeOf(route.departTime)}</div>
      <div class="route-details">
        ${[
          ["clock", "예상 소요시간", typeof route.durationMin === "number" ? `${route.durationMin}분` : "미제공"],
          ["route", "거리", typeof route.distanceKm === "number" ? `${route.distanceKm}km` : "미제공"],
          ["toll", "통행료", route.toll == null ? "미제공" : formatWon(route.toll)],
          ["fuel", "예상 유류비", route.fuel == null ? "미제공" : formatWon(route.fuel)],
        ].map(([name, title, value]) => `<div class="route-metric"><span class="route-metric-icon">${icon(name, { size: 25 })}</span><div><small>${title}</small><b>${escapeHtml(value)}</b></div></div>`).join("")}
      </div>
      <div class="arrival-info"><div class="arrival-main">${icon("flag", { size: 25 })}<span>도착 예정</span><b>${escapeHtml(timeOf(route.arriveTime))}</b></div>${renderBufferNote(route, buffer)}</div>
    </article>
  `;
}

// 즐겨찾기는 장소 단위이므로 별을 누르면 이번 검색의 목적지를 저장한다.
async function saveDestination(name) {
  const favorites = await getFavorites();
  if (!favorites.some((place) => place.name === name)) {
    const places = await searchPlaces(name);
    const address = places.find((place) => place.name === name)?.address ?? name;
    await addFavorite({ name, address, type: "기타" });
  }
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
  const list = document.getElementById("route-list");
  list.innerHTML = routes.map((route, index) => renderRouteCard(route, index, search)).join("");
  const cards = list.querySelectorAll(".route-card");
  const drawGraph = () => {
    const route = routes[selectedIndex];
    const normalized = graphs.get(route.id);
    const durations = [...graphs.values()].flatMap(value => value.points.map(point => point.durationMin));
    const range = durations.length ? { min: Math.min(...durations), max: Math.max(...durations) } : undefined;
    const chart = document.getElementById("duration-chart");
    chart.setAttribute("aria-busy", String(graphMessage.includes("불러오는 중")));
    renderDurationChart(chart, { points: normalized?.points ?? [], discarded: normalized?.discarded ?? 0,
      color: ROUTE_COLORS[selectedIndex % ROUTE_COLORS.length], recommendedTime: route.departTime,
      range, routeName: `${formatRouteLabel(route)} · ${route.name}`, routeId: route.id, isExample: USE_MOCK,
      routeTag: formatRouteLabel(route), message: graphMessage || "선택 경로와 일치하는 유효한 그래프 데이터가 없습니다." });
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
    const star = card.querySelector(".star-button");
    star.addEventListener("click", async (event) => {
      event.stopPropagation();
      try {
        await saveDestination(search.to);
        star.classList.add("active");
        showToast("즐겨찾기에 저장했어요");
      } catch {
        showToast("즐겨찾기에 저장하지 못했어요", { error: true });
      }
    });
  });

  select(0);
  return (data, message = "") => {
    graphs = normalizeRouteGraphs(data, routes);
    graphMessage = message;
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
    // 전체 검색당 그래프 요청은 한 번. 카드 전환은 받은 데이터만 사용한다.
    getRouteGraph({ from: search.from, to: search.to, arrive }).then(graph => {
      updateGraph(graph, !USE_MOCK && !GRAPH_API_ENABLED ? "그래프 API 연동 대기 중입니다. 경로 카드와 지도는 계속 사용할 수 있습니다." : "");
    }).catch(() => {
      updateGraph([], "소요시간 그래프를 불러오지 못했습니다. 경로 카드와 지도는 계속 사용할 수 있습니다.");
    });
  } catch (error) {
    renderMessage({ title: "경로를 불러오지 못했어요", text: error.status >= 400 && error.status < 500 ? error.message : "실제 경로 조회에 실패했어요. 서버와 API 연결을 확인한 뒤 다시 시도해 주세요." });
  }
}

init();
