// 추가 패키지 없이 실행: node frontend/tests/login-redirect.test.mjs
// 로그인 성공 후 메인 화면(/index.html)으로 이동: 이메일 로그인, 구글·카카오 콜백 복귀, 이동 중 데이터 요청 차단
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const read = async (path) => (await readFile(new URL(path, import.meta.url), 'utf8')).replace(/\r\n/g, '\n');
const plain = (source) => source.replace(/^import[\s\S]*?from ["'][^"']+["'];\n/gm, '').replace(/^export /gm, '');
const storage = () => { const values = new Map(); return { getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k), values }; };
const authSource = plain(await read('../js/auth.js'));

// 화면 위치(pathname)와 auth_result를 정해 auth.js를 띄운다. 인증 변경 이벤트를 받은 순간의 isRedirecting()을 기록한다.
function setup({ pathname = '/pages/search.html', result = '', search = result, session = async () => ({ id: '1', name: 'A' }), mock = false, assignThrows = false } = {}) {
  const navigations = [], listeners = {}, seenWhileChanging = [];
  const context = vm.createContext({
    USE_MOCK: mock, URL, Event: class { constructor(type) { this.type = type; } },
    localStorage: storage(), sessionStorage: storage(),
    location: { origin: 'https://gilit.test', pathname, search, hash: '', href: `https://gilit.test${pathname}${search}`,
      assign: (url) => { if (assignThrows) throw new Error('blocked'); navigations.push(['assign', url]); },
      replace: (url) => navigations.push(['replace', url]) },
    history: { replaceState() {} },
    getSessionUser: session, getSocialLoginUrl: (provider) => `https://gilit.test/api/auth/${provider}/start`,
    window: { dispatchEvent: (e) => listeners[e.type]?.forEach((fn) => fn()), addEventListener: (type, fn) => (listeners[type] ??= []).push(fn) },
  });
  vm.runInContext(authSource, context);
  context.onAuthChange(() => seenWhileChanging.push(context.isRedirecting()));
  return { context, navigations, seenWhileChanging };
}

// --- 이메일 로그인 성공 (completeLogin)
{
  // 메인이 아닌 화면: 메인으로 이동, 이동 중 표시가 인증 변경 이벤트보다 먼저 켜진다
  for (const pathname of ['/pages/search.html', '/pages/stats.html', '/pages/favorites.html']) {
    const t = setup({ pathname });
    assert.equal(t.context.completeLogin({ id: '7', name: '길잇' }), true);
    assert.deepEqual(t.navigations, [['assign', '/index.html']]);
    assert.deepEqual(t.seenWhileChanging, [true], '이동 중에 받은 인증 변경 이벤트에서 화면이 저장 데이터를 요청하지 않는다');
    assert.equal(t.context.getUser().id, '7');
    assert.equal(t.context.isRedirecting(), true);
  }
  // 이미 메인 화면, 결과 화면: 이동 없이 상태만 갱신 (이동 중 표시를 켜지 않는다)
  for (const pathname of ['/', '/index.html', '/pages/result.html']) {
    const t = setup({ pathname });
    assert.equal(t.context.completeLogin({ id: '7', name: '길잇' }), false);
    assert.deepEqual(t.navigations, []);
    assert.deepEqual(t.seenWhileChanging, [false]);
    assert.equal(t.context.getUser().id, '7');
    assert.equal(t.context.isRedirecting(), false);
  }
  // 이동이 막히면 이동 중 표시를 되돌린다
  const blocked = setup({ assignThrows: true });
  assert.throws(() => blocked.context.completeLogin({ id: '7' }), /blocked/);
  assert.equal(blocked.context.isRedirecting(), false);
  // 잘못된 사용자 응답: 이동하지 않는다
  const invalid = setup();
  assert.throws(() => invalid.context.completeLogin({ name: 'id 없음' }));
  assert.deepEqual(invalid.navigations, []);
  assert.equal(invalid.context.isRedirecting(), false);
  // 목업 이메일 로그인도 세션을 남기고 이동한다 (다음 화면에서 initializeAuth가 읽는다)
  const mock = setup({ mock: true });
  mock.context.completeLogin({ id: 'mock-1', name: 'M' });
  assert.ok(mock.context.sessionStorage.getItem('gilit:mock:session').includes('mock-1'));
  assert.deepEqual(mock.navigations, [['assign', '/index.html']]);
  console.log('PASS: 이메일 로그인 성공 → 메인 이동(이동 중 표시 먼저), 메인·결과 화면이면 이동 없음, 이동 실패·잘못된 응답 복구, 목업 세션 유지');
}

