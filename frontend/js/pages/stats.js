import { getStats } from "/js/api.js";
import { renderRankingChart, renderVisitorChart } from "/js/components/charts.js";
import { renderIcons } from "/js/components/icon.js";
import { requirePageAccess } from "/js/guard.js";

const LOADING = "불러오는 중";
const EMPTY = "데이터 없음";
const ERROR = "통계를 불러올 수 없음";
const PERIOD_LABELS = { 1: "오늘", 7: "최근 7일", 31: "최근 31일" };
let latestRequest = 0;
const formatCount = (value) => value.toLocaleString("ko-KR");
const displayCount = (value, unit, fallback) => value == null ? fallback : formatCount(value) + unit;

function setText(id, text) {
  document.getElementById(id).textContent = text;
}

function describeDayChange(change) {
  if (change == null) return "어제 대비 —";
  if (change === 0) return "어제와 같음";
  return `어제보다 ${Math.abs(change).toFixed(1)}% ${change > 0 ? "증가" : "감소"}`;
}

function render(stats = {}, fallback = EMPTY, days = 7) {
  stats ??= {};
  const visitorMessage = stats.visitorStatus === "unavailable" ? ERROR : fallback;
  const searchMessage = stats.searchStatus === "unavailable" ? ERROR : fallback;
  const dailyVisitors = stats.dailyVisitors ?? [];
  const popularOrigins = stats.popularOrigins ?? [];
  const popularDestinations = stats.popularDestinations ?? [];
  const topDestination = popularDestinations[0];
  const comparison = stats.periodChangePct;
  const period = PERIOD_LABELS[days];
  const ga4Range = stats.visitorPeriods?.dailyVisitors;
  const dates = stats.from && stats.to ? `${stats.from} ~ ${stats.to}` : period;
  const covered = ga4Range && ga4Range.startDate !== stats.from
    ? ` · GA4 조회 ${ga4Range.startDate} ~ ${ga4Range.endDate}` : "";
  setText("visitor-period", `${dates} (한국 시간)${covered}`);

  setText("stat-today", displayCount(stats.todayVisitors, "명", visitorMessage));
  setText("stat-today-note", stats.todayVisitors == null ? "" : describeDayChange(stats.dayChangePct));
  setText("stat-total", displayCount(stats.totalVisitors, "명", visitorMessage));
  setText("stat-total-note", `이번 달 ${displayCount(stats.monthVisitors, "명", visitorMessage)}`);
  setText("stat-searches", displayCount(stats.totalSearches || null, "회", searchMessage));
  setText("stat-searches-note", `방문자당 평균 ${fallback === LOADING ? LOADING : EMPTY}`);
  const popular = document.getElementById("stat-popular");
  popular.textContent = topDestination?.name ?? searchMessage;
  if (topDestination) popular.setAttribute("title", topDestination.name);
  else popular.removeAttribute("title");
  setText("stat-popular-note", topDestination ? `${period} ${formatCount(topDestination.count)}회 검색` : "");
  setText("period-total", displayCount(stats.periodVisitors, "명", visitorMessage));
  setText("period-change", comparison == null
    ? "—"
    : `직전 ${days}일 대비 ${comparison > 0 ? "+" : ""}${comparison}%`);

  const graph = document.getElementById("visitor-graph");
  if (dailyVisitors.some(day => day.count != null)) {
    renderVisitorChart(graph, dailyVisitors);
  } else {
    graph.innerHTML = `<p class="stats-status" role="status">${visitorMessage}</p>`;
  }
  renderRankingChart(document.getElementById("ranking-origins"), {
    title: "인기 출발지 TOP 5", description: "검색 출발지 기준",
    rows: popularOrigins, tone: "blue", message: searchMessage, period,
  });
  renderRankingChart(document.getElementById("ranking-destinations"), {
    title: "인기 목적지 TOP 5", description: "검색 목적지 기준",
    rows: popularDestinations, tone: "navy", message: searchMessage, period,
  });
}

async function loadPeriod(days) {
  const request = ++latestRequest;
  setText("stats-period-label", PERIOD_LABELS[days]);
  render({}, LOADING, days);
  try {
    const stats = await getStats(days);
    if (request === latestRequest) render(stats, EMPTY, days);
  } catch {
    if (request === latestRequest) render({}, ERROR, days);
  }
}

function init() {
  renderIcons();
  const select = document.getElementById("stats-period");
  select.addEventListener("change", () => loadPeriod(Number(select.value)));
  return loadPeriod(Number(select.value));
}

requirePageAccess().then(init);
