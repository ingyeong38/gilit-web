import { escapeHtml, formatShortDate, minutesBetween, timeOf } from "/js/utils.js";

// SVG 좌표 기준값은 디자인 원본과 같다.
const DURATION = {
  gridLines: [35, 75, 115, 155, 195],
  left: 34,
  width: 630,
  bottomY: 176,
  topY: 35,
  maxScale: 4.1,
  viewWidth: 700,
  viewHeight: 230,
  svgHeight: 190,
  yLabelWidth: 38,
  initialHover: 3,
};

const VISITORS = {
  gridLines: [25, 65, 105, 145, 185],
  left: 35,
  right: 625,
  lastX: 623,
  topY: 25,
  bottomY: 185,
  axisStep: 100,
  axisTicks: 4,
};

// range: 모든 경로에 공통으로 적용할 { min, max }. 경로를 바꿔도 세로 눈금이 유지된다.
export function renderDurationChart(container, { points, color, recommendedTime, range }) {
  const base = range.min - 3;
  const scale = Math.min(DURATION.maxScale, (DURATION.bottomY - DURATION.topY) / Math.max(range.max - base, 1));
  const xAt = (index) => DURATION.left + (index * DURATION.width) / Math.max(points.length - 1, 1);
  const yAt = (value) => DURATION.bottomY - (value - base) * scale;
  const firstTime = points[0].departTime;
  const totalMinutes = minutesBetween(firstTime, points.at(-1).departTime);
  const recommendedOffset = minutesBetween(firstTime, recommendedTime);
  const showRecommended = recommendedOffset >= 0 && recommendedOffset <= totalMinutes;
  const recommendedX = DURATION.left + (recommendedOffset / (totalMinutes || 1)) * DURATION.width;
  const linePoints = points.map((point, index) => `${xAt(index)},${yAt(point.durationMin)}`).join(" ");

  container.innerHTML = `
    <div class="chart-head">
      <div><div class="list-title">출발시각별 예상 소요시간</div><p>출발 시간에 따른 교통 흐름 변화를 확인하세요.</p></div>
      <div class="chart-legend"><i style="background: ${color}"></i>예상 소요시간 <span></span>권장 출발</div>
    </div>
    <div class="chart-wrap">
      <div class="y-label">소요시간 (분)</div>
      <svg viewBox="0 0 ${DURATION.viewWidth} ${DURATION.viewHeight}" preserveAspectRatio="none">
        ${DURATION.gridLines.map((y) => `<line x1="34" y1="${y}" x2="664" y2="${y}" class="grid-line" />`).join("")}
        ${showRecommended ? `<line x1="${recommendedX}" y1="24" x2="${recommendedX}" y2="195" class="recommend-line" />` : ""}
        <polyline points="${linePoints}" class="duration-area-line" style="stroke: ${color}" />
        ${points.map((point, index) => `<circle cx="${xAt(index)}" cy="${yAt(point.durationMin)}" r="4" class="chart-point" style="stroke: ${color}" data-index="${index}" />`).join("")}
      </svg>
      <div class="chart-tooltip" hidden></div>
      <div class="x-labels">${points.map((point) => `<span>${timeOf(point.departTime)}</span>`).join("")}</div>
    </div>
  `;

  const tooltip = container.querySelector(".chart-tooltip");
  const circles = container.querySelectorAll(".chart-point");

  const setHover = (index) => {
    circles.forEach((circle, circleIndex) => circle.setAttribute("r", circleIndex === index ? "6" : "4"));
    tooltip.hidden = index === null;
    if (index === null) return;
    const point = points[index];
    tooltip.innerHTML = `<b>${timeOf(point.departTime)} 출발</b><span>예상 ${point.durationMin}분</span>`;
    tooltip.style.left = `calc(${DURATION.yLabelWidth}px + (100% - ${DURATION.yLabelWidth}px) * ${xAt(index) / DURATION.viewWidth})`;
    tooltip.style.top = `${(yAt(point.durationMin) / DURATION.viewHeight) * DURATION.svgHeight - 8}px`;
  };

  circles.forEach((circle, index) => {
    circle.addEventListener("mouseenter", () => setHover(index));
    circle.addEventListener("mouseleave", () => setHover(null));
  });
  setHover(points.length > DURATION.initialHover ? DURATION.initialHover : null);
}

export function renderVisitorChart(container, dailyVisitors) {
  const max = Math.max(...dailyVisitors.map((day) => day.count), 1);
  const axisMax = Math.ceil(max / VISITORS.axisStep) * VISITORS.axisStep;
  const ticks = Array.from({ length: VISITORS.axisTicks + 1 }, (_, index) => axisMax - (axisMax / VISITORS.axisTicks) * index);
  const xAt = (index) => VISITORS.left + (index * (VISITORS.lastX - VISITORS.left)) / Math.max(dailyVisitors.length - 1, 1);
  const yAt = (value) => VISITORS.bottomY - (value / axisMax) * (VISITORS.bottomY - VISITORS.topY);
  const linePoints = dailyVisitors.map((day, index) => `${xAt(index)},${yAt(day.count)}`).join(" ");

  container.innerHTML = `
    <div class="visitor-axis">${ticks.map((tick) => `<span>${tick}</span>`).join("")}</div>
    <svg viewBox="0 0 660 210" preserveAspectRatio="none">
      ${VISITORS.gridLines.map((y) => `<line x1="${VISITORS.left}" y1="${y}" x2="${VISITORS.right}" y2="${y}" class="grid-line" />`).join("")}
      <defs><linearGradient id="visitorFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#2563EB" stop-opacity=".2" /><stop offset="100%" stop-color="#2563EB" stop-opacity="0" /></linearGradient></defs>
      <polygon points="${VISITORS.left},${VISITORS.bottomY} ${linePoints} ${VISITORS.lastX},${VISITORS.bottomY}" class="visitor-area" />
      <polyline points="${linePoints}" class="visitor-line" />
      ${dailyVisitors.map((day, index) => `<circle cx="${xAt(index)}" cy="${yAt(day.count)}" r="4" class="visitor-point"><title>${day.count}명</title></circle>`).join("")}
    </svg>
    <div class="visitor-labels">${dailyVisitors.map((day) => `<span>${formatShortDate(day.date)}</span>`).join("")}</div>
  `;
}

export function renderRankingChart(container, { title, description, rows, tone }) {
  const max = Math.max(...rows.map((row) => row.count), 1);
  container.innerHTML = `
    <div class="dashboard-head"><div><div class="list-title">${title}</div><p>${description}</p></div><span>이번 주</span></div>
    <div class="horizontal-bars">
      ${rows.map((row, index) => `
        <div class="horizontal-row">
          <span class="rank-number">${index + 1}</span>
          <div><div class="bar-label"><b>${escapeHtml(row.name)}</b><small>${row.count.toLocaleString("ko-KR")}회</small></div><div class="bar-track"><span class="${tone}" style="width: ${(row.count / max) * 100}%"></span></div></div>
        </div>
      `).join("")}
    </div>
  `;
}
