// node frontend/tests/favorites-server.test.mjs — 서버 모드 즐겨찾기 요청 본문·해제 id·좌표 없는 목적지 차단
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
const strip = (source) => source.replace(/^import[\s\S]*?from ["'][^"']+["'];/mg, '').replace(/export /g, '');
const tick = () => new Promise((r) => setImmediate(r));

// 1. api.js: 서버 모드 본문과 DELETE id, 목업 모드 저장 방식
const requests = [];
const values = new Map();
let user = { id: 'A' };
let reply = { ok: true, status: 201, json: async () => ({ id: '12' }) };
const api = vm.createContext({
  USE_MOCK: false, BASE_URL: '/api', getUser: () => user, URLSearchParams, crypto: webcrypto,
  localStorage: { getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v) },
  fetch: async (url, options) => { requests.push({ url, options }); return reply; },
});
vm.runInContext(strip(await readFile(new URL('../js/api.js', import.meta.url), 'utf8')), api);

const created = await api.addFavorite({ name: '동의대학교', address: '부산 부산진구', type: '기타', lat: '35.1438', lng: '129.0345', extra: 'x' });
assert.equal(created.id, '12');
assert.equal(requests[0].url, '/api/favorites');
assert.equal(requests[0].options.method, 'POST');
const body = JSON.parse(requests[0].options.body);
assert.deepEqual(body, { name: '동의대학교', address: '부산 부산진구', type: '기타', lat: 35.1438, lng: 129.0345 });
assert.equal(typeof body.lat, 'number');
assert.equal(typeof body.lng, 'number');

// 좌표가 하나만 있거나 숫자가 아니면 보내지 않는다 (서버 검증에서 400이 되지 않게). 주소 검색 경로는 서버가 처리한다.
for (const place of [{ name: '집', address: '김해' }, { name: '집', lat: 35.1 }, { name: '집', lat: '', lng: '' }, { name: '집', lat: 'abc', lng: 1 }]) {
  await api.addFavorite(place);
  const sent = JSON.parse(requests.at(-1).options.body);
  assert.ok(!('lat' in sent) && !('lng' in sent), JSON.stringify(place));
}

reply = { ok: true, status: 204, json: async () => null };
await api.removeFavorite('12');
assert.equal(requests.at(-1).url, '/api/favorites?id=12');
assert.equal(requests.at(-1).options.method, 'DELETE');

reply = { ok: false, status: 400, json: async () => ({ message: '장소 위치를 찾을 수 없습니다. 장소를 검색해서 선택해 주세요.' }) };
await assert.rejects(api.addFavorite({ name: '집' }), (e) => e.status === 400 && e.message.startsWith('장소 위치를'));

const before = requests.length;
user = null;
await assert.rejects(api.addFavorite({ name: '집', lat: 1, lng: 1 }), (e) => e.status === 401);
await assert.rejects(api.removeFavorite('12'), (e) => e.status === 401);
await assert.rejects(api.getFavorites(), (e) => e.status === 401);
assert.equal(requests.length, before); // 비로그인은 요청하지 않는다

vm.runInContext('USE_MOCK = true', api);
user = { id: 'A' };
const mockPlace = { name: 'A 집', address: '서울', type: '집' };
const mockCreated = await api.addFavorite(mockPlace);
assert.deepEqual(JSON.parse(JSON.stringify(await api.getFavorites())), [{ ...mockPlace, id: mockCreated.id }]);
await api.removeFavorite(mockCreated.id);
assert.deepEqual(JSON.parse(JSON.stringify(await api.getFavorites())), []);
assert.equal(requests.length, before); // 목업은 서버를 부르지 않는다
console.log('PASS: 서버 본문 이름·주소·분류·숫자 좌표, 불완전 좌표 생략, DELETE ?id=, 비로그인 미요청, 목업 저장 유지');

// 2. result.js: 목적지 별 하나, 클릭으로 추가·해제, id 보관, 좌표 없는 목적지 차단, 계정 전환
const resultSource = strip(await readFile(new URL('../js/pages/result.js', import.meta.url), 'utf8')).replace(/^init\(\);\r?$/m, '');
const resultHtml = await readFile(new URL('../pages/result.html', import.meta.url), 'utf8');
assert.equal([...resultHtml.matchAll(/class="star-button"/g)].length, 1);
// 요약 바의 도착지 이름(#summary-to) 바로 뒤, 같은 nowrap 묶음 안
assert.match(resultHtml, /<span class="summary-destination"><b id="summary-to"><\/b><button class="star-button" id="destination-star" type="button" aria-label="목적지 즐겨찾기" aria-pressed="false" hidden><i data-icon="star" data-size="24"><\/i><\/button><\/span>/);
// 제목 행에는 h1만 남는다 (이전 위치의 별·이름 묶음 제거)
assert.match(resultHtml, /<div class="results-heading">\s*<div><h1 class="page-title">추천 출발시각을 찾았어요<\/h1><p>/);
for (const removed of ['title-favorite', 'results-title-row', 'results-heading-main', 'destination-favorite', 'destination-name']) assert.ok(!resultHtml.includes(removed), removed);

