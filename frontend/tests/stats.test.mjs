// node frontend/tests/stats.test.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const read = path => readFile(new URL(path, import.meta.url), 'utf8');
const strip = source => source.replace(/^import .*;$/mg, '').replace(/export /g, '');
const config = await read('../js/config.js');
assert.match(config, /USE_MOCK_STATS = false;/);
assert.match(config, /USE_MOCK = false;/);

const dailyVisitors = Array.from({ length: 7 }, (_, i) => ({ date: `2026-11-${13 + i}`, count: 1200 + i }));
const report = {
  visitorStatus: 'ok', searchStatus: 'ok',
  from: '2026-11-13', to: '2026-11-19', dailyVisitors, todayVisitors: 1206, periodVisitors: 2200, periodChangePct: -2, dayChangePct: 0,
  totalVisitors: 5300, monthVisitors: 4000, totalSearches: 9000,
  popularOrigins: [], popularDestinations: [{ name: '긴<장소>' + '이름'.repeat(30), count: 1010 }],
};
const calls = [];
const nodes = new Map();
const context = vm.createContext({
  URLSearchParams, USE_MOCK: false, USE_MOCK_STATS: false, BASE_URL: '/api',
  fetch: async url => { calls.push(url); return { ok: true, json: async () => report }; },
  document: { getElementById: id => { if (!nodes.has(id)) nodes.set(id, { value: "7", setAttribute() {}, removeAttribute() {}, addEventListener(event, listener) { this[event] = listener; } }); return nodes.get(id); } },
  requirePageAccess: () => ({ then() {} }),
  renderIcons() {},
});
for (const module of ['utils.js', 'api.js', 'components/charts.js', 'pages/stats.js']) {
  vm.runInContext(strip(await read(`../js/${module}`)), context);
}

