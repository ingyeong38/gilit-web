// node frontend/tests/ai-summary.test.mjs — AI 경로 요약 (js/components/aiSummary.js, api.js getRouteSummary, result.js 연결)
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const strip = (source) => source.replace(/^import[\s\S]*?from ["'][^"']+["'];/mg, '').replace(/export /g, '');
const RULE_NOTICE = 'AI 요약을 불러오지 못해 기본 비교를 표시합니다';
const ROUTE_COLORS = ['#2563EB', '#16A36A', '#F59E0B', '#7C3AED'];

// 실제 utils.js(escapeHtml, formatRouteLabel, timeOf, ROUTE_COLORS)를 같은 컨텍스트에 먼저 올린다.
const ui = vm.createContext({ KAKAO_JS_KEY: '', icon: () => '<svg></svg>' });
vm.runInContext(strip(await read('../js/utils.js')), ui);
vm.runInContext(strip(await read('../js/components/aiSummary.js')), ui);

// --- 게이지: 요청 여유 대비 확보율 ---
{
  const full = ui.gaugeModel(12, 10);
  assert.equal(full.percent, 100); assert.equal(full.tone, 'ok'); assert.equal(full.label, '여유 12분'); assert.equal(full.detail, '요청 10분 확보');
  assert.equal(ui.gaugeModel(10, 10).percent, 100); // 같으면 100%
  const part = ui.gaugeModel(4, 10);
  assert.equal(part.percent, 40); assert.equal(part.tone, 'short'); assert.equal(part.label, '여유 4분'); assert.equal(part.detail, '요청 10분보다 6분 부족');
  assert.equal(ui.gaugeModel(0, 15).percent, 0); assert.equal(ui.gaugeModel(0, 15).detail, '요청 15분보다 15분 부족');
  const late = ui.gaugeModel(-7, 10);
  assert.equal(late.percent, 0); assert.equal(late.ratio, 0); assert.equal(late.tone, 'late'); assert.equal(late.late, true);
  assert.equal(late.label, '여유 없음'); assert.equal(late.detail, '7분 늦게 도착');
  assert.deepEqual([late.startLabel, late.endLabel], ['0', '요청 10분']); // 눈금: 0과 요청값
  const noBuffer = ui.gaugeModel(5, 0); // 요청 여유 0분: 제시간 도착이면 100%
  assert.equal(noBuffer.percent, 100); assert.equal(noBuffer.endLabel, '제시간'); assert.equal(noBuffer.detail, '도착 희망 시각 전 도착');
  assert.equal(ui.gaugeModel(-1, 0).percent, 0);
  assert.equal(ui.gaugeModel(Number.NaN, 10).slack, 0);
  console.log('PASS: 게이지 확보율(100%·부분·음수 0%+late), 눈금 0·요청값, 하단 문구');
}

// --- 비교표 행: 막대 폭, 최단 대비 차이, 통행료 ---
const comparison = [
  { routeId: 'recommend', label: '추천', durationMin: 38, slackMin: 10, toll: 1500, departTime: '2026-11-21T08:12:00+09:00' },
  { routeId: 'free', label: '무료도로', durationMin: 47, slackMin: -2, toll: 0, departTime: '2026-11-21T08:02:00+09:00' },
  { routeId: 'time', label: '최단시간', durationMin: 35, slackMin: 3, toll: null, departTime: '2026-11-21T08:40:00+09:00' },
];
{
  const rows = ui.barModel(comparison, { selectedId: 'free', recommendedId: 'recommend' });
  assert.deepEqual(rows.map((row) => row.width), [80.9, 100, 74.5]); // duration/최대값
  assert.deepEqual(rows.map((row) => row.diffMin), [3, 12, 0]);
  assert.deepEqual(rows.map((row) => row.diffText), ['최단 대비 +3분', '최단 대비 +12분', '최단']);
  assert.deepEqual(rows.map((row) => row.tollText), ['1,500원', '무료', '미제공']);
  assert.deepEqual(rows.map((row) => row.selected), [false, true, false]);
  assert.deepEqual(rows.map((row) => row.recommended), [true, false, false]);
  assert.deepEqual(rows.map((row) => row.fastest), [false, false, true]);
  assert.deepEqual(rows.map((row) => row.color), ROUTE_COLORS.slice(0, 3));
  const same = ui.barModel([{ routeId: 'a', durationMin: 30 }, { routeId: 'b', durationMin: 30 }]);
  assert.deepEqual(same.map((row) => row.diffText), ['최단', '최단']); // 동률은 모두 최단
  assert.equal(ui.barModel([{ routeId: 'a', durationMin: 1 }, { routeId: 'b', durationMin: 100 }])[0].width, 4); // 최소 폭
  assert.equal(ui.barModel([{ routeId: 'x', durationMin: -1 }, { durationMin: 3 }, null]).length, 0);
  assert.equal(ui.tollText(1234567), '1,234,567원');
  console.log('PASS: 비교표(막대 폭, 최단 대비 +N분·최단, 통행료 무료·원·미제공, 선택·추천)');
}

