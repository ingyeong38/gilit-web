// 추가 패키지 없이 실행: node frontend/tests/favorites-coordinates.test.mjs
// 즐겨찾기 좌표(기록 "다시 검색" → 목적지 별, 장소 추가 모달 자동완성)와 계정 전환 시 이전 화면 상태 차단
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const read = async (path) => (await readFile(new URL(path, import.meta.url), 'utf8')).replace(/\r\n/g, '\n');
const plain = (source) => source.replace(/^import[\s\S]*?from ["'][^"']+["'];\n/gm, '').replace(/^export /gm, '');
const tick = () => new Promise((resolve) => setImmediate(resolve));
const json = (value) => JSON.parse(JSON.stringify(value));

const utils = vm.createContext({ KAKAO_JS_KEY: '', URLSearchParams });
vm.runInContext(plain(await read('../js/utils.js')), utils);

// --- 1. 기록 좌표 고르기 (utils.historyCoordinates)
{
  const pick = (item) => json(utils.historyCoordinates(item));
  assert.deepEqual(pick({ fromLat: 35.2285, fromLng: 128.8894, toLat: 35.1441, toLng: 129.0336 }),
    { fromLat: 35.2285, fromLng: 128.8894, toLat: 35.1441, toLng: 129.0336 });
  assert.deepEqual(pick({ fromLat: null, fromLng: null, toLat: 35.1441, toLng: 129.0336 }), { toLat: 35.1441, toLng: 129.0336 });
  assert.deepEqual(pick({ toLat: 35.1, toLng: null }), {}, '한쪽만 있으면 넣지 않는다');
  assert.deepEqual(pick({ toLat: '35.1', toLng: '129' }), {}, '문자열은 넣지 않는다');
  assert.deepEqual(pick({ toLat: 91, toLng: 129 }), {}, '범위 밖');
  assert.deepEqual(pick({ toLat: NaN, toLng: 129 }), {});
  assert.deepEqual(pick(undefined), {});
  const url = new URL(utils.buildResultUrl({ from: '집', to: '동의대학교', date: '2026-11-20', time: '09:00', buffer: 10,
    ...utils.historyCoordinates({ toLat: 35.1441, toLng: 129.0336 }) }), 'http://localhost').searchParams;
  assert.deepEqual([url.get('toLat'), url.get('toLng'), url.has('fromLat')], ['35.1441', '129.0336', false]);
  console.log('PASS: 기록 좌표 선택(둘 다 있는 숫자 쌍만), 결과 URL 전달');
}

// --- 2. getHistory는 캐시를 쓰지 않는다 (getFavorites와 같다)
{
  const requests = [];
  const api = vm.createContext({ ...utils, USE_MOCK: false, USE_MOCK_ROUTES: false, USE_MOCK_STATS: false, BASE_URL: '/api',
    URLSearchParams, getUser: () => ({ id: 'A' }),
    fetch: async (url, options) => { requests.push({ url, options }); return { ok: true, status: 200, json: async () => [] }; } });
  vm.runInContext(plain(await read('../js/api.js')), api);
  await api.getHistory();
  assert.equal(requests[0].url, '/api/history');
  assert.equal(requests[0].options?.cache, 'no-store');
  console.log('PASS: getHistory cache: no-store');
}