await context.init();
assert.deepEqual(calls, ['/api/stats?days=7']);
assert.equal(nodes.get('stat-today').textContent, '1,206명');
assert.equal(nodes.get('stat-total').textContent, '5,300명');
assert.equal(nodes.get('period-total').textContent, '2,200명');
assert.equal(nodes.get('period-change').textContent, '직전 7일 대비 -2%');
assert.equal(nodes.get('stat-searches-note').textContent, '방문자당 평균 데이터 없음');
assert.equal((nodes.get('visitor-graph').innerHTML.match(/class="visitor-point"/g) || []).length, 7);
assert.match(nodes.get('ranking-destinations').innerHTML, /긴&#60;장소&#62;.*1,010회/s);
assert.match(nodes.get('ranking-origins').innerHTML, /인기 출발지 TOP 5.*데이터 없음/s);

context.render({ ...report, dailyVisitors: dailyVisitors.map((day, i) => i === 2 ? { ...day, count: null } : day) });
assert.equal((nodes.get('visitor-graph').innerHTML.match(/class="visitor-line"/g) || []).length, 2);
assert.match(nodes.get('visitor-graph').innerHTML, /일부 날짜 데이터 없음/);
context.render({ visitorStatus: 'unavailable', searchStatus: 'ok', totalSearches: 0, popularDestinations: report.popularDestinations });
assert.equal(nodes.get('stat-today').textContent, '통계를 불러올 수 없음');
assert.equal(nodes.get('stat-searches').textContent, '데이터 없음');
assert.match(nodes.get('ranking-destinations').innerHTML, /1,010회/);
context.render({ ...report, searchStatus: 'unavailable', totalSearches: null, popularDestinations: null });
assert.equal(nodes.get('stat-today').textContent, '1,206명');
assert.match(nodes.get('ranking-destinations').innerHTML, /통계를 불러올 수 없음/);
context.render(null);
assert.equal(nodes.get('stat-today').textContent, '데이터 없음');

let finishRequest;
context.fetch = url => {
  calls.push(url);
  return new Promise(resolve => { finishRequest = resolve; });
};
const pending = context.loadPeriod(7);
assert.equal(nodes.get('stat-today').textContent, '불러오는 중');
assert.match(nodes.get('ranking-destinations').innerHTML, /불러오는 중/);
finishRequest({ ok: false, status: 503, json: async () => ({ message: 'unavailable' }) });
await pending;
assert.deepEqual(calls, ['/api/stats?days=7', '/api/stats?days=7']);
assert.match(nodes.get('ranking-destinations').innerHTML, /통계를 불러올 수 없음/);

const requests = new Map();
context.fetch = url => new Promise(resolve => requests.set(url, resolve));
const select = nodes.get('stats-period');
select.value = '1';
const one = select.change();
assert.equal(nodes.get('stats-period-label').textContent, '오늘');
assert.match(nodes.get('ranking-origins').innerHTML, /오늘.*불러오는 중/s);
select.value = '31';
const month = select.change();
assert.equal(nodes.get('stats-period-label').textContent, '최근 31일');
assert.equal(nodes.get('period-total').textContent, '불러오는 중');
const days31 = Array.from({ length: 31 }, (_, index) => ({ date: context.daysFrom('2026-11-19', index - 30), count: index }));
requests.get('/api/stats?days=31')({ ok: true, json: async () => ({
  ...report, from: days31[0].date, dailyVisitors: days31, periodVisitors: 111, periodChangePct: null,
}) });
await month;
assert.equal(nodes.get('period-total').textContent, '111명');
assert.equal(nodes.get('period-change').textContent, '—');
assert.equal(nodes.get('visitor-period').textContent, '2026-10-20 ~ 2026-11-19 (한국 시간)');
const graph31 = nodes.get('visitor-graph').innerHTML;
assert.equal((graph31.match(/class="visitor-point"/g) || []).length, 31);
assert.equal((graph31.match(/class="visitor-labels">(.+?)<\/div>/)?.[1].match(/<span>/g) || []).length, 7);
assert.match(nodes.get('ranking-destinations').innerHTML, /최근 31일/);

const oneReport = { ...report, from: report.to, dailyVisitors: dailyVisitors.slice(-1), periodVisitors: 1206 };
requests.get('/api/stats?days=1')({ ok: true, json: async () => oneReport });
await one;
assert.equal(nodes.get('period-total').textContent, '111명');
assert.equal(nodes.get('visitor-graph').innerHTML, graph31);

select.value = '1';
const oneAgain = select.change();
requests.get('/api/stats?days=1')({ ok: true, json: async () => oneReport });
await oneAgain;
assert.equal(nodes.get('stat-today').textContent, '1,206명');
assert.equal(nodes.get('stat-total').textContent, '5,300명');
assert.equal(nodes.get('period-total').textContent, '1,206명');
assert.match(nodes.get('visitor-graph').innerHTML, /single-date/);
assert.equal((nodes.get('visitor-graph').innerHTML.match(/class="visitor-point"/g) || []).length, 1);
assert.equal(nodes.get('stat-popular-note').textContent, '오늘 1,010회 검색');

// 수집 설정을 켜도 공유 링크와 콜백 값이 GA4 이벤트에 들어가지 않는다.
const scripts = [];
const analytics = vm.createContext({
  loadRuntimeConfig: async () => ({ kakaoJsKey: '', ga4MeasurementId: 'G-TEST' }),
  window: { location: {
    pathname: '/pages/result.html', origin: 'https://example.test',
    href: 'https://example.test/pages/result.html?from=private&lat=123#secret',
  } },
  document: {
    referrer: 'https://example.test/?email=private',
    createElement: () => ({}),
    head: { append: script => scripts.push(script) },
  },
});
const analyticsSource = strip(await read('../js/analytics.js'));
// 두 번 실행해도(모듈 중복 평가 대비) gtag는 한 번만 시작한다.
assert.equal(await vm.runInContext(`${analyticsSource}\nanalyticsReady`, analytics), true);
assert.equal(await vm.runInContext(`{ ${analyticsSource}\nanalyticsReady }`, analytics), false);
assert.equal(scripts.length, 1);
assert.equal(scripts[0].src, 'https://www.googletagmanager.com/gtag/js?id=G-TEST');
assert.equal(scripts[0].referrerPolicy, 'no-referrer');
const queue = Array.from(analytics.window.dataLayer, call => Array.from(call));
assert.equal(queue[1][2].send_page_view, false);
assert.deepEqual(queue.filter(call => call[0] === 'event').map(call => call[1]), ['page_view']);
assert.match(JSON.stringify(queue), /https:\/\/example.test\/pages\/result.html/);
assert.doesNotMatch(JSON.stringify(queue), /private|secret|lat=|user_id/);
console.log('PASS: 사이트 통계 API, 로딩/정상/빈 응답/부분 장애, 단일 방문 이벤트');