// --- 구글·카카오 시작과 콜백 복귀
{
  // 헤더에서 시작(복귀 주소 없음): 이전에 남은 복귀 주소를 지운다
  const start = setup();
  start.context.sessionStorage.setItem('gilit:auth:return', '/pages/stats.html');
  start.context.login('kakao');
  assert.equal(start.context.sessionStorage.getItem('gilit:auth:return'), null);
  assert.deepEqual(start.navigations, [['assign', 'https://gilit.test/api/auth/kakao/start']]);
  // 결과 화면에서 시작(복귀 주소 없음): 쿼리를 포함한 결과 화면 주소를 남긴다
  const resultQuery = '?' + new URLSearchParams({ from: '김해시청', to: '동의대학교', date: '2026-11-20', time: '09:00', buffer: '10', toLat: '35.1441', toLng: '129.0336', toAddress: '부산 부산진구 엄광로 176' });
  const fromResult = setup({ pathname: '/pages/result.html', search: resultQuery });
  fromResult.context.login('google');
  assert.equal(fromResult.context.sessionStorage.getItem('gilit:auth:return'), '/pages/result.html' + resultQuery);
  // 결과 화면 주소가 너무 길면(2048자 초과) 메인으로
  const longResult = setup({ pathname: '/pages/result.html', search: '?from=' + 'x'.repeat(2100) });
  longResult.context.login('kakao');
  assert.equal(longResult.context.sessionStorage.getItem('gilit:auth:return'), '/index.html');
  // 검색 화면에서 시작: 기존대로 복귀 주소 없음(메인)
  const fromSearch = setup({ pathname: '/pages/search.html', search: '?from=a' });
  fromSearch.context.login('google');
  assert.equal(fromSearch.context.sessionStorage.getItem('gilit:auth:return'), null);
  // 보호된 화면 접근(guard)에서 시작: 그 화면을 복귀 주소로 남긴다
  const guarded = setup();
  guarded.context.login('google', '/pages/favorites.html?tab=history');
  assert.equal(guarded.context.sessionStorage.getItem('gilit:auth:return'), '/pages/favorites.html?tab=history');

  // 콜백 성공 + 복귀 주소 없음 → 메인
  let t = setup({ result: '?auth_result=success' });
  await t.context.initializeAuth();
  assert.deepEqual(t.navigations, [['replace', '/index.html']]);
  assert.equal(t.context.isRedirecting(), true, '이동 중이므로 화면은 저장 데이터를 요청하지 않는다');
  assert.equal(t.context.takeAuthMessage(), '');
  // 콜백 성공 + 정해 둔 복귀 주소 → 그 화면 (보호된 화면 접근)
  t = setup({ result: '?auth_result=success' });
  t.context.sessionStorage.setItem('gilit:auth:return', '/pages/favorites.html?tab=history');
  await t.context.initializeAuth();
  assert.deepEqual(t.navigations, [['replace', '/pages/favorites.html?tab=history']]);
  assert.equal(t.context.sessionStorage.getItem('gilit:auth:return'), null, '한 번 쓰면 지운다');
  // 콜백 성공 + 결과 화면 복귀 주소 → 쿼리 그대로 결과 화면으로
  t = setup({ result: '?auth_result=success' });
  t.context.sessionStorage.setItem('gilit:auth:return', '/pages/result.html' + resultQuery);
  await t.context.initializeAuth();
  assert.deepEqual(t.navigations, [['replace', '/pages/result.html' + resultQuery]]);
  assert.equal(new URL(t.navigations[0][1], 'https://gilit.test').searchParams.get('toAddress'), '부산 부산진구 엄광로 176');
  // 저장된 값을 누가 고쳐 허용되지 않은 값·너무 긴 값이 되면 메인
  for (const stored of ['/pages/unknown.html?x=1', '//evil.test/pages/result.html', '/pages/result.html?from=' + 'x'.repeat(2100)]) {
    t = setup({ result: '?auth_result=success' });
    t.context.sessionStorage.setItem('gilit:auth:return', stored);
    await t.context.initializeAuth();
    assert.deepEqual(t.navigations, [['replace', '/index.html']], stored.slice(0, 30));
  }
  // 콜백 성공 + 허용되지 않은 복귀 주소 → 메인
  t = setup({ result: '?auth_result=success' });
  t.context.sessionStorage.setItem('gilit:auth:return', 'https://evil.test/');
  await t.context.initializeAuth();
  assert.deepEqual(t.navigations, [['replace', '/index.html']]);
  // 실패·취소·이메일 충돌: 이동 없이 안내
  for (const [result, text] of [['failed', /실패/], ['cancelled', /취소/], ['email_exists', /기존에 쓰던 방법/]]) {
    t = setup({ result: `?auth_result=${result}`, session: async () => { throw { status: 401 }; } });
    t.context.sessionStorage.setItem('gilit:auth:return', '/pages/stats.html');
    await t.context.initializeAuth();
    assert.deepEqual(t.navigations, [], result);
    assert.equal(t.context.isRedirecting(), false);
    assert.match(t.context.takeAuthMessage(), text);
  }
  // success인데 세션이 없으면(위조·만료) 이동하지 않고 실패 안내
  t = setup({ result: '?auth_result=success', session: async () => { throw { status: 401 }; } });
  await t.context.initializeAuth();
  assert.deepEqual(t.navigations, []);
  assert.match(t.context.takeAuthMessage(), /실패/);
  console.log('PASS: 소셜 시작 시 복귀 주소 정리·결과 화면(쿼리 포함)·보호 화면 유지, 콜백 성공 → 메인(결과·보호 화면 예외, 잘못되거나 긴 주소는 메인), 실패·취소·충돌·세션 없음은 이동 없이 안내');

  // 결과 화면 이메일 로그인: 이동 없이 인증 변경 알림으로 별(목적지 즐겨찾기) 상태를 다시 불러온다 (auth.js + result.js 실제 코드)
  const auth = setup({ pathname: '/pages/result.html', search: resultQuery, session: async () => { throw { status: 401 }; } });
  const star = { hidden: true, classes: new Set(), attrs: {}, addEventListener() {} };
  star.classList = { toggle: (c, on) => (on ? star.classes.add(c) : star.classes.delete(c)) };
  star.setAttribute = (k, v) => { star.attrs[k] = v; };
  const favoriteReads = [];
  const page = vm.createContext({
    USE_MOCK: false, USE_MOCK_FAVORITES: false,
    document: { querySelector: () => null, getElementById: (id) => ({ 'destination-star': star, 'summary-to': {} })[id] ?? null },
    getUser: auth.context.getUser, initializeAuth: auth.context.initializeAuth, onAuthChange: auth.context.onAuthChange, isRedirecting: auth.context.isRedirecting,
    getFavorites: async () => { favoriteReads.push(auth.context.getUser()?.id); return [{ id: '31', name: '동의대학교' }]; },
    addFavorite: async () => ({}), removeFavorite: async () => {}, searchPlaces: async () => [], showToast() {},
    icon: () => '', escapeHtml: String, formatRouteLabel: (r) => r.label, dateOf: () => '', timeOf: () => '', formatBuffer: String, formatWon: String, placeAddress: () => null,
  });
  vm.runInContext(plain(await read('../js/pages/result.js')).replace(/^init\(\);$/m, ''), page);
  page.watchDestinationFavorite({ to: '동의대학교' });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(favoriteReads, [], '비로그인 상태에서는 즐겨찾기를 요청하지 않는다');
  assert.equal(star.attrs['aria-pressed'], 'false');
  assert.equal(auth.context.completeLogin({ id: '7', name: '길잇' }), false);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(auth.navigations, [], '결과 화면에 머문다');
  assert.equal(auth.context.isRedirecting(), false);
  assert.deepEqual(favoriteReads, ['7'], '로그인한 계정의 즐겨찾기로 별 상태를 다시 불러온다');
  assert.ok(star.classes.has('active') && star.attrs['aria-pressed'] === 'true');
  console.log('PASS: 결과 화면 이메일 로그인 → 이동 없음, 이동 중 표시 꺼짐, 인증 변경 알림으로 별 상태 재조회');
}

