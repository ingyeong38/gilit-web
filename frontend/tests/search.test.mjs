// 추가 패키지 없이 실행: node frontend/tests/search.test.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const plain = (source) => source.replace(/^import[\s\S]*?from ["'][^"']+["'];/mg, '').replace(/export /g, '');
const utils = vm.createContext({ KAKAO_JS_KEY: '', URLSearchParams });
vm.runInContext(plain(await read('../js/utils.js')), utils);
const now = new Date('2026-11-06T14:59:30Z'); // 한국 23:59:30
const valid = { from: '김해시청', to: '동의대학교', date: '2026-11-07', time: '00:00', buffer: '10' };
assert.equal(utils.validateSearchConditions(valid, now), null);
for (const [change, field] of [
  [{ from: '  ' }, 'from'], [{ to: '' }, 'to'], [{ to: ' 김해시청 ' }, 'to'],
  [{ date: '' }, 'date'], [{ date: '2026-02-30' }, 'date'], [{ time: '' }, 'time'],
  [{ time: '24:00' }, 'time'], [{ date: '2026-11-06', time: '23:59' }, 'time'],
  [{ date: '2026-11-05' }, 'date'], [{ buffer: '20' }, 'buffer'],
]) assert.equal(utils.validateSearchConditions({ ...valid, ...change }, now).field, field);
assert.equal(utils.validateSearchConditions(valid, new Date('2026-11-06T15:00:00Z')).message, '현재보다 늦은 도착 시각을 선택해 주세요');
assert.equal(utils.nextDateForTime('23:59', now), '2026-11-07');
assert.equal(utils.nextDateForTime('00:00', now), '2026-11-07');
assert.equal(utils.nextDateForTime('09:00', new Date('2026-12-31T15:00:00Z')), '2027-01-01');
for (const buffer of [0, 5, 10, 15]) assert.equal(utils.validateSearchConditions({ ...valid, buffer }, now), null);
assert.equal(new URL(utils.buildResultUrl({ ...valid, from: '<서울 & 부산>' }), 'http://localhost').searchParams.get('from'), '<서울 & 부산>');

const places = JSON.parse(await read('../js/mock/places.json'));
let fetched;
const api = vm.createContext({ ...utils, USE_MOCK: true, USE_MOCK_ROUTES: true, BASE_URL: '/api', URLSearchParams,
  fetch: async (url) => { fetched = url; return { ok: true, json: async () => places }; } });
vm.runInContext(plain(await read('../js/api.js')), api);
assert.equal((await api.searchPlaces(' 김해시청 '))[0].name, '김해시청');
assert.equal((await api.searchPlaces('경상남도')).length, 3);
assert.equal((await api.searchPlaces('없는장소')).length, 0);
api.USE_MOCK = false;
api.USE_MOCK_ROUTES = false;
await api.searchPlaces(' 부산 & 김해 ');
assert.equal(fetched, '/api/places?q=%EB%B6%80%EC%82%B0+%26+%EA%B9%80%ED%95%B4');
console.log('PASS: 날짜·시각·KST 자정/연말·동일 장소·필수값·여유시간·이름/주소 검색·API 쿼리');

