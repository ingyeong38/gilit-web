// node frontend/tests/routes.test.mjs — 실제 모드가 목업으로 대체되지 않는지 확인한다.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const strip = (source) => source.replace(/^import[\s\S]*?from ["'][^"']+["'];/mg, '').replace(/export /g, '');
const calls = [];
const path = [{ lat: 35.2285, lng: 128.8894 }, { lat: 35.2286, lng: 128.8895 }, { lat: 35.2287, lng: 128.8896 }];
let status = 200;
const context = vm.createContext({ USE_MOCK: true, USE_MOCK_ROUTES: false, GRAPH_API_ENABLED: false, BASE_URL: '/api', URLSearchParams,
  localStorage: { getItem: () => null },
  fetch: async (url) => {
    calls.push(url);
    return { ok: status === 200, status,
      json: async () => status === 200 ? [{ id: 'kakao-time', dataSource: 'kakao', path, durationMin: 20, distanceKm: 10 }]
        : { message: '실제 조회 실패' } };
  },
});
vm.runInContext(strip(await readFile(new URL('../js/api.js', import.meta.url), 'utf8')), context);
const routes = await context.getRoutes({ from: '김해시청', to: '동의대학교', arrive: '2026-11-07T09:00:00+09:00', buffer: 10, fromLat: 35.2, fromLng: 128.8 });
assert.equal(routes[0].path, path);
assert.equal(routes[0].durationMin, 20);
assert.equal(calls[0].split('?')[0], '/api/routes');
assert.equal(new URL(calls[0], 'http://localhost').searchParams.get('from'), '김해시청');
assert.equal(new URL(calls[0], 'http://localhost').searchParams.get('fromLat'), '35.2');
const graph = await context.getRouteGraph({});
assert.equal(graph.length, 0);
assert.equal(calls.length, 1); // 미구현 그래프 API를 부르지 않는다.
status = 502;
await assert.rejects(context.getRoutes({ from: '김해시청', to: '동의대학교' }), (error) => error.status === 502);
assert(calls.every((url) => !url.includes('/mock/')));
status = 200;
await context.getFavorites();
assert.equal(calls.at(-1), '/js/mock/favorites.json'); // 경로 실데이터 모드가 다른 기능의 모드를 바꾸지 않는다.
console.log('PASS: 실제 상세 좌표·카드 지표 전달, 쿼리 호환, 그래프 독립, 실패 시 목업 미사용');
