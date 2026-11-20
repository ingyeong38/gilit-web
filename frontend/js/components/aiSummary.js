// AI 경로 요약 카드 (결과 화면 #ai-summary). 서버 응답(POST /api/routes/summary)이나 로컬 대체 요약을 그린다.
// 결론 카드(권장 출발시각 → headline → 키워드) + 여유시간 확보율 SVG 게이지 + 경로별 소요시간 비교표(막대).
// 숫자는 서버(또는 카드 값)가 계산한 값만 쓴다. 서버 값은 모두 escapeHtml을 거쳐 넣는다 (headline·keywords는 AI 문자열이다).
import { icon } from "/js/components/icon.js";
import { ROUTE_COLORS, escapeHtml, formatRouteLabel, timeOf } from "/js/utils.js";

export const RULE_NOTICE = "AI 요약을 불러오지 못해 기본 비교를 표시합니다";
export const LOADING_TEXT = "AI 경로 요약을 준비하고 있습니다.";
export const EMPTY_TEXT = "경로 요약을 표시할 수 없습니다.";
export const KEYWORD_LIMIT = 2;
export const KEYWORD_MAX_LENGTH = 12;
export const HEADLINE_MAX_LENGTH = 40;
const MIN_BAR_PERCENT = 4; // 0이 아닌 막대가 보이도록 하는 최소 폭 (트랙 대비 %)
const ISO_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

const isCount = (value) => typeof value === "number" && Number.isFinite(value);
const isIso = (value) => typeof value === "string" && ISO_PATTERN.test(value) && Number.isFinite(Date.parse(value));

// --- 순수 함수 ---

// 여유시간 게이지: 요청 여유(bufferMin) 대비 확보율. slackMin >= bufferMin이면 100%, 음수(늦게 도착)는 0% + late.
// 요청 여유가 0분이면 제시간에 도착하는 것만으로 100%다.
export function gaugeModel(slackMin, bufferMin = 0) {
  const slack = isCount(slackMin) ? Math.trunc(slackMin) : 0;
  const buffer = isCount(bufferMin) && bufferMin > 0 ? Math.trunc(bufferMin) : 0;
  const late = slack < 0;
  const ratio = late ? 0 : buffer > 0 ? Math.min(1, slack / buffer) : 1;
  const tone = late ? "late" : ratio < 1 ? "short" : "ok";
  let detail;
  if (late) detail = `${-slack}분 늦게 도착`;
  else if (buffer === 0) detail = "도착 희망 시각 전 도착";
  else if (slack >= buffer) detail = `요청 ${buffer}분 확보`;
  else detail = `요청 ${buffer}분보다 ${buffer - slack}분 부족`;
  return {
    slack,
    buffer,
    late,
    tone,
    ratio,
    percent: Math.round(ratio * 100),
    label: late ? "여유 없음" : `여유 ${slack}분`,
    detail,
    startLabel: "0",
    endLabel: buffer > 0 ? `요청 ${buffer}분` : "제시간",
  };
}

export function tollText(toll) {
  if (!isCount(toll)) return "미제공";
  return toll === 0 ? "무료" : `${toll.toLocaleString("ko-KR")}원`;
}

export function diffText(diffMin) {
  return diffMin === 0 ? "최단" : `최단 대비 +${diffMin}분`;
}

