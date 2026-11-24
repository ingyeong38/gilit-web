// 추가 패키지 없이 실행: node frontend/tests/runtime-config.test.mjs
// GET /api/config(api.js getRuntimeConfig) → js/runtimeConfig.js(한 번만 호출, config.js 대체) → 지도·GA 로드 여부
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const strip = (source) => source.replace(/^import .*;$/mg, '').replace(/export /g, '');
const [utilsSource, apiSource, runtimeSource, analyticsSource, mapSource] = await Promise.all(
  ['../js/utils.js', '../js/api.js', '../js/runtimeConfig.js', '../js/analytics.js', '../js/components/map.js'].map(read),
);

// 상태를 공유하는 모듈에는 ?v=를 붙이지 않는다.
for (const source of [analyticsSource, mapSource, runtimeSource]) {
  assert.doesNotMatch(source, /runtimeConfig\.js\?v=|api\.js\?v=|auth\.js\?v=/);
}
assert.match(analyticsSource, /^import \{ loadRuntimeConfig \} from "\/js\/runtimeConfig\.js";$/m);
assert.match(mapSource, /^import \{ loadRuntimeConfig \} from "\/js\/runtimeConfig\.js";$/m);

function makeRuntime({ fetch, local = {}, useMock = false, timers } = {}) {
  const context = vm.createContext({
    URLSearchParams, AbortController, KAKAO_JS_KEY: '',
    USE_MOCK: useMock, USE_MOCK_STATS: false, USE_MOCK_ROUTES: false, BASE_URL: '/api',
    fetch, localConfig: local,
    setTimeout: timers?.setTimeout ?? setTimeout, clearTimeout: timers?.clearTimeout ?? clearTimeout,
  });
  for (const source of [utilsSource, apiSource, runtimeSource]) vm.runInContext(strip(source), context);
  return context;
}

const ok = (body) => async () => ({ ok: true, status: 200, json: async () => body });
const LOCAL = { KAKAO_JS_KEY: 'local-js-key', GA4_MEASUREMENT_ID: 'G-LOCAL1' };
const plain = (value) => JSON.parse(JSON.stringify(value));

// 1. 서버 값을 쓰고, 여러 번 불러도 요청은 한 번. 응답의 다른 필드는 버린다.
{
  const calls = [];
  const rt = makeRuntime({
    local: LOCAL,
    fetch: async (url, options) => {
      calls.push({ url, cache: options.cache, signal: Boolean(options.signal) });
      return ok({ kakaoJsKey: ' server-js-key ', ga4MeasurementId: 'G-SERVER1', secretKey: 'must-not-leak' })();
    },
  });
  const results = await Promise.all([rt.loadRuntimeConfig(), rt.loadRuntimeConfig(), rt.loadRuntimeConfig()]);
  assert.equal(rt.loadRuntimeConfig(), rt.loadRuntimeConfig());
  assert.deepEqual(calls, [{ url: '/api/config', cache: 'no-store', signal: true }]);
  for (const result of results) assert.deepEqual(plain(result), { kakaoJsKey: 'server-js-key', ga4MeasurementId: 'G-SERVER1' });
  assert(Object.isFrozen(results[0]));
}

// 2. 실패(네트워크 오류·500·JSON 오류)면 config.js 값으로 대체. 예외를 던지지 않는다.
for (const fetch of [
  async () => { throw new TypeError('Failed to fetch'); },
  async () => ({ ok: false, status: 500, json: async () => ({ message: '오류' }) }),
  async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError('bad json'); } }),
]) {
  const rt = makeRuntime({ fetch, local: LOCAL });
  assert.deepEqual(plain(await rt.getRuntimeConfig()), { kakaoJsKey: '', ga4MeasurementId: '' });
  const rt2 = makeRuntime({ fetch, local: LOCAL });
  assert.deepEqual(plain(await rt2.loadRuntimeConfig()), { kakaoJsKey: 'local-js-key', ga4MeasurementId: 'G-LOCAL1' });
}

// 3. 형식 오류는 값마다 빈 값으로 정규화한 뒤 대체. 서버 값이 하나만 있으면 나머지만 config.js에서.
{
  const rt = makeRuntime({ fetch: ok({ kakaoJsKey: 123, ga4MeasurementId: 'UA-1234-1' }), local: LOCAL });
  assert.deepEqual(plain(await rt.loadRuntimeConfig()), { kakaoJsKey: 'local-js-key', ga4MeasurementId: 'G-LOCAL1' });
  const mixed = makeRuntime({ fetch: ok({ kakaoJsKey: 'server-js-key', ga4MeasurementId: '' }), local: LOCAL });
  assert.deepEqual(plain(await mixed.loadRuntimeConfig()), { kakaoJsKey: 'server-js-key', ga4MeasurementId: 'G-LOCAL1' });
  for (const body of [null, [], 'text', { kakaoJsKey: null }]) {
    assert.deepEqual(plain(await makeRuntime({ fetch: ok(body) }).getRuntimeConfig()), { kakaoJsKey: '', ga4MeasurementId: '' });
  }
}