// 정적 검사: 별의 조상(마크업 기준)이 CSS 숨김 규칙의 대상이 아닌지. 별 자신의 hidden 속성은 JS가 푼다 (아래에서 확인).
const ancestors = [];
{
  const stack = [];
  const voidTags = new Set(['meta', 'link', 'img', 'br', 'input', 'hr']);
  for (const match of resultHtml.matchAll(/<(\/?)([a-z0-9]+)([^>]*)>/gi)) {
    const [, closing, tag, attrs] = match;
    if (closing) { stack.pop(); continue; }
    const node = { tag, cls: (attrs.match(/class="([^"]*)"/)?.[1] ?? '').split(/\s+/).filter(Boolean), id: attrs.match(/id="([^"]*)"/)?.[1], hidden: /\shidden(\s|$|>)/.test(attrs) };
    if (node.id === 'destination-star') { ancestors.push(...stack, node); break; }
    if (!voidTags.has(tag.toLowerCase())) stack.push(node);
  }
}
// 구조: .summary-bar > .summary-inner > .summary-route > .summary-destination > 별
assert.deepEqual(ancestors.slice(-5).map((n) => n.cls[0] ?? n.tag), ['summary-bar', 'summary-inner', 'summary-route', 'summary-destination', 'star-button']);
assert.deepEqual(ancestors.filter((n) => n.hidden).map((n) => n.id), ['destination-star']); // 숨김 조상 없음
const names = ancestors.flatMap((n) => [...n.cls.map((c) => `.${c}`), ...(n.id ? [`#${n.id}`] : [])]);
assert.ok(names.includes('.summary-bar') && !names.includes('.results-heading'));
const resultCss = await readFile(new URL('../css/pages/result.css', import.meta.url), 'utf8');
for (const removed of ['.title-favorite', '.results-title-row', '.results-heading-main']) assert.ok(!resultCss.includes(removed), removed);
assert.match(resultCss, /\.summary-destination \{[^}]*display: inline-flex; align-items: center; gap: 6px;[^}]*white-space: nowrap;/);
assert.match(resultCss, /#summary-to \{[^}]*overflow: hidden; text-overflow: ellipsis; white-space: nowrap;/);
assert.match(resultCss, /\.summary-destination \.star-button \{ flex-shrink: 0; min-width: 32px; min-height: 32px;/);
assert.match(resultCss, /@media \(max-width: 640px\) \{\s*\.summary-destination \.star-button \{ min-width: 44px; min-height: 44px; \}/);
assert.ok(!/\.summary-destination \.star-button \{[^}]*color:/.test(resultCss)); // 색은 .star-button / .active 그대로
assert.match(await readFile(new URL('../css/base.css', import.meta.url), 'utf8'), /--muted-2: #99a3b6;/);
assert.match(resultCss, /\.star-button \{[^}]*color: var\(--muted-2\);/);
assert.match(resultCss, /\.star-button:hover, \.star-button\.active \{ color: var\(--orange\); \}/);
// 캐시 방지 버전: css·js가 같은 값을 쓰고, 이 브랜치 이전 값(card530-20261114-6)이 아니다
const cssVersion = resultHtml.match(/result\.css\?v=([\w-]+)"/)?.[1];
const jsVersion = resultHtml.match(/result\.js\?v=([\w-]+)"/)?.[1];
assert.match(cssVersion, /^[a-z0-9-]+-\d{8}-\d+$/);
assert.equal(jsVersion, cssVersion);
assert.notEqual(cssVersion, 'card530-20261114-6');
const cssFiles = ['base.css', 'layout.css', 'components.css', 'pages/result.css'];
const hidingRules = [];
for (const file of cssFiles) {
  const css = (await readFile(new URL(`../css/${file}`, import.meta.url), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '');
  for (const [, selector, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!/display\s*:\s*none|visibility\s*:\s*hidden|clip(-path)?\s*:|opacity\s*:\s*0(?![.\d])|height\s*:\s*0(?![.\d])/.test(body)) continue;
    for (const part of selector.split(',')) {
      const hit = names.find((name) => new RegExp(`${name.replace(/[.#-]/g, '\\$&')}(?![\\w-])`).test(part));
      if (hit) hidingRules.push(`${file}: ${part.trim()}`);
    }
  }
}
assert.deepEqual(hidingRules, []);

const label = { textContent: '동의대학교' }; // renderSummary가 넣은 도착지 이름
const star = { hidden: true, classes: new Set(), attrs: {}, listeners: {} };
star.classList = { toggle: (c, on) => (on ? star.classes.add(c) : star.classes.delete(c)) };
star.setAttribute = (k, v) => { star.attrs[k] = v; };
star.addEventListener = (type, fn) => { (star.listeners[type] ??= []).push(fn); };
const clickStar = async () => { star.listeners.click.forEach((fn) => fn({})); await tick(); await tick(); };
const toasts = [];
const calls = [];
let serverFavorites = [];
let authListener;
let redirecting = false;
const placeUtils = vm.createContext({ KAKAO_JS_KEY: '', URLSearchParams });
vm.runInContext(strip(await readFile(new URL('../js/utils.js', import.meta.url), 'utf8')), placeUtils);
const page = vm.createContext({
  USE_MOCK: false, USE_MOCK_FAVORITES: false,
  document: { querySelector: () => null, getElementById: (id) => ({ 'destination-star': star, 'summary-to': label })[id] ?? null },
  getUser: () => user, initializeAuth: async () => {}, onAuthChange: (fn) => { authListener = fn; },
  isRedirecting: () => redirecting,
  showToast: (message, options) => toasts.push({ message, error: !!options?.error }),
  getFavorites: async () => { calls.push(['get']); return serverFavorites; },
  addFavorite: async (place) => { calls.push(['add', place]); return { ...place, id: '7' }; },
  removeFavorite: async (id) => { calls.push(['remove', id]); },
  searchPlaces: async () => [{ name: '동의대학교', address: '부산광역시 부산진구 엄광로 176' }],
  icon: (name) => `<svg data-name="${name}"></svg>`, escapeHtml: String, formatRouteLabel: (r) => r.label,
  placeAddress: placeUtils.placeAddress,
  dateOf: () => '2026-11-15', timeOf: (v) => v?.slice(11, 16) ?? '', formatBuffer: String, formatWon: String,
});
vm.runInContext(resultSource, page);
const favoriteId = () => vm.runInContext('destinationFavoriteId', page);
const search = { to: '동의대학교', toLat: '35.1438', toLng: '129.0345' };

// 경로 카드에는 별이 없다
const cardHtml = page.renderRouteCard({ label: '추천', name: '추천', departTime: '2026-11-15T08:00:00+09:00', arriveTime: '2026-11-15T08:50:00+09:00', durationMin: 50 }, 0, { date: '2026-11-15', buffer: 0 });
assert.ok(!cardHtml.includes('star-button') && !cardHtml.includes('data-name="star"'));

// 경로가 나오기 전에는 숨김, 나오면 별 하나를 보이고 클릭을 한 번만 연결한다
assert.equal(star.hidden, true);
user = { id: 'A' };
page.watchDestinationFavorite(search);
await tick(); await tick();
assert.equal(star.hidden, false);
assert.equal(label.textContent, '동의대학교');
assert.equal(label.title, '동의대학교');
assert.equal(star.listeners.click.length, 1);
assert.equal(star.attrs['aria-pressed'], 'false');

// 추가: 쿼리 좌표를 숫자로 그대로 쓰고 이름 검색은 하지 않는다 + 생성 id 보관 → 별 활성
calls.length = 0;
let placeSearches = 0;
page.searchPlaces = async () => { placeSearches++; return [{ name: '동의대학교', address: '부산광역시 부산진구 엄광로 176' }]; };
await clickStar();
assert.deepEqual(JSON.parse(JSON.stringify(calls.find(([type]) => type === 'add')[1])),
  { name: '동의대학교', address: '동의대학교', type: '기타', lat: 35.1438, lng: 129.0345 });
assert.equal(placeSearches, 0);
assert.equal(favoriteId(), '7');
assert.ok(star.classes.has('active') && star.attrs['aria-pressed'] === 'true');
assert.equal(toasts.at(-1).message, '즐겨찾기에 저장했어요');

// 해제: 보관한 id로 DELETE
calls.length = 0;
await clickStar();
assert.deepEqual(calls, [['remove', '7']]);
assert.equal(favoriteId(), null);
assert.ok(!star.classes.has('active') && star.attrs['aria-pressed'] === 'false');
assert.equal(toasts.at(-1).message, '즐겨찾기에서 삭제했어요');

// 서버 4xx 문구 표시, 5xx는 기본 문구
const realAdd = page.addFavorite;
page.addFavorite = async () => { throw Object.assign(new Error('이미 같은 이름의 즐겨찾기가 있습니다.'), { status: 409 }); };
await clickStar();
assert.deepEqual(toasts.at(-1), { message: '이미 같은 이름의 즐겨찾기가 있습니다.', error: true });
page.addFavorite = async () => { throw Object.assign(new Error('요청 실패'), { status: 502 }); };
await clickStar();
assert.equal(toasts.at(-1).message, '즐겨찾기에 저장하지 못했어요');
assert.equal(favoriteId(), null);
page.addFavorite = realAdd;

// 좌표 없는 목적지: 이름이 같은 결과에 좌표가 없으면 POST를 보내지 않고 안내
calls.length = 0;
await page.toggleDestinationFavorite({ to: '동의대학교' });
assert.ok(!calls.some(([type]) => type === 'add'));
assert.equal(toasts.at(-1).message, '목적지 위치를 알 수 없어요. 장소를 검색해서 선택해 주세요.');
assert.equal(favoriteId(), null);

// 목록에서 불러온 id 보관 → 별 클릭 해제 시 그 id 사용
serverFavorites = [{ id: '31', name: '동의대학교', address: '부산', type: '학교', lat: 35.1, lng: 129 }];
await page.loadDestinationFavorite('동의대학교');
assert.equal(favoriteId(), '31');
assert.ok(star.classes.has('active'));
calls.length = 0;
await clickStar();
assert.deepEqual(calls, [['remove', '31']]);

// 계정 전환: 이전 계정 상태를 버리고 새 계정 목록으로 다시 불러온다
serverFavorites = [{ id: '31', name: '동의대학교' }];
await page.loadDestinationFavorite('동의대학교');
assert.equal(favoriteId(), '31');
user = { id: 'B' };
serverFavorites = [];
authListener();
assert.equal(favoriteId(), null);
assert.ok(!star.classes.has('active'));
await tick();
assert.equal(favoriteId(), null);

// 늦게 도착한 이전 계정 응답 무시
let resolveOld;
page.getFavorites = () => new Promise((r) => { resolveOld = r; });
authListener();
page.getFavorites = async () => [];
user = { id: 'C' };
authListener();
resolveOld([{ id: '99', name: '동의대학교' }]);
await tick();
assert.equal(favoriteId(), null);

// 비로그인: 즐겨찾기 API 호출 없음
user = null;
calls.length = 0;
page.getFavorites = async () => { calls.push(['get']); return []; };
authListener();
await clickStar();
assert.deepEqual(calls, []);
assert.equal(toasts.at(-1).message, '로그인이 필요합니다.');

// 로그인 직후 메인 화면으로 이동 중(isRedirecting)이면 즐겨찾기 목록을 요청하지 않는다
user = { id: 'A' };
calls.length = 0;
redirecting = true;
await page.loadDestinationFavorite('동의대학교');
assert.deepEqual(calls, []);
redirecting = false;
await page.loadDestinationFavorite('동의대학교');
assert.deepEqual(calls, [['get']]);
user = null;

// 목업 모드: 좌표가 없어도 기존처럼 저장 (위에서 찾은 결과(일치 없음)를 다시 찾지 않고 주소는 이름으로)
vm.runInContext('USE_MOCK_FAVORITES = true', page);
user = { id: 'A' };
calls.length = 0;
page.addFavorite = async (place) => { calls.push(['add', place]); return { ...place, id: 'mock-1' }; };
await page.toggleDestinationFavorite({ to: '동의대학교' });
assert.deepEqual(JSON.parse(JSON.stringify(calls.find(([type]) => type === 'add')[1])),
  { name: '동의대학교', address: '동의대학교', type: '기타' });
assert.equal(favoriteId(), 'mock-1');
console.log('PASS: 결과 화면 목적지 별 1개(카드 별 없음), 클릭 추가·해제, 생성·목록 id 보관, 좌표 없는 목적지 미요청, 서버 문구 표시, 계정 전환 초기화, 목업 저장 유지');
