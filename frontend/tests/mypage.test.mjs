// 추가 패키지 없이 실행: node frontend/tests/mypage.test.mjs
// 마이페이지 순수 함수: 최근 7일(KST) 요일·합계·막대 높이, 닉네임 규칙, 즐겨찾기 카드, 빈 데이터, mock 로더
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const read = async (path) => (await readFile(new URL(path, import.meta.url), 'utf8')).replace(/\r\n/g, '\n');
const plain = (source) => source.replace(/^import[\s\S]*?from ["'][^"']+["'];\n/gm, '').replace(/^export /gm, '');
const json = (value) => JSON.parse(JSON.stringify(value));
const source = plain(await read('../js/mypage.js'));
const load = (useMockStats = true) => {
  const ctx = vm.createContext({ USE_MOCK_STATS: useMockStats, setTimeout, updateNickname: async (name) => ({ id: '1', name, email: null, provider: 'google' }) });
  vm.runInContext(source, ctx);
  return ctx;
};
const m = load();
const days = (now) => json(m.lastSevenDays(now));

// --- 최근 7일 (KST, 오늘 포함, 오래된 날 → 오늘)
{
  // 2026-11-19(목) 낮
  let week = days(new Date('2026-11-19T03:00:00Z'));
  assert.equal(week.length, 7);
  assert.deepEqual(week.map((d) => d.date), ['2026-11-13', '2026-11-14', '2026-11-15', '2026-11-16', '2026-11-17', '2026-11-18', '2026-11-19']);
  assert.deepEqual(week.map((d) => d.weekday), ['금', '토', '일', '월', '화', '수', '목']);
  // KST 경계: UTC 14:59:59 = KST 23:59:59 (아직 18일), UTC 15:00 = KST 0시 (19일)
  assert.equal(days(new Date('2026-11-18T14:59:59Z')).at(-1).date, '2026-11-18');
  assert.equal(days(new Date('2026-11-18T14:59:59Z')).at(-1).weekday, '수');
  assert.equal(days(new Date('2026-11-18T15:00:00Z')).at(-1).date, '2026-11-19');
  assert.equal(days(new Date('2026-11-18T15:00:00Z')).at(-1).weekday, '목');
  // UTC로는 아직 전날이어도 KST 날짜로 센다
  assert.equal(m.kstDateKey(new Date('2026-11-18T20:00:00Z')), '2026-11-19');
  // 연말·월말 경계
  week = days(new Date('2026-12-31T15:30:00Z')); // KST 2027-01-01 00:30
  assert.equal(week[0].date, '2026-12-26');
  assert.equal(week.at(-1).date, '2027-01-01');
  assert.equal(m.periodLabel(week), '12월 26일 ~ 1월 1일');
  assert.equal(m.periodLabel(days(new Date('2026-11-19T03:00:00Z'))), '11월 13일 ~ 11월 19일');
  assert.equal(m.periodLabel(days(new Date('2026-03-02T03:00:00Z'))), '2월 24일 ~ 3월 2일');
  console.log('PASS: 최근 7일 요일 라벨 순서(오래된 날→오늘), KST 자정 경계, 연말·월말 기간 라벨');
}

