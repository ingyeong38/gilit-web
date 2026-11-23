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
  dailyVisitors, todayVisitors: 1206, weekVisitors: 2200, weekChangePct: -2, dayChangePct: 0,
  totalVisitors: 5300, monthVisitors: 4000, totalSearches: 9000,
  popularOrigins: [], popularDestinations: [{ name: '긴<장소>' + '이름'.repeat(30), count: 1010 }],
};
const calls = [];
const nodes = new Map();
const context = vm.createContext({
  URLSearchParams, USE_MOCK: false, USE_MOCK_STATS: false, BASE_URL: '/api',
  fetch: async url => { calls.push(url); return { ok: true, json: async () => report }; },
  document: { getElementById: id => { if (!nodes.has(id)) nodes.set(id, { setAttribute() {}, removeAttribute() {} }); return nodes.get(id); } },
  requirePageAccess: () => ({ then() {} }),
  renderIcons() {},
});
for (const module of ['utils.js', 'api.js', 'components/charts.js', 'pages/stats.js']) {
  vm.runInContext(strip(await read(`../js/${module}`)), context);
}

await context.init();
assert.deepEqual(calls, ['/api/stats']);
assert.equal(nodes.get('stat-today').textContent, '1,206명');
assert.equal(nodes.get('stat-total').textContent, '5,300명');
assert.equal(nodes.get('week-total').textContent, '2,200명');
assert.equal(nodes.get('week-change').textContent, '전주 대비 -2%');
assert.equal(nodes.get('stat-searches-note').textContent, '방문자당 평균 데이터 없음');
assert.equal((nodes.get('visitor-graph').innerHTML.match(/class="visitor-point"/g) || []).length, 7);
assert.match(nodes.get('ranking-destinations').innerHTML, /긴&#60;장소&#62;.*1,010회/s);
assert.match(nodes.get('ranking-origins').innerHTML, /인기 출발지 TOP 5.*데이터 없음/s);

context.render({ ...report, dailyVisitors: dailyVisitors.map((day, i) => i === 2 ? { ...day, count: null } : day) });
assert.equal((nodes.get('visitor-graph').innerHTML.match(/class="visitor-line"/g) || []).length, 2);
assert.match(nodes.get('visitor-graph').innerHTML, /일부 날짜 데이터 없음/);
context.render({ visitorStatus: 'unavailable', searchStatus: 'ok', totalSearches: 0, popularDestinations: report.popularDestinations });
assert.equal(nodes.get('stat-today').textContent, '통계를 불러올 수 없음');
assert.equal(nodes.get('stat-searches').textContent, '0회');
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
const pending = context.init();
assert.equal(nodes.get('stat-today').textContent, '불러오는 중');
assert.match(nodes.get('ranking-destinations').innerHTML, /불러오는 중/);
finishRequest({ ok: false, status: 503, json: async () => ({ message: 'unavailable' }) });
await pending;
assert.deepEqual(calls, ['/api/stats', '/api/stats']);
assert.match(nodes.get('ranking-destinations').innerHTML, /통계를 불러올 수 없음/);

// 수집 설정을 켜도 공유 링크와 콜백 값이 GA4 이벤트에 들어가지 않는다.
const scripts = [];
const analytics = vm.createContext({
  GA4_MEASUREMENT_ID: 'G-TEST',
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
vm.runInContext(analyticsSource, analytics);
vm.runInContext(`{ ${analyticsSource} }`, analytics);
assert.equal(scripts.length, 1);
assert.equal(scripts[0].referrerPolicy, 'no-referrer');
const queue = Array.from(analytics.window.dataLayer, call => Array.from(call));
assert.equal(queue[1][2].send_page_view, false);
assert.deepEqual(queue.filter(call => call[0] === 'event').map(call => call[1]), ['page_view']);
assert.match(JSON.stringify(queue), /https:\/\/example.test\/pages\/result.html/);
assert.doesNotMatch(JSON.stringify(queue), /private|secret|lat=|user_id/);
console.log('PASS: 사이트 통계 API, 로딩/정상/빈 응답/부분 장애, 단일 방문 이벤트');