// 경로별 비교표의 행. 막대 길이는 소요시간/최대 소요시간(트랙 대비 %), 차이는 가장 짧은 소요시간 대비(분).
// 순서는 비교 목록(=카드) 순서 그대로.
export function barModel(comparison = [], { selectedId = null, recommendedId = null } = {}) {
  const rows = (Array.isArray(comparison) ? comparison : [])
    .filter((row) => typeof row?.routeId === "string" && isCount(row.durationMin) && row.durationMin >= 0);
  const max = Math.max(1, ...rows.map((row) => row.durationMin));
  const min = rows.length ? Math.min(...rows.map((row) => row.durationMin)) : 0;
  return rows.map((row, index) => {
    const diff = Math.round(row.durationMin - min);
    return {
      routeId: row.routeId,
      label: typeof row.label === "string" && row.label ? row.label : row.routeId,
      durationMin: row.durationMin,
      width: row.durationMin > 0 ? Math.max(MIN_BAR_PERCENT, Math.round((row.durationMin / max) * 1000) / 10) : 0,
      diffMin: diff,
      diffText: diffText(diff),
      tollText: tollText(row.toll),
      color: ROUTE_COLORS[index % ROUTE_COLORS.length],
      selected: row.routeId === selectedId,
      recommended: row.routeId === recommendedId,
      fastest: diff === 0,
    };
  });
}

// headline과 겹치는 칩인지. 칩의 두 글자 이상 단어가 headline 안에 있으면 겹친다고 본다 (조사가 붙어도 잡힌다).
function overlapsHeadline(keyword, headline) {
  if (!headline) return false;
  const text = headline.replace(/\s+/g, "");
  return keyword.split(/\s+/).some((word) => word.length >= 2 && text.includes(word));
}

// 키워드 칩: 문자열만, 앞뒤 공백 제거, 빈 값·12자 초과·중복·headline과 겹치는 칩 제외, 2개까지.
export function cleanKeywords(keywords, { headline = "", limit = KEYWORD_LIMIT } = {}) {
  const seen = new Set();
  for (const value of Array.isArray(keywords) ? keywords : []) {
    if (seen.size >= limit) break;
    if (typeof value !== "string") continue;
    const text = value.trim();
    if (!text || text.length > KEYWORD_MAX_LENGTH || seen.has(text) || overlapsHeadline(text, headline)) continue;
    seen.add(text);
  }
  return [...seen];
}

// 막대·결론 라벨: 같은 검색의 경로 카드가 있으면 카드와 같은 formatRouteLabel("추천 · 최단시간" 등), 없으면 서버 label.
function routeLabeler(routes) {
  const cards = new Map((Array.isArray(routes) ? routes : []).filter((route) => typeof route?.id === "string").map((route) => [route.id, route]));
  return (id, fallback) => {
    const card = cards.get(id);
    const label = card ? formatRouteLabel(card) : null;
    if (typeof label === "string" && label) return label;
    return typeof fallback === "string" && fallback ? fallback : id;
  };
}

// 서버 응답을 화면 모델로. 형식이 어긋나면(같은 검색의 카드 id가 아님 등) 던진다 → 화면은 로컬 대체 요약을 쓴다.
export function normalizeSummary(data, routes = []) {
  const ids = new Set((Array.isArray(routes) ? routes : []).map((route) => route?.id).filter((id) => typeof id === "string"));
  if (!data || typeof data !== "object") throw new Error("요약 응답 형식 오류");
  if (data.source !== "gemini" && data.source !== "rule") throw new Error("요약 출처 오류");
  if (typeof data.recommendedRouteId !== "string" || !ids.has(data.recommendedRouteId)) throw new Error("추천 경로 오류");
  if (!isIso(data.recommendedDepartTime) || !isCount(data.slackMin)) throw new Error("요약 수치 오류");
  const comparison = Array.isArray(data.comparison) ? data.comparison.filter((row) => ids.has(row?.routeId)
    && isCount(row.durationMin) && row.durationMin >= 0 && isCount(row.slackMin)) : [];
  if (!comparison.length) throw new Error("비교 수치 오류");
  const labelOf = routeLabeler(routes);
  const headline = (typeof data.headline === "string" ? data.headline.trim().slice(0, HEADLINE_MAX_LENGTH) : "")
    || "추천 경로를 기준으로 안내해요";
  const recommended = comparison.find((row) => row.routeId === data.recommendedRouteId);
  return {
    source: data.source,
    local: false,
    recommendedRouteId: data.recommendedRouteId,
    recommendedLabel: labelOf(data.recommendedRouteId, recommended?.label),
    recommendedDepartTime: data.recommendedDepartTime,
    headline,
    keywords: data.source === "gemini" ? cleanKeywords(data.keywords, { headline }) : [],
    slackMin: Math.trunc(data.slackMin),
    bufferMin: isCount(data.bufferMin) ? Math.trunc(data.bufferMin) : 0,
    comparison: comparison.map((row) => ({
      routeId: row.routeId,
      label: labelOf(row.routeId, row.label),
      durationMin: row.durationMin,
      slackMin: Math.trunc(row.slackMin),
      toll: isCount(row.toll) ? row.toll : null,
      departTime: isIso(row.departTime) ? row.departTime : null,
    })),
  };
}