// --- 합계·누락·범위 밖 데이터
{
  const now = new Date('2026-11-19T03:00:00Z');
  const series = json(m.buildWeeklySeries([
    { date: '2026-11-19', count: 3 }, { date: '2026-11-13', count: 2 },
    { date: '2026-11-19', count: 1 },            // 같은 날 중복은 합친다
    { date: '2026-11-12', count: 99 },           // 7일 밖: 버린다
    { date: '2026-11-20', count: 99 },           // 미래: 버린다
    { date: '2026-11-15', count: -4 }, { date: '2026-11-16', count: 'abc' }, { date: '2026-11-17', count: 2.7 },
    null, { count: 5 },
  ], now));
  assert.deepEqual(series.map((d) => d.count), [2, 0, 0, 0, 2, 0, 4]);
  assert.equal(m.weeklyTotal(series), 8);
  const summary = json(m.weeklySummary({ daily: [{ date: '2026-11-18', count: 5 }, { date: '2026-11-19', count: 2 }], topPlace: ' 동의대학교 ' }, now));
  assert.equal(summary.total, 7);
  assert.equal(summary.total, summary.series.reduce((sum, d) => sum + d.count, 0), '"총 N회"는 7일 합계와 같다');
  assert.equal(summary.topPlace, '동의대학교');
  assert.equal(summary.period, '11월 13일 ~ 11월 19일');
  assert.equal(summary.empty, false);
  console.log('PASS: 7일 합계(중복 합산·범위 밖·음수·숫자 아님 처리), 요약의 총합 일치');
}

// --- 막대 높이
{
  const s = (counts) => counts.map((count) => ({ count }));
  assert.deepEqual(json(m.barHeights(s([4, 7, 5, 9, 6, 11, 8]))), [28, 49, 35, 63, 42, 77, 56]);
  assert.deepEqual(json(m.barHeights(s([0, 1, 100, 0, 0, 0, 0]))), [0, 6, 77, 0, 0, 0, 0], '0회는 빈 막대, 1회 이상은 최소 높이');
  assert.deepEqual(json(m.barHeights(s([0, 0, 0, 0, 0, 0, 0]))), [0, 0, 0, 0, 0, 0, 0]);
  assert.deepEqual(json(m.barHeights(s([3, 3]), { maxHeight: 50, minHeight: 4 })), [50, 50]);
  assert.deepEqual(json(m.barHeights([])), []);
  console.log('PASS: 막대 높이(최댓값 기준 비율, 0회 빈 막대, 최소 높이, 모두 0)');
}

// --- 빈 데이터
{
  const now = new Date('2026-11-19T03:00:00Z');
  for (const stats of [{}, { daily: [] }, { daily: null, topPlace: '부산역' }, { daily: [{ date: '2026-11-01', count: 9 }] }, undefined]) {
    const summary = json(m.weeklySummary(stats, now));
    assert.equal(summary.series.length, 7);
    assert.equal(summary.total, 0);
    assert.equal(summary.empty, true);
    assert.equal(summary.topPlace, null, '검색이 없으면 "가장 많이 간 곳"도 비운다');
    assert.deepEqual(summary.heights, [0, 0, 0, 0, 0, 0, 0]);
  }
  assert.equal(m.weeklyTotal(null), 0);
  assert.deepEqual(json(m.pickFavorites(null)), []);
  assert.deepEqual(json(m.pickFavorites([])), []);
  console.log('PASS: 빈 통계·빈 즐겨찾기 처리');
}

