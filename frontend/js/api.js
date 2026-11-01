// 서버 호출은 이 파일에만 둔다.
import { USE_MOCK, BASE_URL } from "/js/config.js";

function buildUrl(path, params = {}) {
  const entries = Object.entries(params).filter(
    ([, value]) => value !== undefined && value !== null && value !== ""
  );
  const query = new URLSearchParams(entries).toString();
  return `${BASE_URL}${path}${query ? `?${query}` : ""}`;
}

async function request(mockFile, path, params) {
  const url = USE_MOCK ? `/js/mock/${mockFile}` : buildUrl(path, params);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`요청 실패: ${url} (${response.status})`);
  }
  return response.json();
}

export function getRoutes({ from, to, arrive, buffer } = {}) {
  return request("routes.json", "/routes", { from, to, arrive, buffer });
}

export function getRouteGraph({ from, to, arrive } = {}) {
  return request("routeGraph.json", "/routes/graph", { from, to, arrive });
}

export function searchPlaces(q) {
  return request("places.json", "/places", { q });
}

export function getFavorites() {
  return request("favorites.json", "/favorites");
}

export function getHistory() {
  return request("history.json", "/history");
}

export function getStats() {
  return request("stats.json", "/stats");
}