// 서버 호출 자체가 실패했을 때(네트워크, 시간 초과, 400, 5xx) 카드 값으로 만드는 대체 요약. 서버 rule과 같은 규칙이다:
// 추천 = id가 recommend인 카드, 없으면 출발시각이 가장 늦은 카드(같으면 앞). 여유 = 도착 희망 시각 - 예상 도착(분, 내림).
export function localSummary({ arrive, buffer } = {}, routes = []) {
  const arriveAt = Date.parse(arrive);
  if (!Number.isFinite(arriveAt)) return null;
  const cards = (Array.isArray(routes) ? routes : []).filter((route) => typeof route?.id === "string"
    && isIso(route.departTime) && isIso(route.arriveTime) && isCount(route.durationMin)).slice(0, 4);
  if (!cards.length) return null;
  const slackOf = (route) => Math.floor((arriveAt - Date.parse(route.arriveTime)) / 60000);
  const chosen = cards.find((route) => route.id === "recommend")
    ?? cards.reduce((latest, route) => (Date.parse(route.departTime) > Date.parse(latest.departTime) ? route : latest));
  const labelOf = routeLabeler(cards);
  return {
    source: "rule",
    local: true,
    recommendedRouteId: chosen.id,
    recommendedLabel: labelOf(chosen.id, chosen.label),
    recommendedDepartTime: chosen.departTime,
    headline: `${labelOf(chosen.id, chosen.label)} 경로를 기준으로 안내해요`,
    keywords: [],
    slackMin: slackOf(chosen),
    bufferMin: Number(buffer) || 0,
    comparison: cards.map((route) => ({
      routeId: route.id,
      label: labelOf(route.id, route.label),
      durationMin: route.durationMin,
      slackMin: slackOf(route),
      toll: isCount(route.toll) ? route.toll : null,
      departTime: route.departTime,
    })),
  };
}

// 결론 카드 라벨: "추천 경로". 추천 카드 이름이 "추천"으로 시작하지 않으면(예: 무료도로) 이름을 덧붙인다.
export function conclusionLabel(recommendedLabel) {
  return typeof recommendedLabel === "string" && recommendedLabel && !recommendedLabel.startsWith("추천")
    ? `추천 경로 · ${recommendedLabel}` : "추천 경로";
}

// --- 렌더 ---

export function renderAiSummaryLoading(container) {
  container.setAttribute("aria-busy", "true");
  container.innerHTML = `<p class="ai-status" role="status">${escapeHtml(LOADING_TEXT)}</p>`;
}

function renderGauge(gauge) {
  const arc = "M14 62 A46 46 0 0 1 106 62";
  return `
    <figure class="ai-gauge tone-${gauge.tone}" role="img" aria-label="${escapeHtml(`${gauge.label}. ${gauge.detail}. 확보율 ${gauge.percent}%`)}">
      <div class="ai-gauge-dial">
        <svg viewBox="0 0 120 80" aria-hidden="true" focusable="false">
          <path class="gauge-track" d="${arc}" pathLength="100" />
          ${gauge.percent > 0 ? `<path class="gauge-value" d="${arc}" pathLength="100" stroke-dasharray="${gauge.percent} 100" />` : ""}
          <text class="gauge-tick" x="14" y="77" text-anchor="middle">${escapeHtml(gauge.startLabel)}</text>
          <text class="gauge-tick" x="119" y="77" text-anchor="end">${escapeHtml(gauge.endLabel)}</text>
        </svg>
        <b class="ai-gauge-value">${escapeHtml(gauge.label)}</b>
      </div>
      <figcaption>${escapeHtml(gauge.detail)}</figcaption>
    </figure>`;
}