// --- 닉네임 규칙: 2~20자, 한글 완성형·영문·숫자·스페이스·- _ ! #, 한글/영문/숫자 1자 이상, 연속 공백 불가
{
  assert.deepEqual(json(vm.runInContext('NICKNAME_RULES', m)), { minLength: 2, maxLength: 20 });
  assert.equal(vm.runInContext('NICKNAME_HELP_TEXT', m), '한글, 영문, 숫자, 공백, - _ ! # 사용 가능 (2~20자)');
  const messages = json(vm.runInContext('NICKNAME_MESSAGES', m));
  const v = (value, current = '') => json(m.validateNickname(value, { current }));

  // 통과
  for (const ok of ['길잇_01', 'Gil-it', '길잇!', '#길잇', 'a b', '길잇 사용자', '가나', 'ab', '12', 'AbCdEf09', 'GILIT', 'gilit',
    '가'.repeat(20), 'a'.repeat(20), '길잇 - 01_!#', 'a-', '_가']) {
    assert.deepEqual(v(ok), { ok: true, value: ok, code: '', message: '' }, ok);
  }
  // 앞뒤 공백 제거 (탭·줄바꿈이 앞뒤에만 있으면 함께 제거된다)
  assert.deepEqual(v('  길잇러  '), { ok: true, value: '길잇러', code: '', message: '' });
  assert.equal(v(`\t 길잇 \n`).value, '길잇');
  assert.equal(v(` ${'a'.repeat(20)} `).ok, true, '앞뒤 공백은 길이에 세지 않는다');
  assert.equal(m.nicknameLength('  ab  '), 2);

  // 불가: 규칙별 오류 코드·문구
  const expectFail = (value, code, current = '') => {
    const result = v(value, current);
    assert.equal(result.ok, false, JSON.stringify(value));
    assert.equal(result.code, code, JSON.stringify(value));
    assert.equal(result.message, messages[code]);
  };
  for (const value of ['', '   ', '\t', null, undefined, 3]) expectFail(value, 'empty');
  for (const value of ['--', '!!', '##', '- _', '_ !', '-_!#']) expectFail(value, 'required');
  for (const value of ['길잇.', '길잇@', '길잇😀', '😀😀', 'ㅋㅋ', '길ㅏ', 'a/b', '<b>', 'a&b', "a'b", 'a"b', '길\t잇', '길\n잇', '길　잇', '길 잇', 'ａｂ']) {
    expectFail(value, 'chars');
  }
  expectFail('길  잇', 'spaces');
  expectFail('a   b', 'spaces');
  for (const value of ['가', 'a', '1', '가'.repeat(21), 'a'.repeat(21), ` ${'가'.repeat(21)} `]) expectFail(value, 'length');
  expectFail('김서준', 'same', '김서준');
  expectFail(' 김서준 ', 'same', '김서준');
  assert.equal(v('김서준2', '김서준').ok, true);

  // 문구 목록 (규칙별 구분)
  assert.deepEqual(messages, {
    empty: '닉네임을 입력해 주세요.',
    length: '닉네임은 2~20자로 입력해 주세요.',
    chars: '사용할 수 없는 문자가 있어요. 한글, 영문, 숫자, 공백, - _ ! #만 쓸 수 있어요.',
    spaces: '공백은 한 칸씩만 쓸 수 있어요.',
    required: '한글, 영문, 숫자를 1자 이상 포함해 주세요.',
    same: '현재 닉네임과 같아요.',
  });
  // 모달: 안내 문구 표시, 열자마자(현재 닉네임)는 오류를 보이지 않고 고친 뒤부터 검사
  const pageSource = await read('../js/pages/mypage.js');
  assert.match(pageSource, /placeholder="\$\{escapeHtml\(NICKNAME_HELP_TEXT\)\}"/);
  assert.match(pageSource, /<p id="nickname-desc">[^<]*\$\{escapeHtml\(NICKNAME_HELP_TEXT\)\}<\/p>/);
  assert.match(pageSource, /input\.addEventListener\("input", \(\) => \{ edited = true; update\(\); \}\);/);
  assert.match(pageSource, /showAll \|\| \(edited && LIVE_CODES\.includes\(result\.code\)\)/);
  assert.match(pageSource, /const LIVE_CODES = \["chars", "spaces", "length", "required"\];/);

  // 서버와 같은 결과: 공용 사례 파일 (backend/tests/test_nickname.py도 같은 파일을 읽는다)
  const shared = JSON.parse(await read('./fixtures/nickname-cases.json')).cases;
  assert.ok(shared.length >= 40);
  for (const item of shared) {
    const result = v(item.input);
    if (item.ok) assert.deepEqual(result, { ok: true, value: item.value, code: '', message: '' }, JSON.stringify(item.input));
    else assert.deepEqual([result.ok, result.code, result.message], [false, item.code, messages[item.code]], JSON.stringify(item.input));
  }
  // NFC: 자모가 분리된(NFD) 한글도 완성형으로 맞춰 통과하고, 같은 닉네임 판단도 정규화 뒤에 한다
  const nfd = '길잇 사용자'.normalize('NFD');
  assert.notEqual(nfd, '길잇 사용자');
  assert.deepEqual(v(nfd), { ok: true, value: '길잇 사용자', code: '', message: '' });
  assert.equal(v(nfd, '길잇 사용자').code, 'same');
  assert.equal(m.nicknameLength(nfd), 6);
  // 서버 오류 → 모달 문구
  for (const code of ['empty', 'length', 'chars', 'spaces', 'required']) {
    assert.equal(m.nicknameErrorMessage({ status: 400, code, message: '서버 문구' }), messages[code], code);
  }
  assert.equal(m.nicknameErrorMessage({ status: 401, message: '로그인이 필요합니다.' }), '로그인이 필요합니다.');
  assert.equal(m.nicknameErrorMessage({ status: 400, code: 'unknown', message: '다른 400 문구' }), '다른 400 문구');
  assert.equal(m.nicknameErrorMessage({ status: 503, message: 'DB 오류' }), '닉네임을 저장하지 못했어요. 잠시 후 다시 시도해 주세요.');
  assert.equal(m.nicknameErrorMessage(new TypeError('Failed to fetch')), '닉네임을 저장하지 못했어요. 잠시 후 다시 시도해 주세요.');
  console.log('PASS: 닉네임 규칙(허용 문자·한글/영문/숫자 포함·연속 공백·2~20자·앞뒤 공백 제거·현재와 같음), 규칙별 문구, 모달 안내·변경 시 검사');
}

