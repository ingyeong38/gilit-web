// 추가 패키지 없이 실행: node frontend/tests/search-saved-data.test.mjs
// 검색 화면의 즐겨찾기·최근 검색 불러오기 (search.js loadSavedData)
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = (await readFile(new URL('../js/pages/search.js', import.meta.url), 'utf8')).replace(/\r\n/g, '\n');

// 정적 검사: 로그인 상태가 확정된 뒤에만 부르고, 로그인·로그아웃 때 다시 부른다.
assert.match(source, /initializeAuth\(\)\.then\(\(\) => \{\s*loadSavedData\(\);\s*onAuthChange\(loadSavedData\);/);
assert.doesNotMatch(source, /^loadSavedData\(\);/m, '모듈 최상위에서 바로 부르면 /api/auth/me 응답 전에 실행된다');
console.log('PASS: initializeAuth 이후 호출·인증 변경 시 재호출 (정적)');

// loadSavedData와 필요한 함수만 떼어 모의 DOM에서 실행한다.
const pick = (name) => {
  const start = source.search(new RegExp(`^(async )?function ${name}\\(`, 'm'));
  assert(start >= 0, name);
  const end = source.indexOf('\n}\n', start);
  return source.slice(start, end + 2);
};
const code = ['let savedDataGeneration = 0;', ...['clearSavedData', 'loadSavedData'].map(pick)].join('\n');

class El {
  constructor(id) { this.id = id; this.hidden = false; this.children = []; }
  querySelectorAll() { return this.children.filter((child) => child.tag === 'button'); }
  replaceChildren() { this.children = []; }
}

function setup({ user = { id: 'u1' }, redirecting = false, favorites, history }) {
  const els = Object.fromEntries(['quick-places', 'recent-grid', 'recent-login-hint'].map((id) => [id, new El(id)]));
  const calls = { favorites: 0, history: 0 };
  const toasts = [];
  const rendered = { quick: [], recent: [] };
  const context = vm.createContext({
    document: { getElementById: (id) => els[id] },
    getUser: () => context.user,
    user,
    isRedirecting: () => redirecting,
    getFavorites: () => { calls.favorites++; return favorites(); },
    getHistory: () => { calls.history++; return history(); },
    renderQuickPlaces: (value) => rendered.quick.push(value),
    renderRecent: (value) => rendered.recent.push(value),
    showToast: (message, options) => toasts.push({ message, ...options }),
  });
  vm.runInContext(code, context);
  return { context, els, calls, toasts, rendered };
}
const ok = (value) => async () => value;
const fail = (status) => async () => { throw { status }; };

// 비로그인: 서버를 부르지 않고 토스트도 없다. 최근 검색 자리에 안내를 보인다.
{
  const t = setup({ user: null, favorites: ok([]), history: ok([]) });
  await t.context.loadSavedData();
  assert.deepEqual(t.calls, { favorites: 0, history: 0 });
  assert.equal(t.toasts.length, 0);
  assert.equal(t.els['recent-login-hint'].hidden, false);
  assert.equal(t.els['recent-grid'].hidden, true);
  assert.equal(t.els['quick-places'].hidden, true);
}
// 소셜 로그인 복귀로 화면을 떠나는 중이면 부르지 않는다.
{
  const t = setup({ redirecting: true, favorites: ok([]), history: ok([]) });
  await t.context.loadSavedData();
  assert.deepEqual(t.calls, { favorites: 0, history: 0 });
}
// 로그인: 둘 다 성공하면 그리고 토스트 없음.
{
  const t = setup({ favorites: ok([{ name: '집' }]), history: ok([{ from: 'a', to: 'b' }]) });
  await t.context.loadSavedData();
  assert.deepEqual(t.calls, { favorites: 1, history: 1 });
  assert.equal(t.rendered.quick.length, 1);
  assert.equal(t.rendered.recent.length, 1);
  assert.equal(t.toasts.length, 0);
  assert.equal(t.els['recent-login-hint'].hidden, true);
  assert.equal(t.els['recent-grid'].hidden, false);
}
// 부분 실패: 성공한 쪽은 그리고, 실패한 쪽만 알린다.
{
  const t = setup({ favorites: fail(500), history: ok([{ from: 'a', to: 'b' }]) });
  await t.context.loadSavedData();
  assert.equal(t.rendered.recent.length, 1);
  assert.equal(t.rendered.quick.length, 0);
  assert.deepEqual(t.toasts.map((x) => x.message), ['즐겨찾기를 불러오지 못했어요']);
  assert.equal(t.toasts[0].error, true);
}
{
  const t = setup({ favorites: ok([{ name: '집' }]), history: fail(503) });
  await t.context.loadSavedData();
  assert.equal(t.rendered.quick.length, 1);
  assert.deepEqual(t.toasts.map((x) => x.message), ['최근 검색을 불러오지 못했어요']);
}
{
  const t = setup({ favorites: fail(500), history: fail(500) });
  await t.context.loadSavedData();
  assert.deepEqual(t.toasts.map((x) => x.message), ['저장된 정보를 불러오지 못했어요']);
}
// 응답 대기 중 로그아웃(재호출)하면 이전 응답은 그리지도 알리지도 않는다.
{
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const t = setup({ favorites: () => pending.then(() => { throw { status: 401 }; }), history: () => pending.then(() => []) });
  const first = t.context.loadSavedData();
  t.context.user = null;
  await t.context.loadSavedData();
  release(); await first;
  assert.equal(t.rendered.recent.length, 0);
  assert.equal(t.toasts.length, 0);
  assert.equal(t.els['recent-login-hint'].hidden, false);
}
// 다시 그리기 전에 이전 즐겨찾기 버튼과 기록 카드를 지운다 (라벨 span은 남긴다).
{
  const t = setup({ favorites: ok([]), history: ok([]) });
  t.els['quick-places'].children = [{ tag: 'span' }, { tag: 'button', remove() { t.els['quick-places'].children = t.els['quick-places'].children.filter((c) => c !== this); } }];
  t.els['recent-grid'].children = [{ tag: 'button' }];
  await t.context.loadSavedData();
  assert.deepEqual(t.els['quick-places'].children.map((c) => c.tag), ['span']);
  assert.equal(t.els['recent-grid'].children.length, 0);
}
console.log('PASS: 비로그인 미호출·안내 표시·복귀 중 미호출·부분 실패 표시/토스트·로그아웃 경합·재렌더 초기화');
