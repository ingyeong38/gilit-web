import { icon } from "/js/components/icon.js";
import { durationChartModel, graphTime, durationChange, summaryPosition } from "/js/components/durationGraph.js?v=card530-20261114-6";
import { escapeHtml, formatShortDate } from "/js/utils.js";

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

const durationChartCleanups = new WeakMap();

// 기존 SVG 차트를 재사용한다. 나머지 통계 차트와 계산을 분리한다.
export function renderDurationChart(container, { points = [], color = "#2563EB", recommendedTime, range, routeName = "", isExample = false, message = "", discarded = 0, routeId = "", routeTag = "" } = {}) {
  durationChartCleanups.get(container)?.();
  const model = durationChartModel(points, recommendedTime, range);
  const stroke = /^#[0-9a-f]{6}$/i.test(color) ? color : "#2563EB";
  const label = value => escapeHtml(value);
  container.hidden = false;
  container.dataset.routeId = routeId;
  const heading = `<div class="chart-head"><div><h2 class="list-title">출발시각별 예상 소요시간</h2><p>${label(routeName)} · ${isExample ? "테스트용 예시 데이터 · 실제 교통 예측이 아닙니다." : "예상 소요시간 · 한국 시간(KST)"}</p></div></div>`;
  if (!model.points.length) {
    container.innerHTML = `${heading}<p class="duration-empty" role="status">${label(message || "선택 경로의 그래프 데이터가 없습니다.")}</p>`;
    return;
  }
  const recommendedLabel = graphTime(recommendedTime);
  container.innerHTML = `${heading}
    <p class="duration-summary">권장 출발: <b>${label(recommendedLabel)}</b>${model.recommendedX === null ? " (그래프 범위 밖 또는 시각 미제공)" : " · 점선 표시"}</p>
    <div class="duration-plot"><div class="duration-scroll">
      <svg class="duration-svg" viewBox="0 0 700 270" role="group" aria-label="${label(routeName)} 출발시각별 예상 소요시간. 데이터 지점에서 방향키로 이동하세요.">
        <text x="12" y="22" class="duration-axis-title">예상 소요시간 (분)</text>
        ${model.yTicks.map(tick => `<line x1="64" x2="656" y1="${tick.y}" y2="${tick.y}" class="grid-line"/><text x="52" y="${tick.y + 4}" text-anchor="end">${Number(tick.value.toFixed(1))}</text>`).join("")}
        ${model.xTicks.map(tick => `<text x="${tick.x}" y="224" text-anchor="middle">${graphTime(tick.timestamp)}</text>`).join("")}
        <text x="360" y="255" text-anchor="middle" class="duration-axis-title">출발 시각 (KST · 월/일 시:분)</text>
        ${model.recommendedX === null ? "" : `<line x1="${model.recommendedX}" x2="${model.recommendedX}" y1="35" y2="200" class="recommend-line"/><text x="${Math.min(620, Math.max(100, model.recommendedX))}" y="33" text-anchor="middle">권장 출발</text>`}
        <polyline points="${model.points.map(p => `${p.x},${p.y}`).join(" ")}" class="duration-area-line" style="stroke:${stroke}"/>
        ${model.points.map((p, i) => `<g><circle cx="${p.x}" cy="${p.y}" r="4" fill="white" stroke="${stroke}" stroke-width="3"/><circle class="duration-hit" cx="${p.x}" cy="${p.y}" r="14" tabindex="${i === 0 ? 0 : -1}" role="button" aria-pressed="false" data-index="${i}" aria-label="${graphTime(p.timestamp)} 출발, 예상 ${p.durationMin}분"><title>${graphTime(p.timestamp)} 출발 · 예상 ${p.durationMin}분</title></circle></g>`).join("")}
      </svg>
    </div><aside class="duration-popover" aria-label="선택한 출발 시각 요약" hidden></aside></div>
    <p class="duration-readout" role="status" aria-live="polite">지점에 마우스를 올리거나 터치하세요. 키보드는 Tab으로 진입한 뒤 ← → 키로 이동하세요.</p>
    ${model.points.length === 1 ? '<p class="duration-note">데이터가 1개여서 선 대신 지점으로 표시합니다.</p>' : ""}
    ${discarded + model.discarded ? '<p class="duration-note">잘못되거나 중복된 데이터는 제외했습니다. 중복 시각은 마지막 유효 값을 사용합니다.</p>' : ""}
    <details class="duration-table"><summary><span class="duration-disclosure">${icon("chevron")}</span>출발 시각별 데이터 표 보기</summary>
      <div class="duration-table-body"><div class="duration-table-route">${routeTag ? `<span class="route-tag">${label(routeTag)}</span>` : ""}${icon("car")}<span>${label(routeName)} 예상 소요시간 (KST)</span></div>
      <div class="duration-row-heading"><span>${icon("clock")} 출발 시각</span><span>예상 소요시간</span></div>
      <div class="duration-rows" role="group" aria-label="출발 시각별 데이터">
      ${model.points.map((p, i) => `<button class="duration-row" type="button" data-point-index="${i}" aria-pressed="false"><span class="duration-row-time">${icon("clock")}<span>${graphTime(p.timestamp)}</span></span><span class="duration-value">${p.durationMin}분</span><span class="duration-selected" hidden>✓ 선택됨</span></button>`).join("")}</div></div></details>`;
  const nodes = [...container.querySelectorAll(".duration-hit")];
  const rows = [...container.querySelectorAll(".duration-row")];
  const badges = [...container.querySelectorAll(".duration-selected")];
  const readout = container.querySelector(".duration-readout");
  const popover = container.querySelector(".duration-popover");
  const plot = container.querySelector(".duration-plot");
  const scroll = container.querySelector(".duration-scroll");
  let selected = null;
  const describe = index => {
    const p = model.points[index];
    readout.textContent = `${graphTime(p.timestamp)} 출발 · 예상 ${p.durationMin}분${isExample ? " · 테스트용 예시" : ""}`;
  };
  const position = () => {
    if (selected === null) return;
    if (window.matchMedia("(max-width: 640px)").matches) {
      popover.style.left = ""; popover.style.top = ""; popover.style.maxHeight = "";
      return;
    }
    const bounds = plot.getBoundingClientRect();
    const point = nodes[selected].getBoundingClientRect();
    popover.style.maxHeight = `${Math.max(120, bounds.height - 16)}px`;
    const card = popover.getBoundingClientRect();
    const placement = summaryPosition({ width: bounds.width, height: bounds.height, cardWidth: card.width, cardHeight: card.height,
      x: (point.left + point.right) / 2 - bounds.left, y: (point.top + point.bottom) / 2 - bounds.top });
    popover.style.left = `${placement.left}px`; popover.style.top = `${placement.top}px`;
    popover.dataset.side = placement.side;
    popover.style.setProperty("--tail-top", `${placement.tailTop}px`);
  };
  const select = index => {
    selected = index;
    nodes.forEach((node, i) => { node.classList.toggle("active", i === index); node.setAttribute("aria-pressed", String(i === index)); });
    rows.forEach((row, i) => { row.classList.toggle("selected", i === index); row.setAttribute("aria-pressed", String(i === index)); badges[i].hidden = i !== index; });
    popover.hidden = index === null;
    if (index === null) return;
    describe(index);
    const point = model.points[index], change = durationChange(model.points, index);
    popover.innerHTML = `<div class="duration-popover-content"><div class="duration-popover-head"><span class="duration-popover-clock">${icon("clock")}</span><b>${graphTime(point.timestamp)} 출발</b><button class="duration-popover-close" type="button" aria-label="요약 카드 닫기">${icon("close", { size: 16 })}</button></div><div class="duration-popover-value"><div><small>예상 소요시간</small><strong>${point.durationMin}분</strong></div><div class="duration-mode">${icon("car")}<span>자동차 기준</span></div></div><p class="duration-change ${change.tone}"><span class="duration-change-mark" aria-hidden="true">${change.tone === "decrease" ? "▼" : change.tone === "increase" ? "▲" : "−"}</span><span>${label(change.text)}</span></p>${isExample ? '<p class="duration-example-note">테스트용 예시 · 실제 교통 예측이 아닙니다.</p>' : ""}</div>`;
    popover.querySelector(".duration-popover-close").addEventListener("click", () => select(null));
    position();
  };
  nodes.forEach((node, index) => {
    for (const event of ["mouseenter", "focus"]) node.addEventListener(event, () => describe(index));
    node.addEventListener("click", () => select(selected === index ? null : index));
    node.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(selected === index ? null : index); return; }
      if (event.key === "Escape") { select(null); return; }
      let next = index;
      if (["ArrowRight", "ArrowDown"].includes(event.key)) next = Math.min(index + 1, nodes.length - 1);
      else if (["ArrowLeft", "ArrowUp"].includes(event.key)) next = Math.max(index - 1, 0);
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = nodes.length - 1;
      else return;
      event.preventDefault();
      nodes.forEach((target, i) => target.setAttribute("tabindex", i === next ? "0" : "-1"));
      nodes[next].focus();
      if (selected !== null) select(next);
    });
  });
  rows.forEach((row, index) => row.addEventListener("click", () => {
    nodes[index].scrollIntoView({ block: "nearest", inline: "nearest" });
    select(index);
  }));
  const outside = event => {
    if (!plot.contains(event.target) && !container.querySelector(".duration-table").contains(event.target)) select(null);
  };
  const escape = event => { if (event.key === "Escape") select(null); };
  container.addEventListener("keydown", escape);
  document.addEventListener("click", outside);
  window.addEventListener("resize", position);
  scroll.addEventListener("scroll", position);
  durationChartCleanups.set(container, () => {
    container.removeEventListener("keydown", escape);
    document.removeEventListener("click", outside);
    window.removeEventListener("resize", position);
  });
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