class Element {
  constructor() { this.children = []; this.events = {}; this.attrs = {}; this.dataset = {}; this.value = ''; this.hidden = false; this.classList = { toggle() {} }; }
  setAttribute(name, value) { this.attrs[name] = value; }
  removeAttribute(name) { delete this.attrs[name]; }
  addEventListener(name, handler) { (this.events[name] ??= []).push(handler); }
  fire(name, data = {}) {
    const event = { target: this, preventDefault() { this.prevented = true; }, ...data };
    this.events[name]?.forEach((handler) => handler(event));
    return event;
  }
  append(...elements) { this.children.push(...elements); elements.forEach((el) => { el.parent = this; }); }
  replaceChildren() { this.children = []; this._html = ''; }
  set innerHTML(value) {
    this._html = value;
    this.children = [...value.matchAll(/id="([^"]+)" data-place-index="(\d+)"/g)].map((match) => {
      const option = new Element(); option.id = match[1]; option.dataset.placeIndex = match[2]; option.parent = this; return option;
    });
  }
  get innerHTML() { return this._html ?? ''; }
  querySelectorAll() { return this.children; }
  contains(target) { return target === this || this.children.some((child) => child.contains(target)); }
  closest(selector) { return selector === '.field' ? this.field : this.dataset.placeIndex !== undefined ? this : this.parent?.closest(selector); }
  scrollIntoView() {}
  focus() { if (!this.focused) { this.focused = true; this.fire('focus'); } }
}
const timers = new Map(); let nextTimer = 0;
const setTimer = (fn) => { timers.set(++nextTimer, fn); return nextTimer; };
const runTimers = async () => { const tasks = [...timers.values()]; timers.clear(); await Promise.all(tasks.map((fn) => fn())); };
const doc = new Element(); doc.createElement = () => new Element();
const requests = [];
const component = vm.createContext({ ...utils, document: doc, icon: () => '', setTimeout: setTimer, clearTimeout: (id) => timers.delete(id),
  searchPlaces: (query) => new Promise((resolve, reject) => requests.push({ query, resolve, reject })) });
vm.runInContext(plain(await read('../js/components/placeAutocomplete.js')), component);
const input = new Element(); input.name = 'from'; input.field = new Element(); input.field.append(input);
const controller = component.setupAutocomplete(input);
const panel = input.field.children[1], status = panel.children[0], list = panel.children[1];
input.value = '김해'; input.fire('input');
assert(status.textContent.includes('검색 중'));
const firstRequest = runTimers();
input.value = '부산'; input.fire('input'); // 다음 디바운스 실행 전 이전 응답을 무효화
requests[0].resolve([places[0]]); await firstRequest;
assert.equal(list.children.length, 0);
const lastRequest = runTimers(); requests[1].resolve([places[5]]); await lastRequest;
assert(list.innerHTML.includes('부산역'));
input.fire('keydown', { key: 'ArrowDown' });
assert.equal(input.attrs['aria-activedescendant'], 'from-places-0');
assert(input.fire('keydown', { key: 'Enter' }).prevented);
assert.equal(input.value, '부산역'); assert(panel.hidden);
assert.equal(controller.getPlace().lat, places[5].lat);
assert.equal(controller.getPlace().lng, places[5].lng);
input.value = '없음'; input.fire('input');
assert.equal(controller.getPlace(), null);
const emptyRequest = runTimers(); requests.at(-1).resolve([]); await emptyRequest;
assert.equal(status.textContent, '일치하는 장소가 없어요');
assert(input.fire('keydown', { key: 'Enter' }).prevented);
input.fire('keydown', { key: 'Escape' }); assert(panel.hidden);
input.value = '실패'; input.fire('input');
const errorRequest = runTimers(); requests.at(-1).reject(new Error('failed')); await errorRequest;
assert(status.textContent.includes('재시도')); assert.equal(status.children.at(-1).textContent, '다시 검색');
input.value = '안전'; input.fire('input');
const safeRequest = runTimers(); requests.at(-1).resolve([{ name: '<img src=x>', address: '<script>alert(1)</script>' }]); await safeRequest;
assert(!list.innerHTML.includes('<img')); assert(!list.innerHTML.includes('<script>'));
list.fire('mousedown');
const option = list.children[0]; panel.fire('click', { target: option });
assert.equal(input.value, '<img src=x>'); assert(panel.hidden);
input.value = '다시'; input.fire('input'); input.fire('keydown', { key: 'Tab' }); assert(panel.hidden);
controller.close();
console.log('PASS: 디바운스·이전 응답 차단·키보드·마우스 선택·결과 없음·실패·HTML 이스케이프·닫기');