// --- 키워드 칩: 2개까지, headline과 겹치면 제외 ---
{
  assert.deepEqual([...ui.cleanKeywords([' 정체 회피 ', '', '정체 회피', 3, '가'.repeat(13), '빠른 도착', '여유 확보'])],
    ['정체 회피', '빠른 도착']);
  assert.deepEqual([...ui.cleanKeywords(['정체 회피', '무료 구간', '여유 확보'], { headline: '정체가 적은 길이에요' })],
    ['무료 구간', '여유 확보']); // "정체"가 headline에 있어 제외
  assert.deepEqual([...ui.cleanKeywords(['통행료 없음', '빠른길'], { headline: '빠르게 가요' })], ['통행료 없음', '빠른길']); // 겹치는 단어가 없으면 남긴다
  assert.deepEqual([...ui.cleanKeywords(['빠른 도착'], { headline: '빠른도착 경로' })], []); // 공백을 무시하고 겹침 확인
  assert.deepEqual([...ui.cleanKeywords(['가 나'], { headline: '가 나 다' })], ['가 나']); // 한 글자 단어는 겹침으로 보지 않는다
  assert.deepEqual([...ui.cleanKeywords('정체')], []);
  console.log('PASS: 키워드 칩(2개 제한, 중복·12자 초과·headline 겹침 제외)');
}

// --- 서버 응답 정규화와 라벨 통일 ---
const routes = [
  { id: 'recommend', label: '추천', name: '남해고속도로 경유', options: ['recommend', 'time'], departTime: '2026-11-21T08:12:00+09:00', arriveTime: '2026-11-21T08:50:00+09:00',
    durationMin: 38, distanceKm: 31.2, toll: 1500, path: [{ lat: 35.1, lng: 129 }], aiSummary: { title: 'x', text: 'y' } },
  { id: 'free', label: '무료도로', name: '국도 경유', options: ['free'], departTime: '2026-11-21T08:02:00+09:00', arriveTime: '2026-11-21T09:02:00+09:00',
    durationMin: 60, distanceKm: 29.8, toll: 0, path: [] },
];
const server = { source: 'gemini', recommendedRouteId: 'recommend', recommendedDepartTime: '2026-11-21T08:12:00+09:00',
  headline: '<b>빠른</b> 길이에요', keywords: ['정체 회피', '<script>', '셋째'], slackMin: 10, bufferMin: 10,
  comparison: [{ routeId: 'recommend', label: '추천', durationMin: 38, slackMin: 10, toll: 1500, departTime: '2026-11-21T08:12:00+09:00' },
    { routeId: 'free', label: '무료도로', durationMin: 60, slackMin: -2, toll: 0, departTime: '2026-11-21T08:02:00+09:00' }] };
{
  const model = ui.normalizeSummary(server, routes);
  assert.equal(model.source, 'gemini'); assert.equal(model.local, false);
  // 라벨은 경로 카드의 formatRouteLabel과 같다 (합쳐진 카드는 "추천 · 최단시간")
  assert.equal(model.recommendedLabel, '추천 · 최단시간');
  assert.deepEqual(model.comparison.map((row) => row.label), ['추천 · 최단시간', '무료도로']);
  assert.deepEqual([...model.keywords], ['정체 회피', '<script>']);
  // 카드에 label·options가 없으면 서버 label
  const bare = ui.normalizeSummary(server, routes.map(({ id, departTime }) => ({ id, departTime })));
  assert.deepEqual(bare.comparison.map((row) => row.label), ['추천', '무료도로']);
  const rule = ui.normalizeSummary({ ...server, source: 'rule', keywords: ['무시'] }, routes);
  assert.deepEqual([...rule.keywords], []);
  for (const broken of [null, [], { ...server, source: 'ai' }, { ...server, recommendedRouteId: 'time' },
    { ...server, recommendedDepartTime: '08:12' }, { ...server, slackMin: '10' }, { ...server, comparison: [] },
    { ...server, comparison: [{ routeId: 'distance', durationMin: 3, slackMin: 1 }] }]) {
    assert.throws(() => ui.normalizeSummary(broken, routes));
  }
  assert.equal(ui.conclusionLabel('추천'), '추천 경로');
  assert.equal(ui.conclusionLabel('추천 · 최단시간'), '추천 경로');
  assert.equal(ui.conclusionLabel('무료도로'), '추천 경로 · 무료도로');
  console.log('PASS: 서버 응답 정규화, 라벨 통일(카드 formatRouteLabel, 없으면 서버 label), 결론 라벨 중복 제거');
}

