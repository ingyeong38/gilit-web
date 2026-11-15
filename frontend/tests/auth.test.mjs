// node frontend/tests/auth.test.mjs — 서버 응답을 모의한 프론트엔드 테스트
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const strip = (s) => s.replace(/^import .*;$/mg, '').replace(/export /g, '');
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const storage = () => { const values = new Map(); return { getItem: k => values.get(k) ?? null, setItem: (k,v) => values.set(k,v), removeItem: k => values.delete(k) }; };
const authSource = strip(await read('../js/auth.js'));
function setup({ mock = false, result = '', session = async () => ({ id: '1' }) } = {}) {
  const navigations = [], listeners = {};
  const context = vm.createContext({ USE_MOCK: mock, URL, Event: class { constructor(type) { this.type = type; } }, localStorage: storage(), sessionStorage: storage(),
    location: { origin: 'https://gilit.test', pathname: '/index.html', search: result, hash: '', href: 'https://gilit.test/index.html'+result, assign: url => navigations.push(url), replace: url => navigations.push(url) },
    history: { replaceState() {} }, getSessionUser: session, getSocialLoginUrl: () => 'https://gilit.test/api/auth/start',
    window: { dispatchEvent: e => listeners[e.type]?.forEach(fn => fn()), addEventListener: (type,fn) => (listeners[type] ??= []).push(fn) },
  });
  vm.runInContext(authSource, context);
  return { context, navigations };
}
const { context: c, navigations } = setup();
c.localStorage.setItem('gilit:user', '{"name":"가짜 사용자"}');
assert.equal(c.getUser(), null);
await c.initializeAuth(); assert.equal(c.getUser().name, '길잇 사용자');
for (const value of ['//evil.test', '/\\evil.test', 'https://evil.test', 'javascript:alert(1)', '/unknown', '/api/auth/logout']) assert.equal(c.safeReturnPath(value), '/pages/search.html');
assert.equal(c.safeReturnPath('/pages/result.html?from=서울&auth_result=success#route'), '/pages/result.html?from=%EC%84%9C%EC%9A%B8#route');
c.login('google', '/pages/favorites.html?tab=history'); c.login('google'); assert.equal(navigations.length, 1);
assert.equal(c.sessionStorage.getItem('gilit:auth:return'), '/pages/favorites.html?tab=history');
c.logout(); assert.equal(c.getUser(), null);
let calls = 0;
const expired = setup({ session: async () => { calls++; throw { status: 401 }; } }).context;
await Promise.all([expired.initializeAuth(), expired.initializeAuth()]); assert.equal(calls, 1); assert.equal(expired.getUser(), null);
const failed = setup({ session: async () => { throw new Error('offline'); } }).context;
await failed.initializeAuth(); assert(failed.takeAuthMessage().includes('확인하지 못'));
const success = setup({ result: '?auth_result=success' });
success.context.sessionStorage.setItem('gilit:auth:return', '/pages/stats.html'); await success.context.initializeAuth(); assert.equal(success.navigations[0], '/pages/stats.html');
const cancelled = setup({ result: '?auth_result=cancelled', session: async () => { throw { status: 401 }; } }).context;
await cancelled.initializeAuth(); assert(cancelled.takeAuthMessage().includes('취소'));
const mockCallback = setup({ mock: true, result: '?auth_result=success' }).context;
await mockCallback.initializeAuth(); assert.equal(mockCallback.getUser(), null); assert(mockCallback.takeAuthMessage().includes('실패'));
const api = vm.createContext({ USE_MOCK: true, BASE_URL: '/api', SOCIAL_AUTH_START_URLS: { google: '', kakao: '' }, URL, URLSearchParams, location: { origin: 'https://gilit.test' } });
vm.runInContext(strip(await read('../js/api.js')), api);
for (const provider of ['google','kakao']) assert.throws(() => api.getSocialLoginUrl(provider), /연동 대기/);
api.USE_MOCK = false; api.SOCIAL_AUTH_START_URLS.google = '/api/auth/google/start';
assert.equal(api.getSocialLoginUrl('google'), 'https://gilit.test/api/auth/google/start');
api.SOCIAL_AUTH_START_URLS.google = 'https://evil.test/api/auth'; assert.throws(() => api.getSocialLoginUrl('google'), /설정/);
for (const path of ['auth.js', 'api.js', 'guard.js', 'components/authModal.js', 'components/header.js']) new vm.Script(strip(await read('../js/'+path)));
console.log('PASS: 세션 확인·캐시 불신·기본 이름·중복 이동 차단·내부 복귀 검증·401/네트워크 오류·콜백 성공/취소·Mock 성공 위조 차단·연동 대기·시작 URL·문법');

