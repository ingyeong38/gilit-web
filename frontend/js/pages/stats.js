import { getStats } from "/js/api.js";
import { renderRankingChart, renderVisitorChart } from "/js/components/charts.js";
import { icon, renderIcons } from "/js/components/icon.js";

const formatCount = (value) => value.toLocaleString("ko-KR");

function setText(id, text) {
  document.getElementById(id).textContent = text;
}

function describeDayChange(today, yesterday) {
  if (!yesterday) return "어제 기록 없음";
  const change = ((today - yesterday) / yesterday) * 100;
  if (change === 0) return "어제와 같음";
  return `어제보다 ${Math.abs(change).toFixed(1)}% ${change > 0 ? "증가" : "감소"}`;
}

function render(stats) {
  const { dailyVisitors, popularOrigins, popularDestinations } = stats;
  const today = dailyVisitors.at(-1)?.count ?? 0;
  const yesterday = dailyVisitors.at(-2)?.count ?? 0;
  const weekTotal = dailyVisitors.reduce((sum, day) => sum + day.count, 0);
  const topDestination = popularDestinations[0];
  const searchesPerVisitor = stats.totalVisitors ? stats.totalSearches / stats.totalVisitors : 0;

  setText("stat-today", `${formatCount(today)}명`);
  setText("stat-today-note", describeDayChange(today, yesterday));
  setText("stat-total", `${formatCount(stats.totalVisitors)}명`);
  setText("stat-total-note", `이번 달 ${formatCount(stats.monthVisitors)}명`);
  setText("stat-searches", `${formatCount(stats.totalSearches)}회`);
  setText("stat-searches-note", `방문자당 평균 ${searchesPerVisitor.toFixed(1)}회`);
  setText("stat-popular", topDestination?.name ?? "-");
  setText("stat-popular-note", topDestination ? `이번 주 ${formatCount(topDestination.count)}회 검색` : "");
  setText("week-total", `${formatCount(weekTotal)}명`);
  setText("week-change", `${stats.weekChangePct > 0 ? "+" : ""}${stats.weekChangePct}%`);

  renderVisitorChart(document.getElementById("visitor-graph"), dailyVisitors);
  renderRankingChart(document.getElementById("ranking-origins"), {
    title: "인기 출발지 TOP 5",
    description: "검색 출발지 기준",
    rows: popularOrigins,
    tone: "blue",
  });
  renderRankingChart(document.getElementById("ranking-destinations"), {
    title: "인기 목적지 TOP 5",
    description: "검색 목적지 기준",
    rows: popularDestinations,
    tone: "navy",
  });
}

function renderError() {
  document.getElementById("stats-page").innerHTML = `
    <div class="empty-state">
      <span>${icon("chart", { size: 24 })}</span>
      <b>통계를 불러오지 못했어요</b>
      <p>잠시 후 다시 시도해 주세요.</p>
    </div>
  `;
}

async function init() {
  renderIcons();
  try {
    render(await getStats());
  } catch {
    renderError();
  }
}

init();
