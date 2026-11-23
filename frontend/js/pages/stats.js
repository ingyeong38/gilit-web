import { getStats } from "/js/api.js";
import { renderRankingChart, renderVisitorChart } from "/js/components/charts.js";
import { renderIcons } from "/js/components/icon.js";
import { requirePageAccess } from "/js/guard.js";

const LOADING = "불러오는 중";
const EMPTY = "데이터 없음";
const ERROR = "통계를 불러올 수 없음";
const formatCount = (value) => value.toLocaleString("ko-KR");
const displayCount = (value, unit, fallback) => value == null ? fallback : formatCount(value) + unit;

function setText(id, text) {
  document.getElementById(id).textContent = text;
}

function describeDayChange(change) {
  if (change == null) return "어제 대비 계산 불가";
  if (change === 0) return "어제와 같음";
  return `어제보다 ${Math.abs(change).toFixed(1)}% ${change > 0 ? "증가" : "감소"}`;
}

function render(stats = {}, fallback = EMPTY) {
  stats ??= {};
  const visitorMessage = stats.visitorStatus === "unavailable" ? ERROR : fallback;
  const searchMessage = stats.searchStatus === "unavailable" ? ERROR : fallback;
  const dailyVisitors = stats.dailyVisitors ?? [];
  const popularOrigins = stats.popularOrigins ?? [];
  const popularDestinations = stats.popularDestinations ?? [];
  const topDestination = popularDestinations[0];
  const comparison = stats.weekChangePct;

  setText("stat-today", displayCount(stats.todayVisitors, "명", visitorMessage));
  setText("stat-today-note", stats.todayVisitors == null ? "" : describeDayChange(stats.dayChangePct));
  setText("stat-total", displayCount(stats.totalVisitors, "명", visitorMessage));
  setText("stat-total-note", `이번 달 ${displayCount(stats.monthVisitors, "명", visitorMessage)}`);
  setText("stat-searches", displayCount(stats.totalSearches, "회", searchMessage));
  setText("stat-searches-note", `방문자당 평균 ${fallback === LOADING ? LOADING : EMPTY}`);
  const popular = document.getElementById("stat-popular");
  popular.textContent = topDestination?.name ?? searchMessage;
  if (topDestination) popular.setAttribute("title", topDestination.name);
  else popular.removeAttribute("title");
  setText("stat-popular-note", topDestination ? `최근 7일 ${formatCount(topDestination.count)}회 검색` : "");
  setText("week-total", displayCount(stats.weekVisitors, "명", visitorMessage));
  setText("week-change", comparison == null
    ? (fallback === LOADING ? "" : "전주 대비 계산 불가")
    : `전주 대비 ${comparison > 0 ? "+" : ""}${comparison}%`);

  const graph = document.getElementById("visitor-graph");
  if (dailyVisitors.some(day => day.count != null)) {
    renderVisitorChart(graph, dailyVisitors);
  } else {
    graph.innerHTML = `<p class="stats-status" role="status">${visitorMessage}</p>`;
  }
  renderRankingChart(document.getElementById("ranking-origins"), {
    title: "인기 출발지 TOP 5", description: "검색 출발지 기준",
    rows: popularOrigins, tone: "blue", message: searchMessage,
  });
  renderRankingChart(document.getElementById("ranking-destinations"), {
    title: "인기 목적지 TOP 5", description: "검색 목적지 기준",
    rows: popularDestinations, tone: "navy", message: searchMessage,
  });
}

async function init() {
  renderIcons();
  render({}, LOADING);
  try {
    render(await getStats());
  } catch {
    render({}, ERROR);
  }
}

requirePageAccess().then(init);