// UI 이벤트 모의: 모달 X/배경/Esc 닫기와 폼 중복 제출·로딩·오류 복구
const docEvents = {}, windowEvents = {};
let dismissals = 0, removed = 0;
const closeButton = { addEventListener: (type, fn) => { docEvents.close = fn; } };
const backdrop = { set innerHTML(value) {}, querySelector: () => closeButton, remove: () => removed++, addEventListener: (type, fn) => { docEvents[type] = fn; } };
const modalContext = vm.createContext({ icon: () => '', document: { createElement: () => backdrop, body: { append() {} } }, window: { addEventListener: (type, fn) => { windowEvents[type] = fn; }, removeEventListener() {} } });
vm.runInContext(strip(await read('../js/components/modal.js')), modalContext);
modalContext.openModal({ onDismiss: () => dismissals++ }); docEvents.close();
modalContext.openModal({ onDismiss: () => dismissals++ }); docEvents.mousedown({ target: backdrop });
modalContext.openModal({ onDismiss: () => dismissals++ }); windowEvents.keydown({ key: 'Escape' });
assert.equal(dismissals, 3); assert.equal(removed, 3);
modalContext.openModal({ onDismiss: () => dismissals++ }).close(); assert.equal(dismissals, 3);
const events = {}, button = { disabled: false }, errorEl = {}, controls = [button, {}];
const form = { elements: {}, addEventListener: (type, fn) => { events[type] = fn; }, querySelector: selector => selector === '.form-error' ? errorEl : button, closest: () => ({ querySelectorAll: () => controls }), setAttribute: (key, value) => { form[key] = value; } };
const formContext = vm.createContext({ icon: () => "" });
vm.runInContext(strip(await read('../js/components/authModal.js')), formContext);
let submitted = 0, reject;
formContext.setupForm(form, {}, () => { submitted++; return new Promise((resolve, no) => { reject = no; }); });
const pending = events.submit({ preventDefault() {} }); await events.submit({ preventDefault() {} });
assert.equal(submitted, 1); assert(button.disabled); assert.equal(form['aria-busy'], 'true'); assert.equal(button.textContent, '처리 중…');
reject(new Error('offline'));
// ApiError를 모의한 클래스는 instanceof 판단에만 사용한다.
vm.runInContext('class ApiError extends Error {}', formContext);
await pending; assert.equal(button.disabled, false); assert.equal(form['aria-busy'], 'false'); assert.equal(errorEl.hidden, false);
console.log('PASS: 모달 X·배경·Esc·프로그램 닫기 구분·폼 로딩·중복 제출 방지·오류 후 복구 (모의 DOM)');

let currentUser = null, opened, authListener, replaced;
const content = { hidden: true };
const guardContext = vm.createContext({ getUser: () => currentUser, initializeAuth: async () => {}, openAuthModal: options => { opened = options; }, onAuthChange: fn => { authListener = fn; }, location: { pathname: '/pages/favorites.html', origin: 'https://gilit.test', replace: path => { replaced = path; } }, document: { querySelector: () => content, addEventListener() {} } });
vm.runInContext(strip(await read('../js/guard.js')), guardContext);
const waiting = guardContext.requirePageAccess(); await new Promise(resolve => setTimeout(resolve, 0)); assert(content.hidden); assert(opened);
currentUser = { id: '1' }; opened.onLogin(); await waiting; assert.equal(content.hidden, false);
guardContext.installAuthGuard(); currentUser = null; authListener(); assert.equal(replaced, '/pages/search.html');
content.hidden = true; currentUser = { id: '1' }; await guardContext.requirePageAccess(); assert.equal(content.hidden, false);
const headerContext = vm.createContext({ icon: () => '', escapeHtml: value => String(value).replaceAll('<', '&lt;'), onAuthChange() {}, installAuthGuard() {}, initializeAuth: () => ({ then() {} }), document: { getElementById: () => null } });
vm.runInContext(strip(await read('../js/components/header.js')), headerContext);
assert(headerContext.renderAccount(null).includes('회원가입'));
assert(headerContext.renderAccount({}).includes('길잇 사용자'));
assert(headerContext.renderAccount({ name: '<script>' }).includes('&lt;script>'));
assert(headerContext.renderAccount({ name: '길잇' }).includes('로그아웃'));
console.log('PASS: 보호 화면 대기·로그인 후 표시·로그아웃 이동·헤더 로그인/비로그인·이름 누락·HTML 이스케이프 (모의 DOM)');
