import { icon } from "/js/components/icon.js";
import { escapeHtml } from "/js/utils.js";

const FAKE_PATHS = [
  "M80 295 C170 270 190 200 265 220 S365 155 425 180 S520 100 670 115",
  "M80 295 C155 305 230 245 280 260 S380 210 430 160 S555 155 670 115",
  "M80 295 C145 245 210 270 255 205 S350 230 410 190 S520 190 670 115",
];

function renderFakeMap(container, { routeIndex, color, from, to }) {
  const path = FAKE_PATHS[routeIndex % FAKE_PATHS.length];
  container.innerHTML = `
    <div class="map-grid"></div>
    <span class="road road-a">남해고속도로</span><span class="road road-b">낙동대로</span><span class="road road-c">동서고가로</span>
    <span class="map-place place-a">김해시</span><span class="map-place place-b">사상구</span><span class="map-place place-c">부산진구</span>
    <svg viewBox="0 0 740 370" preserveAspectRatio="none">
      <path class="route-shadow" d="${path}" />
      <path class="route-path" d="${path}" style="stroke: ${color}" />
    </svg>
    <div class="map-pin start-pin">${icon("car", { size: 15 })}<span>${escapeHtml(from)}</span></div>
    <div class="map-pin end-pin">${icon("location", { size: 16, filled: true })}<span>${escapeHtml(to)}</span></div>
    <div class="map-controls"><button type="button">+</button><button type="button">−</button></div>
    <div class="map-legend"><span style="background: ${color}"></span>선택한 경로</div>
  `;
}

// 지도 진입점. 카카오맵으로 교체할 때는 이 함수의 내용만 바꾼다.
// options: { route, routeIndex, color, from, to } (route.path가 실제 좌표 배열)
export function renderRouteMap(container, options) {
  renderFakeMap(container, options);
}