// --- 로그인 제공자·아바타
{
  assert.equal(m.providerLabel('google'), 'Google 계정으로 이용 중');
  assert.equal(m.providerLabel('kakao'), '카카오 계정으로 이용 중');
  assert.equal(m.providerLabel('email'), '이메일로 이용 중');
  assert.equal(m.providerLabel(undefined), '길잇 계정으로 이용 중');
  assert.equal(m.avatarInitial(' 김서준'), '김');
  assert.equal(m.avatarInitial('😀abc'), '😀');
  assert.equal(m.avatarInitial(''), '길');
  console.log('PASS: 로그인 제공자 문구, 아바타 첫 글자');
}

// --- 즐겨찾기 카드
{
  const card = (place) => json(m.favoriteCardModel(place));
  assert.deepEqual(card({ id: 7, name: ' 집 ', type: '집', address: ' 김해시 ', lat: 35.2, lng: 128.8 }),
    { id: '7', name: '집', type: '집', address: '김해시', addressText: '김해시', hasAddress: true, lat: 35.2, lng: 128.8 });
  for (const address of [null, undefined, '', '   ', 'null', 'NULL']) {
    const model = card({ name: '부산역', address, lat: 35.1, lng: 129 });
    assert.equal(model.addressText, '주소 정보 없음', String(address));
    assert.equal(model.address, '', 'data 속성에는 빈 값');
    assert.equal(model.hasAddress, false);
  }
  for (const [lat, lng] of [[91, 129], [35, 181], ['35', '129'], [NaN, 129], [null, null], [35, undefined]]) {
    const model = card({ name: 'x', lat, lng });
    assert.deepEqual([model.lat, model.lng], [null, null]);
  }
  assert.equal(card({}).name, '이름 없는 장소');
  const list = Array.from({ length: 5 }, (_, i) => ({ id: i, name: `장소${i}` }));
  assert.deepEqual(json(m.pickFavorites(list)).map((p) => p.name), ['장소0', '장소1', '장소2'], '최대 3개');
  console.log('PASS: 즐겨찾기 카드(주소 없음·"null" 대체 문구, 좌표 검증, 최대 3개)');
}

