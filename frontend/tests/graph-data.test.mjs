import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../js/graphData.js', import.meta.url), 'utf8');
const context = vm.createContext({ URLSearchParams, AbortController, setTimeout, clearTimeout });
vm.runInContext(source.replace('export async function', 'async function'), context);
const { loadGraphPresentation } = context;
const example = async url => url.startsWith('/api/') ? { ok: false, status: 404 } : {
  ok: true, json: async () => JSON.parse(await readFile(new URL('..'+url, import.meta.url), 'utf8')),
};
const settings = { search: { from: '출발', to: '도착', buffer: 10, fromLat: 35 },
  mode: 'auto', baseUrl: '/api', hostname: 'localhost', fetcher: example };
const data = await loadGraphPresentation(settings);
assert(data.isExample);
assert.equal(data.routes.length, 3);
assert(data.graphs.every(graph => data.routes.some(route => route.id === graph.routeId)));
assert(!data.routes.some(route => route.id === 'recommend'));
const production = await loadGraphPresentation({ ...settings, hostname: 'gilit.example' });
assert(!production.isExample);
assert.equal(production.graphs.length, 0);
await assert.rejects(loadGraphPresentation({ ...settings, fetcher: async () => ({ ok: false, status: 502 }) }));
const live = await loadGraphPresentation({ ...settings, mode: 'api', fetcher: async url => {
  assert(url.includes('buffer=10'));
  assert(url.includes('fromLat=35'));
  return { ok: true, json: async () => [{ routeId: 'recommend', points: [] }] };
} });
assert(!live.isExample);
const unmatched = await loadGraphPresentation({ ...settings, fetcher: async url => {
  if (url.startsWith('/api/')) return { ok: false, status: 404 };
  return { ok: true, json: async () => url.includes('routeGraph')
    ? [{ routeId: 'missing', points: [] }, { routeId: 'duplicate', points: [] }, { routeId: 'duplicate', points: [] }]
    : [{ id: 'duplicate' }] };
} });
assert.equal(unmatched.graphs.length, 0);
console.log('PASS: 로컬 예시·정확한 ID/중복 검사·운영 차단·API 장애 유지·실제 API 파라미터');
