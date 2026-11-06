// 추가 패키지 없이 실행: node frontend/tests/map.test.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const source = await read('../js/components/map.js');
const diagnosticUtils = vm.createContext({ KAKAO_JS_KEY: 'test-placeholder' });
vm.runInContext((await read('../js/utils.js')).replace(/^import .*;$/mg, '').replace(/export /g, ''), diagnosticUtils);
const logs = [];
const observers = [];
const pending = [];
const context = vm.createContext({
  getKakaoMapErrorDetails: diagnosticUtils.getKakaoMapErrorDetails,
  console: { error: (...args) => logs.push(args) },
  escapeHtml: (value) => String(value).replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
  loadKakaoMapSdk: () => new Promise((resolve, reject) => pending.push({ resolve, reject })),
  ResizeObserver: class {
    constructor() { observers.push(this); }
    observe() { this.active = true; }
    disconnect() { this.active = false; }
  },
});
vm.runInContext(source.replace(/^import .*;$/mg, '').replace(/export /g, ''), context);
const routes = JSON.parse(await read('../js/mock/routes.json'));
const point = { lat: 35, lng: 129 };
for (const path of [
  [point, { ...point, lng: 130 }],
  [point, { ...point, lat: 36 }],
  [point, point],
  Array.from({ length: 150000 }, (_, i) => ({ lat: 35 + i / 1000000, lng: 129 })),
]) {
  assert.equal(context.validateRoutePath(path), null);
  const projected = context.projectRoutePath(path, 320, 330);
  assert(projected.every(({ x, y }) => Number.isFinite(x) && Number.isFinite(y)
    && x >= 0 && x <= 320 && y >= 0 && y <= 330));
  if (path[0].lng !== path.at(-1).lng) assert.notEqual(projected[0].x, projected.at(-1).x);
  if (path[0].lat !== path.at(-1).lat) assert.notEqual(projected[0].y, projected.at(-1).y);
}
for (const invalid of [null, [], [point], new Array(2), [point, null],
  [point, { lat: NaN, lng: 129 }], [point, { lat: 91, lng: 129 }],
  [point, { lat: 35, lng: 181 }], [point, { lat: '35', lng: 129 }]]) {
  assert(context.validateRoutePath(invalid));
}
assert.equal(new Set(routes.map(({ path }) => JSON.stringify(context.projectRoutePath(path, 800, 378)))).size, 3);

const container = {
  clientWidth: 320, clientHeight: 330, innerHTML: '',
  replaceChildren() { this.innerHTML = ''; },
  querySelector() { return { setAttribute() {}, innerHTML: '' }; },
};
const options = { route: routes[0], from: '<img src=x>', to: '동의대학교', color: '#2563EB', isExample: true };
const first = context.renderRouteMap(container, options);
const last = context.renderRouteMap(container, { ...options, from: '마지막 선택', route: routes[2] });
pending[1].resolve(null);
await last;
pending[0].reject(new Error('늦게 도착한 오류'));
await first;
assert(container.innerHTML.includes('마지막 선택'));
assert.equal(observers.filter((observer) => observer.active).length, 1);
const failure = context.renderRouteMap(container, options);
pending[2].reject(new Error('SDK 실패'));
await failure;
assert(container.innerHTML.includes('불러오지 못했어요'));
assert.equal(logs.length, 1); // 무효화된 이전 요청은 로그도 남기지 않는다.
assert.equal(logs[0][1].stage, 'sdk-load');
const renderFailure = context.renderRouteMap(container, options);
pending.at(-1).resolve({ maps: { LatLng: function () { throw new Error('지도 생성 오류'); } } });
await renderFailure;
assert.equal(logs.at(-1)[1].stage, 'map-render');
assert.equal(logs.at(-1)[1].code, 'MAP_RENDER_FAILED');
assert(!container.innerHTML.includes('<img'));
await context.renderRouteMap(container, { ...options, route: { path: [] } });
assert(container.innerHTML.includes('두 개 이상'));
assert.equal(observers.filter((observer) => observer.active).length, 0);
context.destroyRouteMap(container);
console.log('PASS: 좌표 검증·15만 점 투영·경로별 모양·선택 경쟁·SDK 실패·HTML 처리·감시 정리');