// 실제 페이지 코드를 모의 DOM에서 실행해 제출, 교환, 조건 복원, 뒤로 가기를 검사한다.
const elements = Object.fromEntries(['search-form', 'search-submit', 'swap-button', 'quick-places', 'recent-grid', 'recent-login-hint', 'place-search-hint'].map((id) => [id, new Element()]));
const form = elements['search-form']; form.elements = Object.fromEntries(['from', 'to', 'date', 'time'].map((name) => [name, new Element()]));
const buttons = ['0', '5', '10', '15'].map((buffer) => { const el = new Element(); el.dataset.buffer = buffer; return el; });
const windowMock = new Element(), docEvents = new Element(), toasts = [], navigations = [];
let rechecks = 0;
const stubs = [];
const fixedNow = new Date('2026-11-06T00:00:00Z');
class FixedDate extends Date { constructor(...args) { super(...(args.length ? args : [fixedNow])); } }
const pageContext = vm.createContext({ ...utils, Date: FixedDate, USE_MOCK: true, URLSearchParams,
  document: Object.assign(docEvents, { getElementById: (id) => elements[id], querySelectorAll: () => buttons, createElement: () => new Element() }),
  window: windowMock, location: { search: '?' + new URLSearchParams(valid), assign: (url) => navigations.push(url) },
  icon: () => '', renderIcons() {}, showToast: (message) => toasts.push(message),
  setupAutocomplete: () => { let place = null; const stub = { close() {}, getPlace() { return place; }, setPlace(value) { place = value; } }; stubs.push(stub); return stub; },
  getFavorites: async () => [], getHistory: async () => [],
  getUser: () => null, initializeAuth: async () => {}, isRedirecting: () => false, onAuthChange() {}, recheckAuth: () => { rechecks++; },
  setTimeout: setTimer, clearTimeout: (id) => timers.delete(id),
  validateSearchConditions: (data) => utils.validateSearchConditions(data, fixedNow),
});
vm.runInContext(plain(await read('../js/pages/search.js')), pageContext);
assert.equal(form.elements.from.value, valid.from);
assert.equal(form.elements.date.value, valid.date);
assert.equal(buttons[2].attrs['aria-pressed'], 'true');
elements['swap-button'].fire('click'); assert.equal(form.elements.to.value, valid.from);
form.elements.from.value = ' '; form.fire('submit'); assert(form.elements.from.focused);
form.elements.from.value = '김해시청'; form.elements.to.value = ''; form.fire('submit'); assert(form.elements.to.focused);
form.elements.to.value = '김해시청'; form.fire('submit'); assert.equal(toasts.at(-1), '출발지와 다른 목적지를 입력해 주세요');
form.elements.to.value = '동의대학교'; form.elements.date.value = ''; form.fire('submit'); assert(form.elements.date.focused);
form.elements.date.value = valid.date; form.elements.time.value = ''; form.fire('submit'); assert(form.elements.time.focused);
form.elements.time.value = valid.time; form.elements.from.value = ' 김해시청 '; form.fire('submit'); form.fire('submit');
assert(elements['search-submit'].disabled); await runTimers(); assert.equal(navigations.length, 1);
assert.equal(new URL(navigations[0], 'http://localhost').searchParams.get('from'), '김해시청');
windowMock.fire('pageshow'); assert.equal(elements['search-submit'].disabled, false);
form.fire('submit'); await runTimers(); assert.equal(navigations.length, 2);
windowMock.fire('pagehide');
// 계정 재확인: bfcache 복원(persisted)과 탭 복귀(visible)일 때만 /api/auth/me를 다시 확인한다
assert.equal(rechecks, 0); // 위의 일반 pageshow(persisted 없음)에서는 하지 않는다
windowMock.fire('pageshow', { persisted: true }); assert.equal(rechecks, 1);
docEvents.visibilityState = 'hidden'; docEvents.fire('visibilitychange'); assert.equal(rechecks, 1);
docEvents.visibilityState = 'visible'; docEvents.fire('visibilitychange'); assert.equal(rechecks, 2);
// 최근 검색 카드: 기록의 좌표를 결과 화면 쿼리로 넘기고, 좌표가 null인 쪽은 넘기지 않는다
pageContext.renderRecent([{ from: '김해시청', to: '동의대학교', arriveTime: '2026-11-02T09:00:00+09:00', fromLat: null, fromLng: null, toLat: 35.1441, toLng: 129.0336 }]);
elements['recent-grid'].children.at(-1).fire('click'); await runTimers();
const recentUrl = new URL(navigations.at(-1), 'http://localhost').searchParams;
assert.equal(recentUrl.get('to'), '동의대학교');
assert.deepEqual([recentUrl.get('toLat'), recentUrl.get('toLng')], ['35.1441', '129.0336']);
assert.equal(recentUrl.has('fromLat'), false);
console.log('PASS: bfcache 복원·탭 복귀 시 로그인 재확인, 최근 검색 카드의 기록 좌표 전달');