// --- 로그인 모달: onLogin이 없으면(헤더) 메인 이동, 있으면(guard) 기존처럼 그 화면 처리
{
  const source = plain(await read('../js/components/authModal.js'));
  function openWith({ onLogin, login }) {
    const calls = [];
    let submit;
    const field = () => ({ value: '', focus() {} });
    const form = { elements: { email: field(), password: field() }, querySelector: () => ({ hidden: true }) };
    const modal = {
      setAttribute() {}, insertAdjacentHTML() {}, scrollTop: 0,
      querySelectorAll: () => [],
      querySelector: (selector) => (selector === '.auth-form' ? form : { addEventListener() {}, dataset: {} }),
    };
    const ctx = vm.createContext({
      USE_MOCK: false, icon: () => '', ApiError: class extends Error {},
      openModal: () => ({ element: { isConnected: true, querySelector: () => modal }, close: () => calls.push('close') }),
      loginWithEmail: login, signup: async () => ({}),
      setUser: (user) => calls.push(['setUser', user.id]),
      completeLogin: (user) => calls.push(['completeLogin', user.id]),
      loginWithProvider() {},
      window: { addEventListener() {} },
    });
    vm.runInContext(source, ctx);
    ctx.setupForm = (formEl, rules, onSubmit) => { submit = onSubmit; };
    ctx.bindPasswordToggles = () => {};
    ctx.openAuthModal({ onLogin });
    return { calls, submit: () => submit() };
  }
  // 헤더 로그인: 모달을 닫고 completeLogin(메인 이동 또는 상태 갱신)
  let m = openWith({ login: async () => ({ id: '7' }) });
  await m.submit();
  assert.deepEqual(m.calls, ['close', ['completeLogin', '7']]);
  // 보호된 화면 접근(guard): 기존처럼 setUser 후 onLogin, 메인으로 가지 않는다
  let guarded = 0;
  m = openWith({ login: async () => ({ id: '8' }), onLogin: () => guarded++ });
  await m.submit();
  assert.deepEqual(m.calls, [['setUser', '8'], 'close']);
  assert.equal(guarded, 1);
  // 로그인 실패: 이동·상태 변경 없음 (오류는 setupForm이 폼에 표시한다)
  m = openWith({ login: async () => { throw Object.assign(new Error('이메일 또는 비밀번호가 올바르지 않습니다.'), { status: 401 }); } });
  await assert.rejects(m.submit(), /올바르지 않습니다/);
  assert.deepEqual(m.calls, []);
  console.log('PASS: 로그인 모달 헤더 로그인 → completeLogin, 보호 화면 로그인 → 기존 onLogin, 실패 시 이동·상태 변경 없음');
}