const scripts = [];
let timeout;
const sdkContext = vm.createContext({
  KAKAO_JS_KEY: 'test-placeholder', window: {},
  document: {
    createElement: () => ({ remove() { this.removed = true; } }),
    head: { appendChild(script) { scripts.push(script); } },
  },
  setTimeout(callback) { timeout = callback; return 1; },
  clearTimeout() {},
});
vm.runInContext((await read('../js/utils.js')).replace(/^import .*;$/mg, '').replace(/export /g, ''), sdkContext);
const timedOut = sdkContext.loadKakaoMapSdk();
assert.equal(timedOut, sdkContext.loadKakaoMapSdk());
const timeoutCheck = assert.rejects(timedOut, /시간 초과/);
timeout();
await timeoutCheck;
assert(scripts[0].removed);
const retry = sdkContext.loadKakaoMapSdk();
const failureCheck = assert.rejects(retry, /로드 실패/);
scripts[1].onerror();
await failureCheck;
const success = sdkContext.loadKakaoMapSdk();
sdkContext.window.kakao = { maps: { load(callback) { callback(); }, Map: function () {} } };
scripts[2].onload();
assert.equal(await success, sdkContext.window.kakao);
console.log('PASS: SDK 공유 로딩·시간 초과·네트워크 실패·재시도·성공');

for (const message of [
  'SDK https://dapi.kakao.com/v2/maps/sdk.js?appkey=test-placeholder&autoload=false',
  '키 test-placeholder 오류',
  'https://example.com/?appkey=other-secret&x=1',
]) {
  const error = new Error(message);
  error.stack = 'stack with test-placeholder';
  const details = diagnosticUtils.getKakaoMapErrorDetails(error, 'map-render');
  assert(!JSON.stringify(details).includes('test-placeholder'));
  assert(!JSON.stringify(details).includes('other-secret'));
  assert(!('stack' in details));
}

function loaderHarness(maps) {
  let timeoutCallback, script;
  const loader = vm.createContext({
    KAKAO_JS_KEY: 'test-placeholder', window: { kakao: { maps } },
    document: { createElement: () => ({ remove() {} }), head: { appendChild(value) { script = value; } } },
    setTimeout(callback) { timeoutCallback = callback; return 1; }, clearTimeout() {},
  });
  return { loader, init: async () => vm.runInContext((await read('../js/utils.js')).replace(/^import .*;$/mg, '').replace(/export /g, ''), loader),
    load: () => script.onload(), timeout: () => timeoutCallback() };
}
for (const [maps, expected] of [
  [{}, 'SDK_INVALID_RESPONSE'],
  [{ load() { throw new Error('initialize failed'); } }, 'SDK_INITIALIZATION_FAILED'],
  [{ load(callback) { callback(); } }, 'SDK_INITIALIZATION_FAILED'],
  [{ load() {} }, 'SDK_INITIALIZATION_TIMEOUT'],
]) {
  const harness = loaderHarness(maps);
  await harness.init();
  const promise = harness.loader.loadKakaoMapSdk();
  const check = assert.rejects(promise, (error) => error.code === expected);
  harness.load();
  if (expected === 'SDK_INITIALIZATION_TIMEOUT') harness.timeout();
  await check;
}
const download = loaderHarness({});
await download.init();
const waiting = download.loader.loadKakaoMapSdk();
const downloadCheck = assert.rejects(waiting, (error) => error.code === 'SDK_DOWNLOAD_TIMEOUT');
download.timeout(); await downloadCheck;
console.log('PASS: SDK 다운로드/초기화/지도 생성 오류 구분·늦은 응답 무시·진단 로그 키 마스킹');