// --- 3. recheckAuth: 화면 복귀 때 서버 세션을 다시 확인한다
{
  const storage = () => { const values = new Map(); return { getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k) }; };
  const authSource = plain(await read('../js/auth.js'));
  function setup(first = { id: '1', name: 'A' }) {
    let session = async () => first;
    const events = [];
    const context = vm.createContext({
      USE_MOCK: false, URL, Event: class { constructor(type) { this.type = type; } },
      localStorage: storage(), sessionStorage: storage(),
      location: { origin: 'https://gilit.test', pathname: '/pages/search.html', search: '', hash: '', href: 'https://gilit.test/pages/search.html' },
      history: { replaceState() {} },
      window: { addEventListener() {}, dispatchEvent: (event) => events.push(event.type) },
      getSessionUser: () => session(),
      getSocialLoginUrl: () => '/api/auth/google/start',
    });
    vm.runInContext(authSource, context);
    return { context, events, setSession: (fn) => { session = fn; } };
  }
  const reject = (status) => async () => { throw Object.assign(new Error('x'), { status }); };

  // 같은 계정: 이벤트 없음
  let t = setup();
  await t.context.initializeAuth();
  t.events.length = 0;
  await t.context.recheckAuth();
  assert.deepEqual(t.events, []);
  assert.equal(t.context.getUser().id, '1');
  // 다른 탭에서 다른 계정으로 로그인: 새 계정으로 바꾸고 이벤트
  t.setSession(async () => ({ id: '2', name: 'B' }));
  await t.context.recheckAuth();
  assert.deepEqual(t.events, ['gilit:authchange']);
  assert.equal(t.context.getUser().id, '2');
  // 다른 탭에서 로그아웃(401): 로그아웃 처리
  t.setSession(reject(401));
  await t.context.recheckAuth();
  assert.equal(t.context.getUser(), null);
  assert.equal(t.events.length, 2);
  // 비로그인 상태에서 다시 401: 이벤트 없음
  await t.context.recheckAuth();
  assert.equal(t.events.length, 2);
  // 네트워크 오류(401 이외)는 판단하지 않고 지금 상태를 유지
  t = setup();
  await t.context.initializeAuth();
  t.setSession(reject(503));
  await t.context.recheckAuth();
  assert.equal(t.context.getUser().id, '1');
  // 확인 중에 이 탭에서 로그아웃했다면 늦게 온 응답(이전 계정)을 버린다
  let resolve;
  t.setSession(() => new Promise((r) => { resolve = r; }));
  const pending = t.context.recheckAuth();
  await tick();
  t.context.logout();
  resolve({ id: '9', name: 'late' });
  await pending;
  assert.equal(t.context.getUser(), null);
  console.log('PASS: recheckAuth 같은 계정 유지·계정 변경 반영·401 로그아웃·네트워크 오류 유지·늦은 응답 폐기');
}