// --- 로컬 대체 요약 ---
{
  const local = ui.localSummary({ arrive: '2026-11-21T09:00:00+09:00', buffer: '10' }, routes);
  assert.equal(local.source, 'rule'); assert.equal(local.local, true);
  assert.equal(local.recommendedRouteId, 'recommend'); assert.equal(local.slackMin, 10); assert.equal(local.bufferMin, 10);
  assert.equal(local.recommendedLabel, '추천 · 최단시간');
  assert.deepEqual(local.comparison.map((row) => row.slackMin), [10, -2]);
  assert.deepEqual([...local.keywords], []);
  const noRecommend = ui.localSummary({ arrive: '2026-11-21T09:00:00+09:00', buffer: 0 }, [
    { id: 'free', label: '무료도로', departTime: '2026-11-21T08:02:00+09:00', arriveTime: '2026-11-21T08:49:30+09:00', durationMin: 47 },
    { id: 'time', label: '최단시간', departTime: '2026-11-21T08:15:00+09:00', arriveTime: '2026-11-21T08:53:00+09:00', durationMin: 38 },
  ]);
  assert.equal(noRecommend.recommendedRouteId, 'time');
  assert.equal(noRecommend.comparison[0].slackMin, 10); // 10분 30초 → 내림
  assert.equal(ui.localSummary({ arrive: 'x' }, routes), null);
  assert.equal(ui.localSummary({ arrive: '2026-11-21T09:00:00+09:00' }, []), null);
  console.log('PASS: 로컬 대체 요약(서버 rule과 같은 추천 규칙, 여유 내림, 음수 여유, 카드 라벨)');
}

