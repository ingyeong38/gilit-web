// node frontend/tests/share.test.mjs — 경로 공유 링크 (js/share.js, 결과 화면 연결)
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const strip = (source) => source.replace(/^import[\s\S]*?from ["'][^"']+["'];/mg, '').replace(/export /g, '');

// 실제 utils.js → links.js → share.js를 한 컨텍스트에 올린다 (share.js는 links.js 검증을 그대로 쓴다).
const ctx = vm.createContext({ URLSearchParams, KAKAO_JS_KEY: '' });
for (const path of ['../js/utils.js', '../js/links.js', '../js/share.js']) vm.runInContext(strip(await read(path)), ctx);
const ORIGIN = 'https://gilit.example';
const NOW = new Date('2026-11-20T06:00:00+09:00');

const resultQuery = (extra = {}) => new URLSearchParams({
  from: '김해시청', fromLat: '35.2285', fromLng: '128.8894',
  to: '동의대학교', toLat: '35.1441', toLng: '129.0336', toAddress: '부산광역시 부산진구 엄광로 176',
  date: '2026-11-21', time: '09:00', buffer: '10', ...extra,
});

// --- 화이트리스트 ---
{
  const query = resultQuery({ card: 'recommend@2026-11-21T08:12:00+09:00', selected: '2', path: '[1,2]', aiSummary: '요약', utm_source: 'x' });
  const link = ctx.buildShareLink(query, { origin: ORIGIN });
  const url = new URL(link.url);
  assert.equal(url.origin, ORIGIN); assert.equal(url.pathname, '/pages/result.html');
  assert.deepEqual([...url.searchParams.keys()], ['from', 'fromLat', 'fromLng', 'to', 'toLat', 'toLng', 'toAddress', 'date', 'time', 'buffer']);
  assert.equal(link.originOmitted, false);
  for (const value of ['card', 'selected', 'path', 'aiSummary', 'utm_source', '08:12']) assert(!link.url.includes(value));
  // 이름만 있는 장소(좌표 없음)도 공유된다
  const names = ctx.buildShareLink('from=김해시청&to=동의대학교&date=2026-11-21&time=09:00&buffer=0', { origin: ORIGIN });
  assert.deepEqual([...new URL(names.url).searchParams.keys()], ['from', 'to', 'date', 'time', 'buffer']);
  // 좌표는 links.js 형식(소수 7자리, 끝의 0 제거)으로 다시 쓴다
  const precise = ctx.buildShareLink(resultQuery({ fromLat: '35.228500000', fromLng: '128.88940001234' }), { origin: ORIGIN });
  assert.equal(new URL(precise.url).searchParams.get('fromLat'), '35.2285');
  assert.equal(new URL(precise.url).searchParams.get('fromLng'), '128.8894');
  console.log('PASS: 공유 링크 화이트리스트(장소·날짜·시각·여유만, 카드·경로·결과 값 제외)');
}

