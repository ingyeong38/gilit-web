import { escapeHtml, loadKakaoMapSdk, getKakaoMapErrorDetails } from "/js/utils.js";

const states = new WeakMap();

// 잘못된 점을 건너뛰어 서로 다른 구간을 연결하지 않는다.
export function validateRoutePath(path) {
  if (!Array.isArray(path) || path.length < 2) return "경로 좌표가 두 개 이상 필요해요.";
  if (Array.from(path).some((p) => !p || !Number.isFinite(p.lat) || !Number.isFinite(p.lng)
    || Math.abs(p.lat) > 90 || Math.abs(p.lng) > 180)) return "경로에 올바르지 않은 좌표가 있어요.";
  return null;
}

// 위도는 위쪽, 경도는 오른쪽으로 투영하고 종횡비를 유지한다.
export function projectRoutePath(path, width, height) {
  // 긴 실제 경로도 함수 인자 개수 제한에 걸리지 않게 순회한다.
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const { lat, lng } of path) {
    minX = Math.min(minX, lng);
    maxX = Math.max(maxX, lng);
    minY = Math.min(minY, lat);
    maxY = Math.max(maxY, lat);
  }
  const correction = Math.max(0.01, Math.cos((minY + maxY) / 2 * Math.PI / 180));
  const dx = (maxX - minX) * correction, dy = maxY - minY;
  const scale = Math.min(dx ? (width - 88) / dx : Infinity, dy ? (height - 140) / dy : Infinity);
  const safeScale = Number.isFinite(scale) ? scale : 0;
  return path.map((p) => ({
    x: width / 2 + ((p.lng - minX) * correction - dx / 2) * safeScale,
    y: height / 2 - (p.lat - minY - dy / 2) * safeScale,
  }));
}

function renderPreview(container, state, options, message) {
  const { route, color, from, to, isExample } = options;
  container.innerHTML = `<div class="map-grid"></div>
    <svg class="route-preview" role="img" aria-label="선택한 경로 좌표 미리보기"></svg>
    <div class="map-status" role="status">${isExample ? "예시 경로 · " : ""}좌표 미리보기<br>${escapeHtml(message)}</div>
    <div class="map-endpoints">출발: ${escapeHtml(from)} → 도착: ${escapeHtml(to)}</div>`;
  const svg = container.querySelector(".route-preview");
  const draw = () => {
    const width = Math.max(container.clientWidth, 180), height = Math.max(container.clientHeight, 220);
    const points = projectRoutePath(route.path, width, height);
    const line = points.map((p) => `${p.x},${p.y}`).join(" ");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const endpoints = [points[0], points.at(-1)];
    svg.innerHTML = `<polyline class="route-shadow" points="${line}" />
      <polyline class="route-path" points="${line}" stroke="${color}" />
      ${endpoints.map((p, i) => `<circle cx="${p.x}" cy="${p.y}" r="7" fill="${i ? '#2563eb' : '#16a36a'}" stroke="white" stroke-width="2" />
      <text x="${p.x}" y="${p.y + (i ? 26 : -16)}" text-anchor="middle">${i ? '도착' : '출발'}</text>`).join("")}`;
  };
  draw();
  watchSize(container, state, draw);
}

function watchSize(container, state, callback) {
  state.observer?.disconnect();
  state.removeResize?.();
  if (typeof ResizeObserver !== "undefined") {
    state.observer = new ResizeObserver(callback);
    state.observer.observe(container);
  } else {
    window.addEventListener("resize", callback);
    state.removeResize = () => window.removeEventListener("resize", callback);
  }
}

function clearView(state) {
  state.observer?.disconnect();
  state.removeResize?.();
  state.observer = null;
  state.removeResize = null;
  state.overlays?.forEach((overlay) => overlay.setMap(null));
  state.overlays = [];
  if (state.map && state.zoom) state.map.removeControl(state.zoom);
  state.map = null;
  state.zoom = null;
}

export function destroyRouteMap(container) {
  const state = states.get(container);
  if (!state) return;
  clearView(state);
  states.delete(container); // 무효화되어 진행 중인 SDK 완료도 무시한다.
  container.replaceChildren();
}

function renderKakaoMap(container, state, options, kakao) {
  clearView(state);
  container.innerHTML = `<div class="kakao-map-canvas"></div><div class="map-status" role="status">${options.isExample ? '예시 경로 · ' : ''}카카오 지도</div>
    <div class="map-endpoints">출발: ${escapeHtml(options.from)} → 도착: ${escapeHtml(options.to)}</div>`;
  const path = options.route.path.map((p) => new kakao.maps.LatLng(p.lat, p.lng));
  const map = new kakao.maps.Map(container.querySelector(".kakao-map-canvas"), { center: path[0], level: 5 });
  state.map = map;
  state.zoom = new kakao.maps.ZoomControl();
  map.addControl(state.zoom, kakao.maps.ControlPosition.RIGHT);
  state.overlays.push(new kakao.maps.Polyline({ map, path, strokeWeight: 5, strokeColor: options.color, strokeOpacity: 1 }));
  [path[0], path.at(-1)].forEach((position, i) => {
    const label = `${i ? '도착' : '출발'}: ${i ? options.to : options.from}`;
    state.overlays.push(new kakao.maps.Marker({ map, position, title: label }));
    const content = document.createElement("span");
    content.className = `map-endpoint-label endpoint-${i}`;
    content.textContent = i ? "도착" : "출발";
    state.overlays.push(new kakao.maps.CustomOverlay({ map, position, content, yAnchor: i ? -0.3 : 2.8 }));
  });
  const bounds = new kakao.maps.LatLngBounds();
  path.forEach((p) => bounds.extend(p));
  const same = options.route.path.every((p) => p.lat === options.route.path[0].lat && p.lng === options.route.path[0].lng);
  const fit = () => {
    map.relayout();
    if (same) { map.setCenter(path[0]); map.setLevel(4); }
    else map.setBounds(bounds, 70, 50, 70, 50);
  };
  fit();
  watchSize(container, state, fit);
}

// 기존 options: { route, routeIndex, color, from, to }와 호환. 비동기 완료는 최신 선택만 반영.
export async function renderRouteMap(container, options) {
  destroyRouteMap(container);
  const state = { overlays: [] };
  states.set(container, state);
  const error = validateRoutePath(options.route?.path);
  if (error) {
    container.innerHTML = `<div class="map-error" role="status">${escapeHtml(error)}</div>`;
    return;
  }
  const safeOptions = { ...options, color: /^#[0-9a-f]{6}$/i.test(options.color) ? options.color : "#2563EB" };
  renderPreview(container, state, safeOptions, "지도 배경을 준비하고 있어요.");
  let stage = "sdk-load";
  try {
    const kakao = await loadKakaoMapSdk();
    if (states.get(container) !== state) return;
    if (kakao) {
      stage = "map-render";
      renderKakaoMap(container, state, safeOptions, kakao);
    }
    else renderPreview(container, state, safeOptions, "지도 키가 없어 좌표로 표시해요.");
  } catch (error) {
    if (states.get(container) !== state) return;
    const details = getKakaoMapErrorDetails(error, stage);
    console.error("[Gilit 지도] 지도 표시 실패", details);
    clearView(state);
    renderPreview(container, state, safeOptions, "지도를 불러오지 못했어요. 좌표로 표시해요.");
  }
}
