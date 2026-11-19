// node frontend/tests/favorites.test.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
const strip = s => s.replace(/^import .*;$/mg, '').replace(/export /g, '');
const source = strip(await readFile(new URL('../js/api.js', import.meta.url), 'utf8'));
const values = new Map([['gilit:mock:favorites', JSON.stringify([{ id: 'legacy', name: '공용 장소' }])]]);
let user = { id: 'A' }, response;
const requests = [];
const ctx = vm.createContext({
  USE_MOCK: true, BASE_URL: '/api', getUser: () => user, URLSearchParams, crypto: webcrypto,
  localStorage: { getItem: k => values.get(k) ?? null, setItem: (k,v) => values.set(k,v) },
  fetch: async (url, options) => { requests.push({ url, options }); return response; },
});
vm.runInContext(source, ctx);
const list = async () => JSON.parse(JSON.stringify(await ctx.getFavorites()));
assert.deepEqual(await list(), []);
const a = await ctx.addFavorite({ name: 'A 집' });
assert.equal((await list())[0].name, 'A 집');
user = null;
await assert.rejects(ctx.getFavorites(), e => e.status === 401);
user = { id: 'B' };
assert.deepEqual(await list(), []);
await ctx.removeFavorite(a.id);
const b = await ctx.addFavorite({ name: 'B 회사' });
assert.equal((await list())[0].id, b.id);
user = { id: 'A' };
assert.equal((await list())[0].id, a.id);
await ctx.removeFavorite(a.id);
assert.deepEqual(await list(), []);
user = { id: 'B' };
assert.equal((await list())[0].id, b.id);
assert.ok(values.get('gilit:mock:favorites').includes('legacy'));
vm.runInContext('USE_MOCK = false', ctx);
for (const operation of [() => ctx.getFavorites(), () => ctx.addFavorite({ name: 'A' }), () => ctx.removeFavorite('A')]) {
  user = { id: 'A' };
  let resolve;
  response = new Promise(r => { resolve = r; });
  const pending = operation();
  user = { id: 'B' };
  resolve({ ok: true, status: 200, json: async () => [{ id: 'A' }] });
  await assert.rejects(pending, e => e.status === 409);
}
assert.equal(requests[0].options.cache, 'no-store');
console.log('PASS: 즐겨찾기 A/B 조회·추가·삭제 분리, 비로그인 차단, 공용 데이터 보존, 늦은 GET/POST/DELETE 응답 거부');

const page = (await readFile(new URL('../js/pages/favorites.js', import.meta.url), 'utf8'))
  .replace(/^import[\s\S]*?from ["'][^"']+["'];\r?\n/gm, '');
const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id, { innerHTML: '', textContent: '', hidden: false, addEventListener() {} });
  return elements.get(id);
};
let authListener, modal, pendingReads = [], reads = 0, reloads = 0;
const events = {}, docEvents = {};
let rechecks = 0;
user = { id: 'A' };
const pageUtils = vm.createContext({ KAKAO_JS_KEY: '', URLSearchParams });
vm.runInContext(strip(await readFile(new URL('../js/utils.js', import.meta.url), 'utf8')), pageUtils);
vm.runInContext(strip(await readFile(new URL('../js/links.js', import.meta.url), 'utf8')), pageUtils);
const pageCtx = vm.createContext({
  URLSearchParams, location: { search: '', reload: () => reloads++ },
  document: { getElementById: element, querySelectorAll: () => [], addEventListener: (type, fn) => { docEvents[type] = fn; }, visibilityState: 'visible' },
  window: { addEventListener: (type, fn) => { events[type] = fn; } },
  getUser: () => user, onAuthChange: fn => { authListener = fn; },
  requirePageAccess: () => Promise.resolve(), renderIcons() {}, icon: () => '', escapeHtml: String, recheckAuth: () => { rechecks++; },
  historyCoordinates: pageUtils.historyCoordinates,
  savedTabFromQuery: pageUtils.savedTabFromQuery,
  getFavorites: () => { reads++; return new Promise(r => pendingReads.push(r)); },
  getHistory: async () => [], showToast() {},
  openAddPlaceModal: value => { modal = value; },
  addFavorite: async () => { throw Error('stale modal must not submit'); },
});
vm.runInContext(page, pageCtx);
const tick = () => new Promise(r => setImmediate(r));
await tick();
assert.equal(reads, 1);
user = { id: 'B' }; authListener();
pendingReads[1]([{ id: 'B', name: 'B 회사', type: '회사', address: '부산' }]);
await tick();
assert.ok(element('saved-content').innerHTML.includes('B 회사'));
pendingReads[0]([{ id: 'A', name: 'A 집', type: '집', address: '서울' }]);
await tick();
assert.ok(!element('saved-content').innerHTML.includes('A 집'));
pageCtx.openAddModal();
user = { id: 'C' }; authListener();
await modal.onAdd({ name: '이전 계정 입력' });
events.pagehide();
assert.ok(!element('saved-content').innerHTML.includes('B 회사'));
events.pageshow({ persisted: true });
assert.equal(reloads, 1);
user = null; authListener();
assert.equal(element('favorites-count').textContent, 0);
console.log('PASS: 계정 전환 즉시 화면 비우기, 늦은 A 목록 무시, 이전 계정 모달 제출 차단, BFCache 복원 인증 재검사');
