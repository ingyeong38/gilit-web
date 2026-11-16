// 경로 조회 모드와 독립적인 그래프 데이터 연결. 예시 ID를 실제 ID로 바꾸지 않는다.
export async function loadGraphPresentation({ search, mode, baseUrl, hostname, fetcher = fetch }) {
  const development = ["localhost", "127.0.0.1", "::1", "[::1]"].includes(hostname);
  const read = async (url) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetcher(url, { signal: controller.signal });
      if (!response.ok) {
        const error = new Error(`그래프 조회 실패 (${response.status})`);
        error.status = response.status;
        throw error;
      }
      const data = await response.json();
      if (!Array.isArray(data)) throw new Error("그래프 응답은 배열이어야 합니다.");
      return data;
    } finally { clearTimeout(timer); }
  };
  if (!["auto", "api", "example", "off"].includes(mode)) throw new Error("그래프 모드 설정을 확인해 주세요.");
  if (mode === "off") return { graphs: [], isExample: false, message: "그래프 표시가 꺼져 있습니다." };
  if (mode === "auto" || mode === "api") {
    const params = new URLSearchParams();
    for (const key of ["from", "to", "arrive", "buffer", "fromLat", "fromLng", "toLat", "toLng"]) {
      if (search[key] !== undefined && search[key] !== null) params.set(key, search[key]);
    }
    try {
      return { graphs: await read(`${baseUrl}/routes/graph?${params}`), isExample: false, message: "" };
    } catch (error) {
      // API 장애를 정상 예측/예시로 감추지 않는다. API 부재(404)인 개발 환경만 예시 허용.
      if (mode !== "auto" || error.status !== 404) throw error;
      if (!development) return { graphs: [], isExample: false, message: "그래프 API가 아직 구현되지 않았습니다." };
    }
  }
  if (!development) return { graphs: [], isExample: false, message: "예시 그래프는 로컬 개발 환경에서만 표시합니다." };
  const [graphs, routes] = await Promise.all([read("/js/mock/routeGraph.json"), read("/js/mock/routes.json")]);
  // 실제 카드와 매칭하지 않는다. 예시 카드와 예시 그래프의 정확한 ID만 대조한다.
  const counts = new Map();
  for (const graph of graphs) counts.set(graph?.routeId, (counts.get(graph?.routeId) || 0) + 1);
  const ids = new Set(routes.filter(route => typeof route?.id === "string").map(route => route.id));
  const matched = graphs.filter(graph => ids.has(graph?.routeId) && counts.get(graph.routeId) === 1);
  return { graphs: matched, routes: routes.filter(route => matched.some(graph => graph.routeId === route.id)),
    isExample: true, message: "개발용 예시 · 실제 선택 경로와 무관하며 실제 교통 예측이 아닙니다." };
}