// --- 4. 결과 화면 목적지 별: 좌표 있으면 이름 검색 없음, 없으면 정확 일치 1건일 때만 저장
{
  const star = { hidden: true, classList: { toggle() {} }, setAttribute() {}, listeners: [], addEventListener(type, fn) { this.listeners.push(fn); } };
  const toasts = [], calls = [];
  let places = [], searches = 0, searchGate = null;
  const page = vm.createContext({
    USE_MOCK: false, USE_MOCK_FAVORITES: false,
    document: { querySelector: () => null, getElementById: (id) => ({ 'destination-star': star, 'summary-to': {} })[id] ?? null },
    getUser: () => ({ id: 'A' }), initializeAuth: async () => {}, onAuthChange() {},
    showToast: (message, options) => toasts.push({ message, error: Boolean(options?.error) }),
    getFavorites: async () => [],
    addFavorite: async (place) => { calls.push(json(place)); return { ...place, id: String(calls.length) }; },
    removeFavorite: async () => {},
    searchPlaces: async (q) => { searches++; if (searchGate) await searchGate; return places.map((p) => ({ ...p })); },
    icon: () => '', escapeHtml: String, formatRouteLabel: (r) => r.label, dateOf: () => '', timeOf: () => '', formatBuffer: String, formatWon: String,
    placeAddress: utils.placeAddress,
  });
  vm.runInContext(plain(await read('../js/pages/result.js')).replace(/^init\(\);$/m, ''), page);
  const reset = () => { vm.runInContext('destinationFavoriteId = null; destinationLookup = null;', page); calls.length = 0; searches = 0; };
  const REQUIRED = '목적지 위치를 알 수 없어요. 장소를 검색해서 선택해 주세요.';

  // 기록 "다시 검색"으로 좌표가 온 경우: 이름 검색 없이 그 좌표로 저장 (숫자)
  reset();
  places = [{ name: '동의대학교', address: '부산 부산진구 엄광로 176', lat: 1, lng: 2 }];
  await page.toggleDestinationFavorite({ to: '동의대학교', toLat: '35.1441', toLng: '129.0336' });
  assert.equal(searches, 0);
  assert.deepEqual(calls, [{ name: '동의대학교', address: '동의대학교', type: '기타', lat: 35.1441, lng: 129.0336 }]);
  assert.equal(toasts.at(-1).message, '즐겨찾기에 저장했어요');

  // 좌표 없음 + 정확 일치 1건 (부분 일치는 세지 않는다): 그 좌표·주소로 저장
  reset();
  places = [
    { name: '동의대학교', address: '부산 부산진구 엄광로 176', lat: 35.1441, lng: 129.0336 },
    { name: '동의대학교 정문', address: '부산 부산진구', lat: 35.14, lng: 129.03 },
  ];
  await page.toggleDestinationFavorite({ to: '동의대학교' });
  assert.equal(searches, 1);
  assert.deepEqual(calls, [{ name: '동의대학교', address: '부산 부산진구 엄광로 176', type: '기타', lat: 35.1441, lng: 129.0336 }]);
  // 별을 해제하고 다시 눌러도 이름 검색은 다시 하지 않는다 (화면 상태에 보관한 결과 사용)
  await page.toggleDestinationFavorite({ to: '동의대학교' }); // 해제
  await page.toggleDestinationFavorite({ to: '동의대학교' }); // 다시 저장
  assert.equal(searches, 1);
  assert.equal(calls.length, 2);

  // 좌표 없음 + 0건: POST 없이 기존 안내
  reset();
  places = [{ name: '동의대학교 정문', address: '부산', lat: 35.14, lng: 129.03 }];
  await page.toggleDestinationFavorite({ to: '동의대학교' });
  assert.deepEqual(calls, []);
  assert.deepEqual(toasts.at(-1), { message: REQUIRED, error: true });

  // 좌표 없음 + 정확 일치 2건 (동명 장소): POST 없이 기존 안내
  reset();
  places = [
    { name: '스타벅스', address: '김해시', lat: 35.2, lng: 128.8 },
    { name: '스타벅스', address: '부산시', lat: 35.1, lng: 129.0 },
  ];
  await page.toggleDestinationFavorite({ to: '스타벅스' });
  assert.deepEqual(calls, []);
  assert.deepEqual(toasts.at(-1), { message: REQUIRED, error: true });

  // 정확 일치 1건이지만 좌표가 없으면 저장하지 않는다
  reset();
  places = [{ name: '동의대학교', address: '부산' }];
  await page.toggleDestinationFavorite({ to: '동의대학교' });
  assert.deepEqual(calls, []);
  assert.equal(toasts.at(-1).message, REQUIRED);

  // 장소 검색 실패: 기본 오류 문구, 저장 없음
  reset();
  page.searchPlaces = async () => { searches++; throw Object.assign(new Error('요청 실패'), { status: 502 }); };
  await page.toggleDestinationFavorite({ to: '동의대학교' });
  assert.deepEqual(calls, []);
  assert.equal(toasts.at(-1).message, '즐겨찾기에 저장하지 못했어요');

  // 조회 중 중복 클릭: 검색·저장 모두 한 번
  reset();
  page.searchPlaces = async () => { searches++; await searchGate; return [{ name: '부산역', address: '부산 동구 중앙대로 206', lat: 35.1151, lng: 129.0422 }]; };
  let open;
  searchGate = new Promise((r) => { open = r; });
  const first = page.toggleDestinationFavorite({ to: '부산역' });
  await page.toggleDestinationFavorite({ to: '부산역' });
  await page.toggleDestinationFavorite({ to: '부산역' });
  open();
  await first;
  searchGate = null;
  assert.equal(searches, 1);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].lat, 35.1151);
  console.log('PASS: 목적지 별 좌표 있음→이름 검색 없음, 좌표 없음→정확 일치 1건만 저장(0건·2건·좌표 없음·검색 실패는 안내), 결과 재사용, 중복 클릭 방지');
}