// 자동완성으로 고른 목적지 주소를 toAddress로 넘긴다 (형식이 맞을 때만). 최근 검색 카드는 주소가 없어 넘기지 않는다
assert.equal(recentUrl.has('toAddress'), false);
const submitWith = async (toPlace) => {
  form.elements.from.value = '김해시청'; form.elements.to.value = '동의대학교';
  form.elements.date.value = valid.date; form.elements.time.value = valid.time;
  windowMock.fire('pageshow'); // 이전 이동의 로딩 상태를 푼다 (뒤로 가기와 같다)
  stubs[0].setPlace(null); stubs[1].setPlace(toPlace);
  form.fire('submit'); await runTimers();
  return new URL(navigations.at(-1), 'http://localhost').searchParams;
};
let sent = await submitWith({ name: '동의대학교', lat: 35.1441, lng: 129.0336, address: '  부산 부산진구 엄광로 176 ' });
assert.equal(sent.get('toAddress'), '부산 부산진구 엄광로 176');
assert.equal(sent.get('toLat'), '35.1441');
for (const address of ['x'.repeat(256), '   ', 12345, null, undefined, '부산\n동구']) {
  sent = await submitWith({ name: '동의대학교', lat: 35.1441, lng: 129.0336, address });
  assert.equal(sent.has('toAddress'), false, `잘못된 주소는 넘기지 않는다: ${String(address).slice(0, 10)}`);
  assert.equal(sent.get('toLat'), '35.1441', '좌표는 그대로 넘긴다');
}
sent = await submitWith({ name: '동의대학교', lat: 35.1441, lng: 129.0336, address: 'x'.repeat(255) });
assert.equal(sent.get('toAddress').length, 255);
sent = await submitWith(null); // 자동완성으로 고르지 않음
assert.equal(sent.has('toAddress'), false);

// "조건 수정"으로 돌아오면 쿼리의 toAddress를 목적지 선택값에 되살린다 (잘못된 값은 버린다)
for (const [address, expected] of [['부산 부산진구 엄광로 176', '부산 부산진구 엄광로 176'], ['x'.repeat(256), undefined]]) {
  const restoreStubs = [];
  const query = new URLSearchParams({ ...valid, toLat: '35.1441', toLng: '129.0336', toAddress: address });
  const restoreContext = vm.createContext({ ...pageContext, location: { search: '?' + query, assign() {} },
    setupAutocomplete: () => { let place = null; const stub = { close() {}, getPlace() { return place; }, setPlace(value) { place = value; } }; restoreStubs.push(stub); return stub; } });
  vm.runInContext(plain(await read('../js/pages/search.js')), restoreContext);
  assert.equal(restoreStubs[1].getPlace().address, expected);
  assert.equal(restoreStubs[1].getPlace().lat, 35.1441);
}
console.log('PASS: 자동완성 목적지 주소 toAddress 전달(공백 정리·255자 한도·비문자열·제어 문자 거부), 조건 수정 복원');
for (const path of ['../js/components/placeAutocomplete.js', '../js/pages/search.js', '../js/pages/result.js', '../js/api.js', '../js/utils.js']) new vm.Script(plain(await read(path)));
console.log('PASS: 조건 복원·교환·입력별 포커스·중복 제출 방지·뒤로 가기 복구·변경 JS 문법');