// --- mock 로더
{
  const now = new Date('2026-11-18T15:00:00Z'); // KST 11-19 0시
  const stats = json(await m.loadWeeklyStats(now));
  assert.deepEqual(stats.daily.map((d) => d.date), days(now).map((d) => d.date), 'mock 날짜는 실행 시점 기준 최근 7일');
  const summary = json(m.weeklySummary(stats, now));
  assert.equal(summary.total, stats.daily.reduce((sum, d) => sum + d.count, 0));
  assert.equal(summary.series.at(-1).date, '2026-11-19');
  await assert.rejects(load(false).loadWeeklyStats(now), (error) => error.status === 501 && /연결되지 않았/.test(error.message), 'USE_MOCK_STATS=false면 아직 API가 없음을 알린다');
  const first = await m.loadFavorites();
  first[0].name = '변경';
  assert.notEqual((await m.loadFavorites())[0].name, '변경', '복사본을 돌려준다');
  assert.ok((await m.loadFavorites()).some((p) => p.address === null), 'mock에 주소 없는 장소가 있다 (대체 문구 확인용)');
  // 닉네임 저장: api.js updateNickname(PATCH /api/auth/me)을 부르고 갱신된 사용자를 돌려준다. 오류는 모달 문구로 바꿔 던진다
  const sent = [];
  assert.deepEqual(json(await m.saveNickname('새이름', { update: async (name) => { sent.push(name); return { id: '7', name, email: null, provider: 'kakao' }; } })),
    { id: '7', name: '새이름', email: null, provider: 'kakao' });
  assert.deepEqual(sent, ['새이름']);
  assert.equal((await m.saveNickname('기본경로')).name, '기본경로', '기본은 api.js updateNickname');
  await assert.rejects(m.saveNickname('길잇.', { update: async () => { throw Object.assign(new Error('서버'), { status: 400, code: 'chars' }); } }),
    (error) => error.message === '사용할 수 없는 문자가 있어요. 한글, 영문, 숫자, 공백, - _ ! #만 쓸 수 있어요.' && error.code === 'chars' && error.status === 400);
  await assert.rejects(m.saveNickname('길잇', { update: async () => { throw Object.assign(new Error('로그인이 필요합니다.'), { status: 401 }); } }),
    (error) => error.message === '로그인이 필요합니다.' && error.status === 401);
  let notified;
  assert.equal(m.openFavoriteInSearch({ name: '집' }, { notify: (msg) => { notified = msg; } }), null);
  assert.match(notified, /집/);
  console.log('PASS: mock 로더(최근 7일 날짜·USE_MOCK_STATS 분기·복사본), 저장·카드 클릭 TODO 동작');
}