// --- 4-1. 목적지 주소(toAddress): 쿼리의 주소를 별 저장 address로 쓴다
{
  const valid = '부산광역시 부산진구 엄광로 176';
  assert.equal(utils.placeAddress(`  ${valid} `), valid);
  assert.equal(utils.placeAddress('x'.repeat(255)).length, 255);
  for (const bad of ['x'.repeat(256), '', '   ', 'a\u0000b', 'a\nb', 'a\u0085b', 12, null, undefined, ['부산'], { toString: () => '부산' }]) {
    assert.equal(utils.placeAddress(bad), null, String(bad).slice(0, 12));
  }
  const url = (toAddress) => new URL(utils.buildResultUrl({ from: 'a', to: 'b', date: '2026-11-20', time: '09:00', buffer: 0, toAddress }), 'http://localhost').searchParams;
  assert.equal(url(valid).get('toAddress'), valid);
  assert.equal(url('x'.repeat(256)).has('toAddress'), false);
  assert.equal(url(undefined).has('toAddress'), false);
  assert.equal(url('<script>&').get('toAddress'), '<script>&', 'URL에는 인코딩되어 들어가고, 화면 삽입은 escapeHtml이 맡는다');

  const calls = [];
  let searches = 0, places = [];
  const page = vm.createContext({
    ...utils, USE_MOCK: false, USE_MOCK_FAVORITES: false, URLSearchParams,
    location: { search: '' },
    document: { querySelector: () => null, getElementById: () => null },
    getUser: () => ({ id: 'A' }), initializeAuth: async () => {}, onAuthChange() {}, showToast() {},
    getFavorites: async () => [], removeFavorite: async () => {},
    addFavorite: async (place) => { calls.push(json(place)); return { ...place, id: 'n' }; },
    searchPlaces: async () => { searches++; return places; },
    icon: () => '',
  });
  vm.runInContext(plain(await read('../js/pages/result.js')).replace(/^init\(\);$/m, ''), page);
  const save = async (search) => {
    vm.runInContext('destinationFavoriteId = null; destinationLookup = null;', page);
    calls.length = 0; searches = 0;
    await page.toggleDestinationFavorite(search);
    return calls[0];
  };
  // 쿼리에서 읽기
  page.location.search = '?' + new URLSearchParams({ from: 'a', to: '동의대학교', date: '2026-11-20', time: '09:00', buffer: '0', toLat: '35.1441', toLng: '129.0336', toAddress: valid });
  const search = page.readSearchQuery();
  assert.equal(search.toAddress, valid);
  // 좌표 + 주소: 이름 검색 없이 그 주소로
  assert.deepEqual(await save(search), { name: '동의대학교', address: valid, type: '기타', lat: 35.1441, lng: 129.0336 });
  assert.equal(searches, 0);
  // 좌표만 (기록 "다시 검색"): 기존처럼 장소 이름
  assert.equal((await save({ to: '동의대학교', toLat: '35.1441', toLng: '129.0336' })).address, '동의대학교');
  // 너무 긴 값·제어 문자: 무시하고 기존 동작
  assert.equal((await save({ ...search, toAddress: 'x'.repeat(256) })).address, '동의대학교');
  assert.equal((await save({ ...search, toAddress: '부산\n동구' })).address, '동의대학교');
  // 좌표 없음: 이름 검색 결과의 좌표, 주소는 toAddress가 있으면 그것, 없으면 검색 결과 주소
  places = [{ name: '동의대학교', address: '검색 결과 주소', lat: 35.1, lng: 129.0 }];
  assert.deepEqual(await save({ to: '동의대학교', toAddress: valid }), { name: '동의대학교', type: '기타', address: valid, lat: 35.1, lng: 129.0 });
  assert.equal((await save({ to: '동의대학교' })).address, '검색 결과 주소');
  // 좌표 없음 + 일치 없음: toAddress가 있어도 서버 모드에서는 저장하지 않는다 (위치를 모름)
  places = [];
  assert.equal(await save({ to: '동의대학교', toAddress: valid }), undefined);
  console.log('PASS: toAddress 검증(255자·제어 문자·비문자열), URL 전달, 별 저장 address 사용, 없거나 잘못되면 기존 동작 유지');
}

