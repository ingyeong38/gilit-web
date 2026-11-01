import { addFavorite, getFavorites, getRouteGraph, getRoutes, searchPlaces } from "/js/api.js";
import { renderDurationChart } from "/js/components/charts.js";
import { icon, renderIcons } from "/js/components/icon.js";
import { renderRouteMap } from "/js/components/map.js";
import { showToast } from "/js/components/toast.js";
import {
  ROUTE_COLORS,
  dateOf,
  escapeHtml,
  formatBuffer,
  formatFullDate,
  formatWon,
  isValidDate,
  isValidTime,
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
  if (!from || !to || !isValidDate(date) || !isValidTime(time)) return null;
  if (!Number.isInteger(buffer) || buffer < 0) return null;
  return { from, to, date, time, buffer };
}

function renderMessage({ title, text }) {
  page.innerHTML = `
    <div class="results-shell">
      <div class="empty-state">
        <span>${icon("search", { size: 24 })}</span>
        <b>${title}</b>
        <p>${text}</p>
        <a class="btn btn-primary" href="/pages/search.html">길찾기로 이동</a>
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

function renderRouteCard(route, index, { date, buffer }) {
  const isPreviousDay = dateOf(route.departTime) !== date;
  return `
    <article class="route-card" role="button" tabindex="0" aria-pressed="false" data-index="${index}">
      <div class="route-card-head">
        <span class="route-tag tag-${index}">${index === 0 ? icon("spark", { size: 13 }) : ""}${escapeHtml(route.label)}</span>
        <button class="star-button" type="button" aria-label="목적지를 즐겨찾기에 저장">${icon("star", { size: 19 })}</button>
      </div>
      <div class="route-name">${escapeHtml(route.name)}</div>
      <div class="departure-label">권장 출발${isPreviousDay ? " (전날)" : ""}</div>
      <div class="departure-time">${timeOf(route.departTime)}</div>
      <div class="route-details">
        <span><small>예상 소요</small><b>${route.durationMin}분</b></span>
        <span><small>거리</small><b>${route.distanceKm}km</b></span>
        <span><small>통행료</small><b>${formatWon(route.toll)}</b></span>
        <span><small>예상 유류비</small><b>${formatWon(route.fuel)}</b></span>
      </div>
      <div class="arrival-info"><span>${icon("check", { size: 14 })} ${timeOf(route.arriveTime)} 도착 예정</span><span>여유 ${formatBuffer(buffer)}</span></div>
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

function setupResults(search, routes, graph) {
  const list = document.getElementById("route-list");
  list.innerHTML = routes.map((route, index) => renderRouteCard(route, index, search)).join("");
  const cards = list.querySelectorAll(".route-card");
  const durations = graph.flatMap(({ points }) => points.map((point) => point.durationMin));
  const range = { min: Math.min(...durations), max: Math.max(...durations) };

  const select = (index) => {
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
      from: search.from,
      to: search.to,
    });
    const points = graph.find(({ routeId }) => routeId === route.id)?.points ?? [];
    const chart = document.getElementById("duration-chart");
    chart.hidden = points.length === 0;
    if (points.length > 0) {
      renderDurationChart(chart, { points, color, recommendedTime: route.departTime, range });
    }
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
}

async function init() {
  const search = readSearchQuery();
  if (!search) {
    renderMessage({ title: "검색 조건이 없어요", text: "출발지, 목적지, 도착 희망 시각을 입력해 주세요." });
    return;
  }

  renderIcons();
  renderSummary(search);
  setupShareButton();

  try {
    const arrive = toIsoTime(search.date, search.time);
    const [routes, graph] = await Promise.all([
      getRoutes({ from: search.from, to: search.to, arrive, buffer: search.buffer }),
      getRouteGraph({ from: search.from, to: search.to, arrive }),
    ]);
    if (routes.length === 0) {
      renderMessage({ title: "경로를 찾지 못했어요", text: "출발지와 목적지를 다시 확인해 주세요." });
      return;
    }
    setupResults(search, routes, graph);
  } catch {
    renderMessage({ title: "경로를 불러오지 못했어요", text: "잠시 후 다시 시도해 주세요." });
  }
}

init();