// --- 연결: 보호 화면·복귀 주소·헤더 링크·HTML
{
  const guard = await read('../js/guard.js');
  assert.match(guard, /PROTECTED_PATHS = \[[^\]]*"\/pages\/mypage\.html"/);
  const storage = () => { const v = new Map(); return { getItem: (k) => v.get(k) ?? null, setItem: (k, x) => v.set(k, x), removeItem: (k) => v.delete(k) }; };
  const auth = vm.createContext({ USE_MOCK: false, URL, Event: class {}, localStorage: storage(), sessionStorage: storage(),
    location: { origin: 'https://gilit.test', pathname: '/pages/mypage.html', search: '', hash: '' }, window: { addEventListener() {}, dispatchEvent() {} },
    getSessionUser: async () => ({}), getSocialLoginUrl: () => '' });
  vm.runInContext(plain(await read('../js/auth.js')), auth);
  assert.equal(auth.safeReturnPath('/pages/mypage.html'), '/pages/mypage.html', '로그인 후 마이페이지로 돌아온다');
  const header = await read('../js/components/header.js');
  assert.match(header, /<a href="\/pages\/mypage\.html"[^>]*>\$\{icon\("user", \{ size: 17 \}\)\} 내 정보<\/a>/);
  const html = await read('../pages/mypage.html');
  assert.match(html, /<body class="page-mypage">/);
  assert.match(html, /src="\/js\/pages\/mypage\.js\?v=mypage-\d{8}-\d+"/);
  assert.match(html, /href="\/css\/pages\/mypage\.css\?v=mypage-\d{8}-\d+"/);
  assert.match(html, /data-auth-content hidden/);
  assert.doesNotMatch(html + (await read('../js/pages/mypage.js')) + (await read('../js/mypage.js')), /DepartBy|2025년 5월|절약한 시간/);
  const page = await read('../js/pages/mypage.js');
  assert.match(page, /from "\/js\/mypage\.js\?v=mypage-\d{8}-\d+"/);
  // 캐시 버전: HTML의 CSS·JS와 페이지 스크립트의 import가 같은 값이고, 처음 값(-1)이 아니다
  const versions = new Set([...html.matchAll(/mypage\.(?:css|js)\?v=([\w-]+)"/g), ...page.matchAll(/mypage\.js\?v=([\w-]+)"/g)].map((match) => match[1]));
  assert.deepEqual([...versions], ['mypage-20261119-5']);
  // 저장 성공: 공유 사용자 상태(setUser)를 바꿔 헤더도 바로 바뀌고, "서버 저장 전" 안내·TODO는 없다
  assert.match(page, /import \{ getUser, onAuthChange, recheckAuth, setUser \} from "\/js\/auth\.js";/);
  assert.match(page, /setUser\(\{ \.\.\.current, \.\.\.saved, id: current\.id, name: nickname \}\)/);
  assert.match(page, /if \(user\.name && user\.name !== nickname\) \{\s*nickname = user\.name;\s*renderProfile\(\);/);
  assert.doesNotMatch(page + (await read('../js/mypage.js')), /서버 저장(은| 전)|TODO\(닉네임 저장\)/);
  assert.match(await read('../js/mypage.js'), /import \{ updateNickname \} from "\/js\/api\.js";/);
  // 막대: JS는 비율(--h)만 넣고 높이는 CSS 배율이 정한다
  assert.match(page, /style="--h:\$\{\(summary\.heights\[index\] \/ BAR_MAX_HEIGHT\)\.toFixed\(4\)\}"/);
  assert.equal(vm.runInContext('BAR_MAX_HEIGHT', m), 77);
  assert.match(page, /from "\/js\/auth\.js";/, '공유 상태 모듈은 버전 없이 같은 인스턴스를 쓴다');
  assert.match(page, /총 \$\{summary\.total\.toLocaleString\("ko-KR"\)\}회/, '"총 N회"는 요약 합계를 쓴다');
  const css = await read('../css/pages/mypage.css');
  assert.match(css, /body\.page-mypage \{ min-width: 0; --my-s: 1\.15; \}/);
  // 컨테이너: 최대 1120px (배율 폭 1040×1.15=1196보다 작게 묶음), 좁은 화면은 양옆 24px, 640px 이하는 양옆 16px
  assert.match(css, /\.my-page-shell \{ width: min\(1120px, calc\(1040px \* var\(--my-s\)\), calc\(100% - 48px\)\); margin: auto; \}/);
  assert.match(css, /@media \(max-width: 640px\) \{[\s\S]*?\.my-page-shell \{ width: calc\(100% - 32px\); \}/);
  assert.match(css, /@media \(max-width: 900px\) \{ body\.page-mypage \{ --my-s: 1\.08; \} \}/);
  assert.match(css, /@media \(max-width: 640px\) \{ body\.page-mypage \{ --my-s: 1; \} \}/);
  assert.doesNotMatch(css, /\bzoom\s*:|transform:\s*scale/, '배율은 실제 값으로 키운다');
  // 12px 미만 글자 없음: 고정 font-size는 12px 이상, 배율 글자는 max(12px, …) 또는 12px 이상 기준값
  for (const [, value] of css.matchAll(/font-size:\s*([^;]+);/g)) {
    const fixed = value.match(/^(\d+(?:\.\d+)?)px$/);
    if (fixed) assert.ok(Number(fixed[1]) >= 12, value);
    else if (!value.startsWith('max(12px')) assert.ok(Number(value.match(/calc\((\d+)px/)[1]) >= 12, value);
  }
  // 이 파일의 규칙은 마이페이지 전용 선택자만 쓴다 (다른 화면 영향 없음)
  const selectors = [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}@]+)\{[^{}]*\}/g)].flatMap((match) => match[1].split(',')).map((s) => s.trim()).filter((s) => s && !/^(from|to|\d+%)$/.test(s));
  for (const selector of selectors) assert.match(selector, /page-mypage|\.my-|my-page|nickname-|profile-(edit-row|large-avatar|identity)|edit-profile-button|section-(number|link)/, selector);
  for (const path of ['../js/pages/mypage.js', '../js/mypage.js', '../js/components/header.js', '../js/guard.js', '../js/auth.js']) new vm.Script(plain(await read(path)));
  console.log('PASS: 보호 화면 등록, 로그인 후 마이페이지 복귀, 헤더 "내 정보" 링크, HTML·버전·브랜드 문구, 문법');
}