// --- 5. 즐겨찾기 화면: 기록 카드 좌표 전달, 계정 전환 시 기록도 비움, 탭 복귀 재확인
{
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, { innerHTML: '', textContent: '', hidden: false, addEventListener() {} });
    return elements.get(id);
  };
  const docEvents = {};
  let user = { id: 'A' }, authListener, rechecks = 0, historyReads = [];
  const ctx = vm.createContext({
    ...utils, URLSearchParams,
    location: { search: '?tab=history', reload() {} },
    document: { getElementById: element, querySelectorAll: () => [], addEventListener: (type, fn) => { docEvents[type] = fn; }, visibilityState: 'visible' },
    window: { addEventListener() {} },
    getUser: () => user, onAuthChange: (fn) => { authListener = fn; }, recheckAuth: () => { rechecks++; },
    requirePageAccess: () => Promise.resolve(), renderIcons() {}, icon: () => '', showToast() {},
    getFavorites: async () => [],
    getHistory: () => new Promise((resolve, reject) => historyReads.push({ resolve, reject })),
    openAddPlaceModal() {}, addFavorite: async () => ({}), removeFavorite: async () => {},
  });
  vm.runInContext(plain(await read('../js/pages/favorites.js')), ctx);
  await tick();
  historyReads[0].resolve([
    { id: '1', from: '김해시청', to: '동의대학교', arriveTime: '2026-11-02T09:00:00+09:00', fromLat: 35.2285, fromLng: 128.8894, toLat: 35.1441, toLng: 129.0336 },
    { id: '2', from: '집', to: '센텀시티', arriveTime: '2026-10-31T10:00:00+09:00', fromLat: null, fromLng: null, toLat: null, toLng: null },
  ]);
  await tick();
  const html = element('saved-content').innerHTML;
  const hrefs = [...html.matchAll(/class="saved-search" href="([^"]+)"/g)].map(([, href]) => new URL(href.replace(/&#38;/g, '&'), 'http://localhost').searchParams);
  assert.equal(hrefs.length, 2);
  assert.deepEqual(['fromLat', 'fromLng', 'toLat', 'toLng'].map((key) => hrefs[0].get(key)), ['35.2285', '128.8894', '35.1441', '129.0336']);
  assert.equal(hrefs[1].has('toLat') || hrefs[1].has('fromLat'), false, '좌표가 null인 기록은 이름만 넘긴다');
  assert.equal(element('history-count').textContent, 2);

  // 계정 전환: 다시 불러오기가 실패해도 이전 계정 기록이 남지 않는다
  user = { id: 'B' };
  authListener();
  assert.equal(element('history-count').textContent, 0);
  assert.ok(!element('saved-content').innerHTML.includes('김해시청'));
  historyReads[1].reject(Object.assign(new Error('x'), { status: 503 }));
  await tick();
  assert.ok(!element('saved-content').innerHTML.includes('김해시청'));
  vm.runInContext('history = [{ id: "x", from: "A의 출발", to: "A의 도착", arriveTime: "2026-11-02T09:00:00+09:00" }]', ctx);
  ctx.clearFavoriteView();
  assert.equal(vm.runInContext('history.length', ctx), 0);

  // 탭 복귀(visible)일 때만 세션을 다시 확인한다
  ctx.document.visibilityState = 'hidden'; docEvents.visibilitychange();
  assert.equal(rechecks, 0);
  ctx.document.visibilityState = 'visible'; docEvents.visibilitychange();
  assert.equal(rechecks, 1);
  console.log('PASS: 기록 카드 "다시 검색" 좌표 전달(null 제외), 계정 전환 시 기록 비움(재조회 실패 포함), 탭 복귀 재확인');
}