// 4. 둘 다 비면 빈 값. config.js에 이름이 없어도(오래된 로컬 config.js) 실패하지 않는다. 잘못된 로컬 측정 ID도 버린다.
{
  const empty = makeRuntime({ fetch: ok({ kakaoJsKey: '', ga4MeasurementId: '' }), local: { KAKAO_JS_KEY: '', GA4_MEASUREMENT_ID: '' } });
  assert.deepEqual(plain(await empty.loadRuntimeConfig()), { kakaoJsKey: '', ga4MeasurementId: '' });
  const old = makeRuntime({ fetch: ok({}), local: {} });
  assert.deepEqual(plain(await old.loadRuntimeConfig()), { kakaoJsKey: '', ga4MeasurementId: '' });
  const badLocal = makeRuntime({ fetch: ok({}), local: { GA4_MEASUREMENT_ID: 'G-bad id' } });
  assert.equal((await badLocal.loadRuntimeConfig()).ga4MeasurementId, '');
}

// 5. 5초 안에 응답이 없으면 중단하고 대체 값.
{
  const scheduled = [];
  const timers = { setTimeout: (callback, ms) => { scheduled.push({ callback, ms }); return scheduled.length; }, clearTimeout() {} };
  const fetch = (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  });
  const rt = makeRuntime({ fetch, local: LOCAL, timers });
  const pending = rt.loadRuntimeConfig();
  assert.equal(scheduled.length, 1);
  assert.equal(scheduled[0].ms, 5000);
  scheduled[0].callback();
  assert.deepEqual(plain(await pending), { kakaoJsKey: 'local-js-key', ga4MeasurementId: 'G-LOCAL1' });
}

// 6. 전체 Mock은 서버를 부르지 않고 config.js 값만 쓴다.
{
  let called = false;
  const rt = makeRuntime({ fetch: async () => { called = true; }, local: LOCAL, useMock: true });
  assert.deepEqual(plain(await rt.loadRuntimeConfig()), { kakaoJsKey: 'local-js-key', ga4MeasurementId: 'G-LOCAL1' });
  assert.equal(called, false);
}
console.log('PASS: /api/config 값 사용·한 번만 호출·실패/시간 초과/형식 오류 시 config.js 대체·둘 다 비면 빈 값');

// 7. 측정 ID가 비면 gtag를 불러오지 않는다.
for (const ga4MeasurementId of ['', 'UA-1', undefined]) {
  const scripts = [];
  const analytics = vm.createContext({
    loadRuntimeConfig: async () => ({ kakaoJsKey: '', ga4MeasurementId }),
    window: { location: { pathname: '/pages/search.html', origin: 'https://example.test' } },
    document: { createElement: () => ({}), head: { append: (script) => scripts.push(script) } },
  });
  assert.equal(await vm.runInContext(`${strip(analyticsSource)}\nanalyticsReady`, analytics), false);
  assert.equal(scripts.length, 0);
  assert.equal(analytics.window.gtag, undefined);
  assert.equal(analytics.window.dataLayer, undefined);
}
// 설정 조회가 실패해도 헤더(analytics import)를 깨뜨리지 않는다.
{
  const analytics = vm.createContext({
    loadRuntimeConfig: async () => { throw new Error('unexpected'); },
    window: { location: { pathname: '/pages/search.html', origin: 'https://example.test' } },
    document: { createElement: () => ({}), head: { append() { throw new Error('호출되면 안 됨'); } } },
  });
  assert.equal(await vm.runInContext(`${strip(analyticsSource)}\nanalyticsReady`, analytics), false);
}

// 8. 지도 키가 비면 SDK를 부르지 않고 좌표 미리보기. 키가 있으면 그 키로 SDK를 요청한다.
async function renderMap(kakaoJsKey) {
  const scripts = [];
  const context = vm.createContext({
    KAKAO_JS_KEY: '', window: {},
    document: { createElement: () => ({ remove() {} }), head: { appendChild: (script) => scripts.push(script) } },
    setTimeout: () => 1, clearTimeout() {},
    loadRuntimeConfig: async () => ({ kakaoJsKey, ga4MeasurementId: '' }),
    ResizeObserver: class { observe() {} disconnect() {} },
  });
  vm.runInContext(strip(utilsSource), context);
  vm.runInContext(strip(mapSource), context);
  const container = {
    clientWidth: 320, clientHeight: 330, innerHTML: '',
    replaceChildren() { this.innerHTML = ''; },
    querySelector() { return { setAttribute() {}, innerHTML: '' }; },
  };
  const route = { path: [{ lat: 35, lng: 129 }, { lat: 35.1, lng: 129.1 }] };
  const rendering = context.renderRouteMap(container, { route, from: '출발', to: '도착', color: '#2563EB' });
  return { scripts, container, rendering };
}
{
  const { scripts, container, rendering } = await renderMap('');
  await rendering;
  assert.equal(scripts.length, 0);
  assert(container.innerHTML.includes('지도 키가 없어 좌표로 표시해요.'));
}
{
  const { scripts } = await renderMap('server-js-key');
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(scripts.length, 1);
  assert.equal(scripts[0].src, 'https://dapi.kakao.com/v2/maps/sdk.js?appkey=server-js-key&autoload=false');
}
console.log('PASS: 측정 ID가 비면 gtag 미로드·설정 실패에도 헤더 유지, 지도 키가 비면 SDK 미로드(좌표 미리보기)');