// --- api.js 닉네임 변경 호출 (서버 호출은 api.js에만)
{
  const utils = vm.createContext({ KAKAO_JS_KEY: '', URLSearchParams });
  vm.runInContext(plain(await read('../js/utils.js')), utils);
  const requests = [];
  let reply;
  const values = new Map();
  let user = { id: '7', name: '옛이름', email: null, provider: 'google' };
  const api = vm.createContext({ ...utils, USE_MOCK: false, USE_MOCK_STATS: true, USE_MOCK_ROUTES: false, BASE_URL: '/api', URLSearchParams,
    getUser: () => user, localStorage: { getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v) },
    fetch: async (url, options) => { requests.push({ url, options }); return reply; } });
  vm.runInContext(plain(await read('../js/api.js')), api);
  reply = { ok: true, status: 200, json: async () => ({ id: '7', name: '새이름', email: null, provider: 'google' }) };
  assert.deepEqual(json(await api.updateNickname('새이름')), { id: '7', name: '새이름', email: null, provider: 'google' });
  assert.equal(requests[0].url, '/api/auth/me');
  assert.equal(requests[0].options.method, 'PATCH');
  assert.equal(requests[0].options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(requests[0].options.body), { name: '새이름' });
  // 400 + code를 ApiError로 그대로 전달
  reply = { ok: false, status: 400, json: async () => ({ message: '공백은 한 칸씩만 쓸 수 있어요.', code: 'spaces' }) };
  await assert.rejects(api.updateNickname('길  잇'), (error) => error.status === 400 && error.code === 'spaces' && error.message === '공백은 한 칸씩만 쓸 수 있어요.');
  reply = { ok: false, status: 401, json: async () => ({ message: '로그인이 필요합니다.' }) };
  await assert.rejects(api.updateNickname('새이름'), (error) => error.status === 401 && error.code === undefined);
  // mock(USE_MOCK): 서버를 부르지 않고 mock 계정 목록에 NFC·앞뒤 공백 제거한 이름을 저장
  vm.runInContext('USE_MOCK = true', api);
  values.set('gilit:mock:users', JSON.stringify([{ id: '7', name: '옛이름', email: 'a@b.c' }, { id: '8', name: '남' }]));
  const count = requests.length;
  const nfd = '길잇'.normalize('NFD');
  assert.equal((await api.updateNickname(` ${nfd} `)).name, '길잇');
  assert.equal(requests.length, count);
  assert.deepEqual(JSON.parse(values.get('gilit:mock:users')).map((u) => u.name), ['길잇', '남']);
  user = null;
  await assert.rejects(api.updateNickname('길잇'), (error) => error.status === 401);
  console.log('PASS: api.js updateNickname(PATCH /api/auth/me 본문·400 code 전달·401), mock 분기');
}