// --- 6. 장소 추가 모달: 목록에서 골라야 저장, 고친 뒤에는 다시 골라야 함
{
  class Node {
    constructor(props = {}) { Object.assign(this, { disabled: false, value: '', innerHTML: '', listeners: {}, classes: new Set() }, props); this.classList = { toggle: (c, on) => (on ? this.classes.add(c) : this.classes.delete(c)) }; }
    addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
    click() { (this.listeners.click ?? []).forEach((fn) => fn({})); }
    focus() { this.focused = true; }
  }
  function openWith() {
    const nodes = { place: new Node(), name: new Node(), save: new Node(), cancel: new Node(), selected: new Node(),
      types: ['집', '학교', '회사', '기타'].map((type) => new Node({ dataset: { type } })) };
    let options, closed = 0, destroyed = 0, modalOptions;
    const added = [];
    const ctx = vm.createContext({
      icon: () => '<svg></svg>', escapeHtml: utils.escapeHtml,
      openModal: (value) => {
        modalOptions = value;
        const element = { querySelector: (s) => ({ '[name="place"]': nodes.place, '[name="name"]': nodes.name, '[data-action="save"]': nodes.save,
          '[data-action="cancel"]': nodes.cancel, '.place-selected': nodes.selected })[s], querySelectorAll: () => nodes.types };
        return { element, close: () => { closed++; } };
      },
      setupAutocomplete: (input, value) => { options = { input, ...value }; return { destroy: () => { destroyed++; } }; },
    });
    vm.runInContext(plain(nodes.source ?? source), ctx);
    ctx.openAddPlaceModal({ onAdd: (place) => added.push(json(place)) });
    return { nodes, added, get options() { return options; }, get closed() { return closed; }, get destroyed() { return destroyed; }, get modalOptions() { return modalOptions; } };
  }
  const source = await read('../js/components/addPlaceModal.js');
  assert.match(source, /<input name="place"[^>]*autocomplete="off"/);
  const place = { id: 'p1', name: '부산역', address: '부산광역시 동구 중앙대로 206', lat: 35.1151, lng: 129.0422 };

  // 선택 전 저장 불가 (저장 버튼 비활성, 눌러도 아무것도 보내지 않음)
  let m = openWith();
  assert.ok(m.nodes.place.focused);
  assert.equal(m.options.input, m.nodes.place);
  assert.equal(m.options.label, '즐겨찾기 장소 검색 결과');
  assert.equal(m.nodes.save.disabled, false, '모의 노드 초기값');
  m.options.onChange(null);
  assert.equal(m.nodes.save.disabled, true);
  m.nodes.save.click();
  assert.deepEqual(m.added, []);
  // 목록에서 선택: 저장 활성, 주소 표시(이스케이프), 분류 선택 유지, POST 본문은 name·address·type·숫자 lat·lng
  m.options.onChange({ ...place, address: '<b>부산</b> 동구' });
  assert.equal(m.nodes.save.disabled, false);
  assert.ok(m.nodes.selected.innerHTML.includes('&#60;b&#62;') && !m.nodes.selected.innerHTML.includes('<b>'));
  m.options.onChange(place);
  m.nodes.types[0].click();
  m.nodes.save.click();
  assert.deepEqual(m.added, [{ name: '부산역', address: '부산광역시 동구 중앙대로 206', type: '집', lat: 35.1151, lng: 129.0422 }]);
  assert.equal(typeof m.added[0].lat, 'number');
  assert.equal(m.closed, 1);
  assert.equal(m.destroyed, 1, '닫을 때 자동완성의 문서 이벤트를 뗀다');

  // 별칭을 적으면 그 이름으로, 주소가 비어 있으면 장소 이름을 주소로
  m = openWith();
  m.options.onChange({ ...place, address: '' });
  m.nodes.name.value = '  우리 집 ';
  m.nodes.save.click();
  assert.deepEqual(m.added, [{ name: '우리 집', address: '부산역', type: '기타', lat: 35.1151, lng: 129.0422 }]);

  // 선택 후 검색어를 고치면(onChange(null)) 선택이 풀려 저장할 수 없다
  m = openWith();
  m.options.onChange(place);
  m.options.onChange(null);
  assert.equal(m.nodes.save.disabled, true);
  m.nodes.save.click();
  assert.deepEqual(m.added, []);
  // 좌표 없는 결과는 고를 수 없다
  m.options.onChange({ name: '이름만', address: '주소' });
  assert.equal(m.nodes.save.disabled, true);
  assert.ok(m.nodes.selected.innerHTML.includes('위치 정보가 없는 장소'));
  // 취소·배경·Esc로 닫아도 자동완성 이벤트를 뗀다
  m.nodes.cancel.click();
  assert.equal(m.destroyed, 1);
  m = openWith();
  m.modalOptions.onDismiss();
  assert.equal(m.destroyed, 1);
  console.log('PASS: 장소 추가 모달 선택 전 저장 불가, 선택값 name·address·숫자 lat·lng 전송, 분류 유지, 입력 수정 시 선택 해제, 닫을 때 정리');
}

