// SFR-006 데이터 검증·좌표 계산. 시간대 없는 ISO 시각은 한국 시간으로 해석한다.
export function graphTimestamp(value) {
  if (typeof value !== "string") return NaN;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?(Z|[+-]\d{2}:\d{2})?$/.exec(value);
  if (!match) return NaN;
  const [, year, month, day, hour, minute, second = "0", , zone] = match;
  const calendar = new Date(Date.UTC(+year, +month - 1, +day));
  if (calendar.getUTCFullYear() !== +year || calendar.getUTCMonth() !== +month - 1 || calendar.getUTCDate() !== +day || +hour > 23 || +minute > 59 || +second > 59) return NaN;
  if (zone && zone !== "Z" && (+zone.slice(1, 3) > 23 || +zone.slice(4) > 59)) return NaN;
  return Date.parse(value + (zone ? "" : "+09:00"));
}

export function graphTime(value) {
  const timestamp = typeof value === "number" ? value : graphTimestamp(value);
  if (!Number.isFinite(timestamp)) return "시각 미제공";
  const date = new Date(timestamp + 9 * 60 * 60 * 1000);
  const pad = n => String(n).padStart(2, "0");
  return `${date.getUTCMonth() + 1}/${date.getUTCDate()} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
}

export function normalizeGraphPoints(input) {
  const unique = new Map();
  let discarded = 0;
  for (const point of Array.isArray(input) ? input : []) {
    const timestamp = graphTimestamp(point?.departTime);
    if (!Number.isFinite(timestamp) || typeof point?.durationMin !== "number" || !Number.isFinite(point.durationMin) || point.durationMin < 0) { discarded++; continue; }
    if (unique.has(timestamp)) discarded++;
    unique.set(timestamp, { departTime: point.departTime, durationMin: point.durationMin, timestamp });
  }
  return { points: [...unique.values()].sort((a, b) => a.timestamp - b.timestamp), discarded };
}

// ID를 문자열로 임의 변환하거나 순서로 매칭하지 않는다. 중복 routeId도 모호하므로 제외한다.
export function normalizeRouteGraphs(input, routes) {
  const ids = new Set(routes.map(route => route.id));
  const seen = new Set(), ambiguous = new Set(), result = new Map();
  for (const graph of Array.isArray(input) ? input : []) {
    if (typeof graph?.routeId !== "string" || !ids.has(graph.routeId)) continue;
    if (seen.has(graph.routeId)) { ambiguous.add(graph.routeId); result.delete(graph.routeId); continue; }
    seen.add(graph.routeId);
    if (!ambiguous.has(graph.routeId)) result.set(graph.routeId, normalizeGraphPoints(graph.points));
  }
  return result;
}

export function durationChartModel(input, recommendedTime, range) {
  const normalized = normalizeGraphPoints(input);
  const points = normalized.points;
  if (!points.length) return { ...normalized, points: [] };
  const minTime = points[0].timestamp, maxTime = points.at(-1).timestamp;
  const min = Math.min(...points.map(p => p.durationMin), Number.isFinite(range?.min) ? range.min : Infinity);
  const max = Math.max(...points.map(p => p.durationMin), Number.isFinite(range?.max) ? range.max : 0);
  const yMin = Math.max(0, Math.floor(min - Math.max((max - min) * .15, 2)));
  const yMax = Math.ceil(max + Math.max((max - min) * .15, 2));
  const xAt = time => maxTime === minTime ? 360 : 64 + (time - minTime) / (maxTime - minTime) * 592;
  const yAt = value => 200 - (value - yMin) / (yMax - yMin) * 156;
  const recommended = graphTimestamp(recommendedTime);
  return { ...normalized, points: points.map(p => ({ ...p, x: xAt(p.timestamp), y: yAt(p.durationMin) })),
    yTicks: Array.from({ length: 5 }, (_, i) => { const value = yMin + (yMax - yMin) * i / 4; return { value, y: yAt(value) }; }),
    xTicks: Array.from({ length: maxTime === minTime ? 1 : 4 }, (_, i) => { const timestamp = minTime + (maxTime - minTime) * i / 3; return { timestamp, x: xAt(timestamp) }; }),
    recommendedX: Number.isFinite(recommended) && recommended >= minTime && recommended <= maxTime ? xAt(recommended) : null };
}

// 실제 시간순으로 정규화된 바로 이전 지점과 비교한다.
export function durationChange(points, index) {
  if (index === 0) return { tone: "neutral", text: "비교할 이전 시간대 없음" };
  const difference = Number((points[index].durationMin - points[index - 1].durationMin).toFixed(2));
  return { tone: difference < 0 ? "decrease" : difference > 0 ? "increase" : "neutral",
    text: `이전 시각(${graphTime(points[index - 1].departTime).split(" ")[1]}) 대비 ${difference === 0 ? "변화 없음" : `${Math.abs(difference)}분 ${difference < 0 ? "단축" : "증가"}`}` };
}

export function summaryPosition({ width, height, cardWidth, cardHeight, x, y }) {
  const gap = 16, padding = 8;
  const side = x + gap + cardWidth <= width - padding ? "right" : "left";
  const left = Math.max(padding, Math.min(side === "right" ? x + gap : x - gap - cardWidth, width - cardWidth - padding));
  const top = Math.max(padding, Math.min(y - cardHeight / 2, height - cardHeight - padding));
  return { side, left, top, tailTop: Math.max(16, Math.min(y - top, cardHeight - 16)) };
}