// --- 인코딩과 links.js 검증 왕복 ---
{
  const tricky = { from: '스타벅스 김해 & 내외점 #1', to: '동의대 100%+ "정문"?a=b', toAddress: '부산 <진구> 엄광로 176' };
  const link = ctx.buildShareLink(resultQuery(tricky), { origin: ORIGIN });
  assert(!/[ "<>#&]/.test(link.url.split('?')[1].replaceAll('&', ''))); // 구분자 & 말고는 그대로 노출되는 특수문자 없음
  const params = new URL(link.url).searchParams;
  const from = ctx.readPlaceParams(params, 'from');
  const to = ctx.readPlaceParams(params, 'to');
  assert.deepEqual({ ...from }, { name: tricky.from, lat: 35.2285, lng: 128.8894 });
  assert.deepEqual({ ...to }, { name: tricky.to, lat: 35.1441, lng: 129.0336, address: tricky.toAddress });
  const conditions = { from: params.get('from'), to: params.get('to'), date: params.get('date'), time: params.get('time'), buffer: params.get('buffer') };
  assert.equal(ctx.validateSearchConditions(conditions, NOW), null); // 결과 화면 검사도 통과
  // 공유 링크를 다시 공유해도 같다
  assert.equal(ctx.buildShareLink(params, { origin: ORIGIN }).url, link.url);
  console.log('PASS: 인코딩(공백·&·#·%·+·따옴표·꺾쇠), links.js·결과 화면 검증 왕복');
}

// --- 공유할 수 없는 조건 ---
{
  for (const extra of [{ fromLng: '' }, { fromLat: '91' }, { toLat: '1e2' }, { to: '' }, { to: '가'.repeat(101) },
    { toAddress: '주소\u0007' }, { date: '2026-13-01' }, { time: '25:00' }, { buffer: '7' }, { to: '김해시청', toLat: '35.2285', toLng: '128.8894' }]) {
    assert.equal(ctx.buildShareLink(resultQuery(extra), { origin: ORIGIN }), null, JSON.stringify(extra));
  }
  const noTo = resultQuery(); noTo.delete('to'); noTo.delete('toLat'); noTo.delete('toLng'); noTo.delete('toAddress');
  assert.equal(ctx.buildShareLink(noTo, { origin: ORIGIN }), null);
  console.log('PASS: 잘못된 파라미터는 공유하지 않음 (links.js 기존 검증)');
}

// --- 현재 위치 출발지 제외 ---
{
  const link = ctx.buildShareLink(resultQuery({ from: '현재 위치', fromLat: '35.1', fromLng: '129.1' }), { origin: ORIGIN });
  const params = new URL(link.url).searchParams;
  assert.equal(link.originOmitted, true);
  assert(!params.has('from') && !params.has('fromLat') && !params.has('fromLng'));
  assert(!link.url.includes('35.1&') && !link.url.includes('129.1&'));
  assert.equal(params.get('to'), '동의대학교');
  assert.equal(ctx.copiedMessage(true), '링크를 복사했어요. 현재 위치는 링크에 담지 않았어요');
  assert.equal(ctx.copiedMessage(false), '링크를 복사했어요');
  assert.equal(ctx.isCurrentLocationOrigin('from=%20현재 위치 '), true);
  assert.equal(ctx.isCurrentLocationOrigin('from=현재 위치 근처'), false);
  console.log('PASS: 현재 위치 출발지는 링크에 담지 않고 안내');
}

// --- 도착 시각 과거 판정과 길찾기 화면 주소 ---
{
  assert.equal(ctx.isArrivalPassed({ date: '2026-11-20', time: '05:59' }, NOW), true);
  assert.equal(ctx.isArrivalPassed({ date: '2026-11-20', time: '06:00' }, NOW), true); // 지금과 같으면 지난 것으로 본다 (검색 화면과 같다)
  assert.equal(ctx.isArrivalPassed({ date: '2026-11-20', time: '06:01' }, NOW), false);
  assert.equal(ctx.isArrivalPassed({ date: '2026-11-19', time: '23:00' }, NOW), true);
  assert.equal(ctx.isArrivalPassed({ date: '2026-11-xx', time: '06:00' }, NOW), false); // 형식 오류는 기존 안내
  assert.equal(ctx.isArrivalPassed({}, NOW), false);

  const url = new URL(ctx.retimeSearchUrl(resultQuery({ date: '2026-11-19', card: 'x' })), ORIGIN);
  assert.equal(url.pathname, '/pages/search.html');
  assert.deepEqual([...url.searchParams.keys()], ['from', 'fromLat', 'fromLng', 'to', 'toLat', 'toLng', 'toAddress', 'buffer', 'notice']);
  assert.equal(url.searchParams.get('notice'), 'arrival-passed');
  assert(!url.searchParams.has('date') && !url.searchParams.has('time'));
  // 잘못된 장소는 채우지 않는다 (links.js 기존 동작), 잘못된 여유시간도 뺀다
  const broken = new URL(ctx.retimeSearchUrl(resultQuery({ toLat: 'abc', buffer: '99' })), ORIGIN).searchParams;
  assert(broken.has('from') && !broken.has('to') && !broken.has('buffer'));
  const current = new URL(ctx.retimeSearchUrl(resultQuery({ from: '현재 위치' })), ORIGIN).searchParams;
  assert(!current.has('from'));
  console.log('PASS: 도착 시각 과거 판정, 길찾기 화면 주소(장소·여유 유지, 날짜·시각 제외, 잘못된 값 제외)');
}

// --- 클립보드와 대체 경로 ---
{
  const written = [];
  const ok = { writeText: async (text) => { written.push(text); } };
  const denied = { writeText: async () => { throw new Error('NotAllowedError'); } };
  let execCalls = 0;
  const execOk = () => { execCalls += 1; return true; };
  const execFail = () => { execCalls += 1; return false; };

  assert.equal(await ctx.copyText('A', { clipboard: ok, secure: true, execCopy: execOk }), 'clipboard');
  assert.deepEqual(written, ['A']); assert.equal(execCalls, 0);
  assert.equal(await ctx.copyText('B', { clipboard: denied, secure: true, execCopy: execOk }), 'execCommand'); // 권한 거부 → execCommand
  assert.equal(await ctx.copyText('C', { clipboard: ok, secure: false, execCopy: execOk }), 'execCommand'); // http: Clipboard API 안 씀
  assert.deepEqual(written, ['A']);
  assert.equal(await ctx.copyText('D', { execCopy: execOk }), 'execCommand'); // Clipboard API 없음
  await assert.rejects(ctx.copyText('E', { clipboard: denied, secure: true, execCopy: execFail }), /복사 실패/); // 둘 다 실패 → 입력창
  await assert.rejects(ctx.copyText('F', {}), /복사 실패/);
  console.log('PASS: 클립보드(Clipboard API → execCommand → 실패 시 입력창 표시)');
}

// --- 결과 화면·길찾기 화면 연결 (소스 확인) ---
{
  const html = await read('../pages/result.html');
  const source = await read('../js/pages/result.js');
  const search = await read('../js/pages/search.js');
  assert.match(html, /id="share-button" type="button"><i data-icon="link" data-size="17"><\/i> 링크 복사<\/button>/);
  assert.match(html, /<div class="share-fallback" id="share-fallback" hidden>/);
  assert.match(html, /<input id="share-link" type="text" readonly/);
  const version = html.match(/result\.js\?v=([\w-]+)"/)[1];
  assert.equal(html.match(/result\.css\?v=([\w-]+)"/)[1], version);
  assert(source.includes(`/js/share.js?v=${version}"`));
  assert(source.includes(`/js/components/aiSummary.js?v=${version}"`));
  assert.match(source, /from "\/js\/api\.js";/); assert.match(source, /from "\/js\/auth\.js";/); // ?v= 없음
  assert.match(source, /buildShareLink\(location\.search, \{ origin: location\.origin \}\)/);
  assert(!source.includes('copyToClipboard(location.href)')); // 화면 주소를 그대로 복사하지 않는다
  assert.match(source, /input\.value = url;/);
  // 지난 도착 시각: 계산(getRoutes) 전에 안내한다
  const init = source.slice(source.indexOf('async function init()'));
  assert(init.indexOf('renderArrivalPassed()') < init.indexOf('getRoutes('));
  const passed = source.slice(source.indexOf('function renderArrivalPassed'), source.indexOf('async function init()'));
  assert(!/\.innerHTML\s*=\s*[^;]*(location|retimeSearchUrl|href)/.test(passed)); // 주소 값은 href·textContent로만
  assert.match(passed, /link\.href = retimeSearchUrl\(location\.search\);/);
  assert.match(search, /restoredQuery\.get\(NOTICE_PARAM\) === ARRIVAL_PASSED_NOTICE/);
  assert.match(search, /timeInput\.focus\(\);/);
  const css = await read('../css/pages/result.css');
  assert.match(css, /@media \(max-width: 640px\) \{\s*\.summary-inner \{ gap: 10px; \}\s*\.summary-inner \.btn \{ flex: 1 1 calc\(50% - 5px\); min-width: 0;/);
  console.log('PASS: 결과 화면 연결(링크 복사 버튼, 대체 입력창, 지난 도착 시각 선처리, 버전 일치, 375px 버튼 배치)');
}