// --- 보호된 화면에 직접 들어와 로그인: 소셜 로그인도 그 화면으로 돌아오게 returnTo를 넘긴다
{
  let opened;
  const ctx = vm.createContext({
    getUser: () => null, initializeAuth: async () => {}, onAuthChange() {},
    openAuthModal: (options) => { opened = options; },
    location: { pathname: '/pages/favorites.html', search: '?tab=history', hash: '', origin: 'https://gilit.test', replace() {} },
    document: { querySelector: () => ({ hidden: true }), addEventListener() {} },
  });
  vm.runInContext(plain(await read('../js/guard.js')), ctx);
  ctx.requirePageAccess();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(opened.returnTo, '/pages/favorites.html?tab=history');
  assert.equal(typeof opened.onLogin, 'function');
  // 보호된 화면 링크를 눌러 로그인하는 경우도 그대로 그 화면으로 (기존)
  assert.match(await read('../js/guard.js'), /openAuthModal\(\{ returnTo: link\.pathname \+ link\.search \+ link\.hash, onLogin: \(\) => location\.assign\(link\.href\) \}\)/);
  console.log('PASS: 보호된 화면 로그인은 이메일·소셜 모두 그 화면 유지 (returnTo 전달)');
}

// --- 검색 화면은 이동 중이면 저장 데이터를 요청하지 않는다 (search.js loadSavedData의 isRedirecting 검사)
{
  const searchSource = await read('../js/pages/search.js');
  assert.match(searchSource, /if \(!loggedIn \|\| isRedirecting\(\)\) return;/);
  assert.match(await read('../js/pages/result.js'), /if \(!getUser\(\) \|\| isRedirecting\(\)\) return;/);
  const html = await read('../pages/result.html');
  assert.match(html, /result\.js\?v=loginhome-20261118-2"/);
  assert.match(html, /result\.css\?v=loginhome-20261118-2"/);
  console.log('PASS: 이동 중 저장 데이터 요청 차단(검색·결과 화면), result.js 버전 갱신');
}
