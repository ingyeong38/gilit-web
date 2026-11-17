// node frontend/tests/stats.test.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const read = path => readFile(new URL(path, import.meta.url), 'utf8');
const strip = s => s.replace(/^import .*;$/mg, '').replace(/export /g, '');
const config = await read('../js/config.js');
assert.match(config, /USE_MOCK = false;/);
assert.match(config, /USE_MOCK_STATS = true;/);
const fixture = JSON.parse(await read('../js/mock/stats.json'));
const calls = [];
const context = vm.createContext({ URLSearchParams, USE_MOCK: false, USE_MOCK_STATS: true, BASE_URL: '/api',
  fetch: async url => { calls.push(url); return { ok: true, status: 200, json: async () => structuredClone(fixture) }; },
});
vm.runInContext(strip(await read('../js/utils.js')), context);
vm.runInContext(strip(await read('../js/api.js')), context);
const stats = await context.getStats();
assert.deepEqual(calls, ['/js/mock/stats.json']);
assert.equal(stats.dailyVisitors.at(-1).date, context.toDateString());
assert.deepEqual(Array.from(stats.dailyVisitors, d => d.count), fixture.dailyVisitors.map(d => d.count));
assert.equal(stats.dailyVisitors[0].date, context.daysFrom(context.toDateString(), -6));
assert.deepEqual(JSON.parse(JSON.stringify({ ...stats, dailyVisitors: fixture.dailyVisitors })), fixture);
// 기존 페이지와 통계 차트 함수를 모의 DOM에서 함께 렌더링한다.
const nodes = new Map();
context.document = { getElementById: id => { if (!nodes.has(id)) nodes.set(id, {}); return nodes.get(id); } };
context.requirePageAccess = () => ({ then() {} });
vm.runInContext(strip(await read('../js/components/charts.js')), context);
vm.runInContext(strip(await read('../js/pages/stats.js')), context);
context.render(stats);
assert.equal(nodes.get('stat-today').textContent, '338명');
assert.equal(nodes.get('stat-total').textContent, '48,290명');
assert.equal(nodes.get('stat-searches').textContent, '126,842회');
assert.match(nodes.get('visitor-graph').innerHTML, /visitor-line/);
assert.equal((nodes.get('visitor-graph').innerHTML.match(/class="visitor-point"/g) || []).length, 7);
assert.match(nodes.get('ranking-destinations').innerHTML, /동의대학교/);
context.USE_MOCK_STATS = false;
const live = await context.getStats();
assert.equal(calls.at(-1), '/api/stats');
assert.deepEqual(live, fixture);
context.fetch = async url => { calls.push(url); return { ok: false, status: 503, json: async () => ({ message: 'unavailable' }) }; };
const before = calls.length;
await assert.rejects(context.getStats(), /unavailable/);
assert.deepEqual(calls.slice(before), ['/api/stats']);
console.log('PASS: 통계 전용 설정·기존 JSON·날짜 보정·숫자/SVG 렌더링·실제 API 전환·실패 시 Mock 대체 없음');