// --- 7. 자동완성 컴포넌트: 선택·해제 알림, 목록 라벨, 정리 / 모달 Esc
{
  class El {
    constructor() { this.children = []; this.events = {}; this.attrs = {}; this.dataset = {}; this.value = ''; this.hidden = false; }
    setAttribute(k, v) { this.attrs[k] = v; }
    removeAttribute(k) { delete this.attrs[k]; }
    addEventListener(type, fn) { (this.events[type] ??= []).push(fn); }
    removeEventListener(type, fn) { this.events[type] = (this.events[type] ?? []).filter((f) => f !== fn); }
    fire(type, data = {}) { const event = { target: this, preventDefault() { this.defaultPrevented = true; }, ...data }; (this.events[type] ?? []).forEach((fn) => fn(event)); return event; }
    append(...els) { this.children.push(...els); }
    replaceChildren() { this.children = []; }
    set innerHTML(v) { this._html = v; this.children = [...v.matchAll(/data-place-index="(\d+)"/g)].map(([, i]) => Object.assign(new El(), { id: `o${i}` })); }
    get innerHTML() { return this._html ?? ''; }
    querySelectorAll() { return this.children; }
    contains(target) { return target === this || this.children.some((c) => c.contains(target)); }
    closest() { return this.field; }
    scrollIntoView() {}
    focus() {}
  }
  const timers = [];
  const doc = new El(); doc.createElement = () => new El();
  const results = [{ name: '부산역', address: '부산 동구', lat: 35.1151, lng: 129.0422 }];
  const ctx = vm.createContext({ ...utils, document: doc, icon: () => '', setTimeout: (fn) => timers.push(fn), clearTimeout() {},
    searchPlaces: async () => results });
  vm.runInContext(plain(await read('../js/components/placeAutocomplete.js')), ctx);
  const input = new El(); input.name = 'place'; input.field = new El(); input.field.append(input);
  const changes = [];
  const controller = ctx.setupAutocomplete(input, { label: '즐겨찾기 장소 검색 결과', onChange: (p) => changes.push(p && p.name) });
  const list = input.field.children[1].children[1];
  assert.equal(list.attrs['aria-label'], '즐겨찾기 장소 검색 결과');
  input.value = '부산'; input.fire('input');
  assert.deepEqual(changes, [], '선택 전 입력은 알리지 않는다');
  await timers.shift()();
  input.fire('keydown', { key: 'ArrowDown' });
  input.fire('keydown', { key: 'Enter' });
  assert.deepEqual(changes, ['부산역']);
  assert.equal(controller.getPlace().lat, 35.1151);
  input.value = '부산역 '; input.fire('input');
  assert.deepEqual(changes, ['부산역', null], '선택 후 수정하면 선택 해제를 알린다');
  input.value = '부산역2'; input.fire('input');
  assert.equal(changes.length, 2, '이미 해제된 뒤에는 다시 알리지 않는다');
  // 자동완성이 Esc로 목록을 닫으면 preventDefault → 모달은 닫히지 않는다
  await timers.shift()?.();
  const esc = input.fire('keydown', { key: 'Escape' });
  assert.equal(esc.defaultPrevented, true);
  assert.equal(doc.events.pointerdown.length, 1);
  controller.destroy();
  assert.equal(doc.events.pointerdown.length, 0);
  // 기존 사용(옵션 없음)도 그대로 동작한다
  const plainInput = new El(); plainInput.name = 'from'; plainInput.field = new El(); plainInput.field.append(plainInput);
  ctx.setupAutocomplete(plainInput);
  assert.equal(plainInput.field.children[1].children[1].attrs['aria-label'], '출발지 검색 결과');

  const modalSource = await read('../js/components/modal.js');
  let keydown;
  const backdrop = { className: '', set innerHTML(v) {}, addEventListener() {}, querySelector: () => ({ addEventListener() {} }), remove() { this.removed = true; } };
  const modalCtx = vm.createContext({ icon: () => '', document: { createElement: () => backdrop, body: { append() {} } },
    window: { addEventListener: (type, fn) => { keydown = fn; }, removeEventListener() {} } });
  vm.runInContext(plain(modalSource), modalCtx);
  let dismissed = 0;
  modalCtx.openModal({ content: '', onDismiss: () => dismissed++ });
  keydown({ key: 'Escape', defaultPrevented: true });
  assert.equal(dismissed, 0, '자동완성 목록을 닫는 Esc는 모달을 닫지 않는다');
  keydown({ key: 'Escape', defaultPrevented: false });
  assert.equal(dismissed, 1);
  console.log('PASS: 자동완성 선택·해제 알림(onChange), 목록 라벨, destroy 정리, 기존 사용 유지, 목록 Esc와 모달 Esc 분리');
}

// --- 8. 스타일: 자동완성 공통 규칙은 components.css (즐겨찾기 화면에서도 로드), 모달 안에서는 문서 흐름에 둔다
{
  const components = await read('../css/components.css');
  const search = await read('../css/pages/search.css');
  assert.match(components, /^\.autocomplete \{ position: absolute;/m);
  assert.match(components, /^\.autocomplete\[hidden\] \{ display: none; \}/m);
  assert.match(components, /\.place-modal \.autocomplete \{ position: relative; top: auto;/);
  assert.doesNotMatch(search, /^\.autocomplete \{ position: absolute;/m, '공통 규칙이 두 곳에 있으면 안 된다');
  assert.match(search, /\.autocomplete \{ position: relative; top: auto; margin-top: 6px; \}/, '모바일 길찾기 규칙은 그대로');
  const favoritesHtml = await read('../pages/favorites.html');
  assert.ok(favoritesHtml.indexOf('/css/components.css') > 0);
  console.log('PASS: 자동완성 스타일 공통화(길찾기 모바일 규칙 유지), 모달 안 목록 문서 흐름 배치');
}