function renderRows(rows) {
  const header = `
    <div class="ai-row ai-row-head" role="row">
      <span role="columnheader">경로</span><span role="columnheader" class="ai-col-time">소요시간</span>
      <span role="columnheader">최단 대비</span><span role="columnheader">통행료</span>
    </div>`;
  return header + rows.map((row) => `
    <div class="horizontal-row ai-row${row.selected ? " is-selected" : ""}" role="row" data-route-id="${escapeHtml(row.routeId)}" aria-current="${row.selected ? "true" : "false"}">
      <span class="ai-row-name" role="cell"><span class="route-dot" style="background: ${row.color}"></span><b>${escapeHtml(row.label)}</b>${row.recommended ? '<em class="bar-badge">추천</em>' : ""}</span>
      <span class="bar-track" role="presentation"><span style="width: ${row.width}%; background: ${row.color}"></span></span>
      <b class="ai-row-duration" role="cell">${escapeHtml(`${row.durationMin}분`)}</b>
      <span class="ai-row-diff${row.fastest ? " is-fastest" : ""}" role="cell">${escapeHtml(row.diffText)}</span>
      <span class="ai-row-toll" role="cell">${escapeHtml(row.tollText)}</span>
    </div>`).join("");
}

export function renderAiSummary(container, summary, { selectedId = null } = {}) {
  container.setAttribute("aria-busy", "false");
  if (!summary) {
    container.innerHTML = `<p class="ai-status" role="status">${escapeHtml(EMPTY_TEXT)}</p>`;
    return;
  }
  const gauge = gaugeModel(summary.slackMin, summary.bufferMin);
  const rows = barModel(summary.comparison, { selectedId, recommendedId: summary.recommendedRouteId });
  const depart = summary.recommendedDepartTime;
  container.innerHTML = `
    <div class="ai-head">
      <span class="ai-icon">${icon("spark", { size: 20 })}</span>
      <div class="ai-label">${summary.source === "gemini" ? "AI 경로 추천 요약" : "경로 비교 요약"}</div>
    </div>
    ${summary.source === "rule" ? `<p class="ai-notice" role="note">${escapeHtml(RULE_NOTICE)}</p>` : ""}
    <div class="ai-body">
      <div class="ai-conclusion">
        <small class="ai-conclusion-label">${escapeHtml(conclusionLabel(summary.recommendedLabel))}</small>
        <div class="ai-depart"><span>권장 출발</span><time datetime="${escapeHtml(depart)}">${escapeHtml(timeOf(depart))}</time></div>
        <p class="ai-headline" title="${escapeHtml(summary.headline)}">${escapeHtml(summary.headline)}</p>
        ${summary.keywords.length ? `<ul class="ai-keywords" aria-label="추천 이유">${summary.keywords.map((keyword) => `<li>${escapeHtml(keyword)}</li>`).join("")}</ul>` : ""}
      </div>
      ${renderGauge(gauge)}
    </div>
    <div class="ai-bars">
      <div class="ai-bars-title" id="ai-bars-title">경로별 예상 소요시간</div>
      <div class="horizontal-bars" role="table" aria-labelledby="ai-bars-title">${renderRows(rows)}</div>
    </div>`;
}

// 카드 선택은 다시 요청하지 않고 막대 강조만 바꾼다.
export function highlightSummaryRoute(container, selectedId) {
  container?.querySelectorAll(".horizontal-row[data-route-id]").forEach((row) => {
    const selected = row.dataset.routeId === selectedId;
    row.classList.toggle("is-selected", selected);
    row.setAttribute("aria-current", String(selected));
  });
}