// --- 렌더 ---
class Row {
  constructor(id) { this.dataset = { routeId: id }; this.attrs = {}; this.classes = new Set(); this.classList = { toggle: (name, on) => (on ? this.classes.add(name) : this.classes.delete(name)) }; }
  setAttribute(name, value) { this.attrs[name] = value; }
}
function container() {
  const node = { attrs: {}, innerHTML: '', rows: [] };
  node.setAttribute = (name, value) => { node.attrs[name] = value; };
  node.querySelectorAll = () => node.rows;
  return node;
}
{
  const node = container();
  ui.renderAiSummaryLoading(node);
  assert.equal(node.attrs['aria-busy'], 'true'); assert.match(node.innerHTML, /role="status"/);

  ui.renderAiSummary(node, ui.normalizeSummary(server, routes), { selectedId: 'free' });
  const html = node.innerHTML;
  assert.equal(node.attrs['aria-busy'], 'false');
  assert(!html.includes('<b>빠른') && html.includes('&#60;b&#62;빠른')); // headline 이스케이프 (본문·title 모두)
  assert(!html.includes('<script>') && html.includes('&#60;script&#62;'));
  assert(!html.includes('셋째')); // 칩은 2개까지
  // 결론 카드 순서: 라벨 → 권장 출발 → headline
  assert.match(html, /<small class="ai-conclusion-label">추천 경로<\/small>\s*<div class="ai-depart"><span>권장 출발<\/span><time datetime="2026-11-21T08:12:00\+09:00">08:12<\/time><\/div>\s*<p class="ai-headline"/);
  assert(!html.includes('추천 경로 · 추천'));
  // 게이지: 확보율 100%, 눈금 0·요청값, 중앙·하단 문구
  assert.match(html, /stroke-dasharray="100 100"/);
  assert.match(html, />0<\/text>/); assert.match(html, />요청 10분<\/text>/);
  assert.match(html, /<b class="ai-gauge-value">여유 10분<\/b>/); assert.match(html, /<figcaption>요청 10분 확보<\/figcaption>/);
  // 비교표: 경로명 | 막대 | N분 | 최단 대비 | 통행료. 행의 "여유 N분"·"늦음"은 없다
  assert.match(html, /class="horizontal-bars" role="table"/); assert.match(html, /class="bar-track"/);
  assert.match(html, /class="horizontal-row ai-row is-selected" role="row" data-route-id="free" aria-current="true"/);
  assert.match(html, /<b>추천 · 최단시간<\/b><em class="bar-badge">추천<\/em>/);
  assert.match(html, /<b class="ai-row-duration" role="cell">38분<\/b>/);
  assert.match(html, /ai-row-diff is-fastest" role="cell">최단</); assert.match(html, />최단 대비 \+22분</);
  assert.match(html, />1,500원</); assert.match(html, />무료</);
  const table = html.slice(html.indexOf('class="horizontal-bars"'));
  assert(!/여유 \d+분/.test(table) && !table.includes('늦음'));
  assert(!html.includes(RULE_NOTICE)); assert.match(html, /AI 경로 추천 요약/);

  ui.renderAiSummary(node, ui.localSummary({ arrive: '2026-11-21T08:40:00+09:00', buffer: 10 }, routes));
  assert(node.innerHTML.includes(RULE_NOTICE)); assert.match(node.innerHTML, /role="note"/);
  assert.match(node.innerHTML, /tone-late/); assert.match(node.innerHTML, /<figcaption>10분 늦게 도착<\/figcaption>/);
  assert.match(node.innerHTML, /여유 없음/);
  assert(!node.innerHTML.includes('class="gauge-value"')); // 0%면 값 호를 그리지 않는다
  assert(!node.innerHTML.includes('ai-keywords'));
  assert.match(node.innerHTML, /class="horizontal-bars"/); // rule도 같은 시각화

  ui.renderAiSummary(node, null);
  assert.match(node.innerHTML, /경로 요약을 표시할 수 없습니다/);

  node.rows = [new Row('recommend'), new Row('free')];
  ui.highlightSummaryRoute(node, 'recommend');
  assert(node.rows[0].classes.has('is-selected')); assert(!node.rows[1].classes.has('is-selected'));
  assert.equal(node.rows[0].attrs['aria-current'], 'true'); assert.equal(node.rows[1].attrs['aria-current'], 'false');
  console.log('PASS: 렌더(결론 위계, 이스케이프, 확보율 게이지·눈금, 비교표 열, 선택 강조, rule 안내, 음수 여유)');
}

// --- CSS: 375px 2줄 접기, 트랙 약 45% ---
{
  const css = await read('../css/pages/result.css');
  assert.match(css, /\.ai-row \{ display: grid; grid-template-columns: minmax\(0, 1fr\) 45% /);
  assert.match(css, /grid-template-areas: "name name duration" "bar diff toll"/);
  assert.match(css, /\.ai-headline \{[^}]*white-space: nowrap;[^}]*text-overflow: ellipsis;/);
  console.log('PASS: CSS(트랙 45%, 375px 2줄 접기, headline 한 줄)');
}

// --- api.js getRouteSummary ---
{
  const calls = [];
  let reply = { ok: true, status: 200, json: async () => server };
  const timers = [];
  const context = vm.createContext({
    USE_MOCK: false, USE_MOCK_ROUTES: false, USE_MOCK_STATS: true, BASE_URL: '/api', URLSearchParams, AbortController,
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimeout: () => {},
    fetch: async (url, options) => { calls.push({ url, options }); return typeof reply === 'function' ? reply(options) : reply; },
    getUser: () => null, location: { hostname: 'localhost' },
  });
  vm.runInContext(strip(await read('../js/api.js')), context);
  const search = { from: '김해시청', to: '동의대학교', arrive: '2026-11-21T09:00:00+09:00', buffer: 10, fromLat: '35.2', fromLng: '128.8', toLat: '35.1', toLng: '129.0', toAddress: '부산' };

  const result = await context.getRouteSummary(search, routes);
  assert.equal(result.source, 'gemini');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/routes/summary');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.headers['Content-Type'], 'application/json');
  const sent = JSON.parse(calls[0].options.body);
  assert.deepEqual(Object.keys(sent).sort(), ['arrive', 'buffer', 'routes']);
  assert.equal(sent.arrive, search.arrive); assert.equal(sent.buffer, 10);
  assert.deepEqual(sent.routes.map((route) => Object.keys(route)), Array(2).fill(['id', 'departTime', 'arriveTime', 'durationMin', 'distanceKm', 'toll']));
  for (const value of ['김해시청', '동의대학교', '35.2', '129.0', '부산', '남해고속도로', 'lat', 'path', 'aiSummary', 'options']) {
    assert(!calls[0].options.body.includes(value), `요청에 ${value}가 없어야 합니다`);
  }
  assert.equal(timers.at(-1).ms, 10000);
  assert(calls[0].options.signal instanceof AbortSignal);

  // 카드 4개까지, id·departTime 없는 카드는 뺀다. buffer는 숫자로.
  const many = [...routes, { id: 'time', departTime: 'x' }, { id: 'distance', departTime: 'y' }, { id: 'extra', departTime: 'z' }, { name: 'id 없음' }];
  const body = context.summaryRequestBody({ arrive: 'a', buffer: '5' }, many);
  assert.equal(body.routes.length, 4); assert.equal(body.buffer, 5);
  assert.equal(context.summaryRequestBody({ arrive: 'a' }, [{ id: 'recommend', departTime: 't' }]).routes[0].toll, null);

  // 10초 뒤 abort
  reply = (options) => new Promise((resolve, reject) => { options.signal.addEventListener('abort', () => reject(new Error('aborted'))); });
  const late = context.getRouteSummary(search, routes);
  timers.at(-1).fn();
  await assert.rejects(late, /aborted/);

  // 400(code 포함)과 5xx는 ApiError로 던진다 → 화면은 로컬 대체 요약
  reply = { ok: false, status: 400, json: async () => ({ message: '출발시각이 이미 지난 경로가 있습니다. 경로를 다시 검색해 주세요.', code: 'depart_passed' }) };
  await assert.rejects(context.getRouteSummary(search, routes), (error) => error.status === 400 && error.code === 'depart_passed');
  reply = { ok: false, status: 502, json: async () => { throw new Error('not json'); } };
  await assert.rejects(context.getRouteSummary(search, routes), (error) => error.status === 502);
  assert(calls.every((call) => !call.url.includes('/mock/')));
  console.log('PASS: getRouteSummary가 카드 6개 필드·arrive·buffer만 POST, 10초 abort, 400(code)·5xx 오류 전달');

  // 목업 모드: routeSummary.json을 읽고 출발시각은 같은 카드 값으로 맞춘다
  const mockCalls = [];
  const mock = vm.createContext({ ...context, USE_MOCK_ROUTES: true,
    fetch: async (url) => { mockCalls.push(url); return { ok: true, status: 200, json: async () => JSON.parse(await read(`..${url}`)) }; } });
  vm.runInContext(strip(await read('../js/api.js')), mock);
  const mockRoutes = JSON.parse(await read('../js/mock/routes.json')).map((route) => ({ ...route, departTime: route.departTime.replace('08:', '09:') }));
  const mocked = await mock.getRouteSummary({ arrive: '2026-11-02T10:00:00+09:00', buffer: 10 }, mockRoutes);
  assert.deepEqual(mockCalls, ['/js/mock/routeSummary.json']);
  assert.equal(mocked.recommendedDepartTime, mockRoutes[0].departTime);
  const mockModel = ui.normalizeSummary(mocked, mockRoutes); // 목업 id가 routes.json 카드와 짝지어진다
  assert.equal(mockModel.source, 'gemini'); assert.equal(mockModel.comparison.length, mockRoutes.length);
  console.log('PASS: 목업 요약(routeSummary.json)이 목업 카드와 짝지어짐');
}

// --- result.js 연결 (소스 확인) ---
{
  const source = await read('../js/pages/result.js');
  const html = await read('../pages/result.html');
  assert.match(source, /from "\/js\/api\.js";/); // api.js import에는 ?v=를 붙이지 않는다
  assert.match(source, /from "\/js\/auth\.js";/);
  const version = html.match(/result\.js\?v=([\w-]+)"/)[1];
  assert.equal(html.match(/result\.css\?v=([\w-]+)"/)[1], version);
  assert(source.includes(`/js/components/aiSummary.js?v=${version}"`)); // 페이지 전용 모듈은 같은 버전
  assert.match(html, /id="ai-summary"[^>]*aria-busy="true"/);
  assert.match(html, /<p class="ai-status" role="status">/);
  assert(!/ai-title|ai-text|aiSummary\.(title|text)/.test(source + html)); // 고정 문구는 더 쓰지 않는다
  assert.equal((source.match(/getRouteSummary\(/g) || []).length, 1); // 검색 하나에 한 번 (카드 선택 때 재호출 없음)
  assert.match(source, /if \(token !== summaryToken\) return;/);
  console.log('PASS: result.js 연결(요약 1회 요청, 요청 토큰, 고정 문구 제거, 버전 일치)');
}

// --- result.js 요약 흐름 (모의 DOM) ---
{
  const node = container();
  let respond;
  const page = vm.createContext({
    getRouteSummary: () => new Promise((resolve, reject) => { respond = { resolve, reject }; }),
    normalizeSummary: ui.normalizeSummary, localSummary: ui.localSummary, renderAiSummary: ui.renderAiSummary,
    renderAiSummaryLoading: ui.renderAiSummaryLoading, highlightSummaryRoute: ui.highlightSummaryRoute,
    document: { getElementById: (id) => (id === 'ai-summary' ? node : null), querySelector: () => null },
  });
  vm.runInContext(strip(await read('../js/pages/result.js')).replace(/\ninit\(\);\s*$/, ''), page);
  const search = { buffer: 10 };
  const arrive = '2026-11-21T09:00:00+09:00';

  // 실패하면 로컬 대체 요약 + 안내
  const first = page.loadSummary(search, arrive, routes);
  assert.equal(node.attrs['aria-busy'], 'true');
  respond.reject(Object.assign(new Error('network'), { status: undefined }));
  await first;
  assert(node.innerHTML.includes(RULE_NOTICE)); assert.equal(node.attrs['aria-busy'], 'false');

  // 이전 요청이 늦게 오면 버린다 (요청 토큰)
  const older = page.loadSummary(search, arrive, routes); const olderRespond = respond;
  const newer = page.loadSummary(search, arrive, routes); const newerRespond = respond;
  newerRespond.resolve(server); await newer;
  const shown = node.innerHTML;
  olderRespond.resolve({ ...server, headline: '이전 검색 결과' }); await older;
  assert.equal(node.innerHTML, shown); assert(!node.innerHTML.includes('이전 검색 결과'));

  // 형식이 어긋난 200 응답도 로컬 대체
  const odd = page.loadSummary(search, arrive, routes); respond.resolve({ source: 'gemini' }); await odd;
  assert(node.innerHTML.includes(RULE_NOTICE));
  console.log('PASS: 결과 화면 요약 흐름(실패 대체, 늦은 이전 응답 무시, 형식 오류 대체)');
}
