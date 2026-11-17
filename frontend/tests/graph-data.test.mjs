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
// /api/routes 카드 (그래프 요청의 card 파라미터 원본)
const cards = [{ id: 'recommend', departTime: '2026-11-18T08:20:00+09:00' }, { id: 'time', departTime: '2026-11-18T08:10:00+09:00' }];
const settings = { search: { from: '출발', to: '도착', buffer: 10, fromLat: 35 }, routes: cards,
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

// card=<id>@<departTime> 반복 (set이 아니라 append), 기존 쿼리 유지, 인코딩은 URLSearchParams
const urls = [];
const capture = async url => { urls.push(url); return { ok: true, json: async () => [] }; };
await loadGraphPresentation({ ...settings, mode: 'api', fetcher: capture });
const sent = new URL(urls[0], 'http://localhost');
assert.equal(sent.pathname, '/api/routes/graph');
assert.deepEqual(sent.searchParams.getAll('card'), ['recommend@2026-11-18T08:20:00+09:00', 'time@2026-11-18T08:10:00+09:00']);
assert(urls[0].includes('card=recommend%402026-11-18T08%3A20%3A00%2B09%3A00')); // + 가 공백으로 바뀌지 않게
assert.equal(sent.searchParams.get('buffer'), '10');
assert.equal(sent.searchParams.get('fromLat'), '35');
assert.equal(sent.searchParams.get('from'), '출발');

// 카드 0개: 요청하지 않는다 (auto 모드의 예시 대체도 하지 않는다)
for (const routes of [[], undefined, null]) {
  urls.length = 0;
  const empty = await loadGraphPresentation({ ...settings, routes, fetcher: capture });
  assert.equal(urls.length, 0);
  assert.equal(empty.graphs.length, 0);
  assert(!empty.isExample && empty.message);
}

// departTime(또는 id)이 없는 카드는 건너뛴다. 남는 카드가 없으면 요청하지 않는다
urls.length = 0;
await loadGraphPresentation({ ...settings, mode: 'api', fetcher: capture, routes: [
  { id: 'recommend' }, { id: 'time', departTime: '' }, { id: 'distance', departTime: null },
  { departTime: '2026-11-18T08:00:00+09:00' }, { id: 'free', departTime: '2026-11-18T08:05:00+09:00' }] });
assert.deepEqual(new URL(urls[0], 'http://localhost').searchParams.getAll('card'), ['free@2026-11-18T08:05:00+09:00']);
urls.length = 0;
const none = await loadGraphPresentation({ ...settings, mode: 'api', fetcher: capture, routes: [{ id: 'recommend' }] });
assert.equal(urls.length, 0);
assert.equal(none.graphs.length, 0);

// 5장 이상: 앞에서부터 4장만 보낸다
urls.length = 0;
const five = ['recommend', 'time', 'distance', 'free', 'extra'].map((id, i) => ({ id, departTime: `2026-11-18T08:0${i}:00+09:00` }));
await loadGraphPresentation({ ...settings, mode: 'api', fetcher: capture, routes: five });
assert.deepEqual(new URL(urls[0], 'http://localhost').searchParams.getAll('card'),
  five.slice(0, 4).map(route => `${route.id}@${route.departTime}`));

const unmatched = await loadGraphPresentation({ ...settings, fetcher: async url => {
  if (url.startsWith('/api/')) return { ok: false, status: 404 };
  return { ok: true, json: async () => url.includes('routeGraph')
    ? [{ routeId: 'missing', points: [] }, { routeId: 'duplicate', points: [] }, { routeId: 'duplicate', points: [] }]
    : [{ id: 'duplicate' }] };
} });
assert.equal(unmatched.graphs.length, 0);
console.log('PASS: 로컬 예시·정확한 ID/중복 검사·운영 차단·API 장애 유지·실제 API 파라미터·card 반복/0개/누락/4개 제한');
