// 추가 패키지 없이 실행: node frontend/tests/links.test.mjs
// 화면 사이 이동 주소 (js/links.js): 장소 쿼리 만들기·읽기·검증, 즐겨찾기·기록 화면 탭 쿼리, 길찾기 화면 목적지 채우기
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const read = async (path) => (await readFile(new URL(path, import.meta.url), 'utf8')).replace(/\r\n/g, '\n');
const plain = (source) => source.replace(/^import[\s\S]*?from ["'][^"']+["'];[^\n]*\n/gm, '').replace(/^export /gm, '');
const json = (value) => JSON.parse(JSON.stringify(value));
const ctx = vm.createContext({ KAKAO_JS_KEY: '', URLSearchParams });
vm.runInContext(plain(await read('../js/utils.js')), ctx);
vm.runInContext(plain(await read('../js/links.js')), ctx);
const L = ctx;
const read_ = (query, prefix = 'to') => json(L.readPlaceParams(new URLSearchParams(query), prefix));

// --- 만들기
{
  const place = { name: '동의대학교', lat: 35.1441, lng: 129.0336, address: '부산광역시 부산진구 엄광로 176' };
  assert.deepEqual(json(L.placeToParams('to', place)), { to: '동의대학교', toLat: '35.1441', toLng: '129.0336', toAddress: '부산광역시 부산진구 엄광로 176' });
  assert.deepEqual(json(L.placeToParams('from', place)), { from: '동의대학교', fromLat: '35.1441', fromLng: '129.0336', fromAddress: '부산광역시 부산진구 엄광로 176' }, '출발지도 같은 형식');
  // 좌표 없음·한쪽만·범위 밖·문자열이면 이름만, 주소는 좌표가 있을 때만
  assert.deepEqual(json(L.placeToParams('to', { name: '집', address: '김해' })), { to: '집' });
  assert.deepEqual(json(L.placeToParams('to', { name: '집', lat: 35.1 })), { to: '집' });
  assert.deepEqual(json(L.placeToParams('to', { name: '집', lat: 91, lng: 129 })), { to: '집' });
  assert.deepEqual(json(L.placeToParams('to', { name: '집', lat: '35.1', lng: '129.1' })), { to: '집' });
  assert.deepEqual(json(L.placeToParams('to', { name: '집', lat: 35.1, lng: 129.1, address: null })), { to: '집', toLat: '35.1', toLng: '129.1' });
  assert.deepEqual(json(L.placeToParams('to', { name: '  집  ', lat: 35, lng: 129 })), { to: '집', toLat: '35', toLng: '129' }, '이름 앞뒤 공백 제거, 정수 좌표');
  // 이름이 틀리면 null
  for (const name of [undefined, null, '', '   ', 12, 'a'.repeat(101), '집\n잇', '집\u0000']) assert.equal(L.placeToParams('to', { name, lat: 35, lng: 129 }), null, JSON.stringify(name));
  assert.ok(L.placeToParams('to', { name: '가'.repeat(100) }), '100자는 된다');
  assert.throws(() => L.placeToParams('via', place), /알 수 없는 장소 구분/);
  // 좌표 문자열: 소수 7자리까지, 지수 표기 없음
  assert.equal(L.formatCoordinate(35.12345678), '35.1234568');
  assert.equal(L.formatCoordinate(0.0000001), '0.0000001');
  assert.equal(L.formatCoordinate(-33.5), '-33.5');
  assert.equal(L.formatCoordinate(100), '100');
  assert.equal(L.formatCoordinate(0), '0');
  // 길찾기 주소: 틀린 장소는 빼고, 아무것도 없으면 쿼리 없음
  assert.equal(L.buildSearchUrl({ to: { name: '집', lat: 35.2342, lng: 128.8811 } }), '/pages/search.html?to=%EC%A7%91&toLat=35.2342&toLng=128.8811');
  assert.equal(L.buildSearchUrl({ to: { name: '' } }), '/pages/search.html');
  assert.equal(L.buildSearchUrl(), '/pages/search.html');
  assert.equal(L.buildSearchUrl({ from: { name: '김해시청', lat: 35.2285, lng: 128.8894 }, to: { name: '집' } }),
    '/pages/search.html?from=%EA%B9%80%ED%95%B4%EC%8B%9C%EC%B2%AD&fromLat=35.2285&fromLng=128.8894&to=%EC%A7%91', '출발지를 더해도 같은 형식');
  console.log('PASS: 장소 쿼리 만들기(목적지·출발지 같은 형식, 좌표·주소 조건, 이름 검사, 좌표 문자열, 길찾기 주소)');
}

// --- 읽기
{
  assert.deepEqual(read_('to=집&toLat=35.2342&toLng=128.8811&toAddress=김해시'), { name: '집', lat: 35.2342, lng: 128.8811, address: '김해시' });
  assert.deepEqual(read_('to=집&toLat=35.2342&toLng=128.8811'), { name: '집', lat: 35.2342, lng: 128.8811 });
  assert.deepEqual(read_('to=%20집%20'), { name: '집' }, '이름만 (선택 상태 아님), 앞뒤 공백 제거');
  assert.deepEqual(read_('to=집&toLat=-33.5&toLng=-70.25'), { name: '집', lat: -33.5, lng: -70.25 }, '음수');
  assert.deepEqual(read_('to=집&toLat=90&toLng=180'), { name: '집', lat: 90, lng: 180 }, '경계값');
  assert.deepEqual(read_('from=김해시청&fromLat=35.2285&fromLng=128.8894', 'from'), { name: '김해시청', lat: 35.2285, lng: 128.8894 }, '출발지도 같은 규칙');
  assert.equal(L.readPlaceParams(new URLSearchParams(''), 'to'), null, '없음');
  assert.equal(L.readPlaceParams(new URLSearchParams('from=집'), 'to'), null, '다른 구분만 있음');
  // 하나라도 틀리면 null (채우지 않는다)
  const invalid = {
    '좌표 한쪽 누락(위도만)': 'to=집&toLat=35.1',
    '좌표 한쪽 누락(경도만)': 'to=집&toLng=129.1',
    '좌표 빈 값': 'to=집&toLat=&toLng=129.1',
    '위도 범위 밖': 'to=집&toLat=90.0001&toLng=129',
    '경도 범위 밖': 'to=집&toLat=35&toLng=-180.5',
    '문자열 좌표': 'to=집&toLat=abc&toLng=129',
    '숫자+문자': 'to=집&toLat=35.1abc&toLng=129',
    '지수 표기': 'to=집&toLat=3.5e1&toLng=129',
    '16진수': 'to=집&toLat=0x23&toLng=129',
    '앞뒤 공백 좌표': 'to=집&toLat=%2035.1&toLng=129',
    '+ 부호': 'to=집&toLat=%2B35.1&toLng=129',
    'Infinity': 'to=집&toLat=Infinity&toLng=129',
    'NaN': 'to=집&toLat=NaN&toLng=129',
    '이름 없음': 'toLat=35.1&toLng=129',
    '이름 빈 값': 'to=&toLat=35.1&toLng=129',
    '이름 공백만': 'to=%20%20&toLat=35.1&toLng=129',
    '이름 101자': `to=${'가'.repeat(101)}&toLat=35.1&toLng=129`,
    '이름 줄바꿈': 'to=%EC%A7%91%0A%EC%9E%87&toLat=35.1&toLng=129',
    '이름이 줄바꿈뿐': 'to=%0A&toLat=35.1&toLng=129',
    '이름 제어 문자': 'to=%EC%A7%91%00',
    '주소 256자': `to=집&toLat=35.1&toLng=129&toAddress=${'가'.repeat(256)}`,
    '주소 빈 값': 'to=집&toLat=35.1&toLng=129&toAddress=',
    '주소 제어 문자': 'to=집&toLat=35.1&toLng=129&toAddress=%EA%B9%80%09%ED%95%B4',
    '좌표 없이 주소': 'to=집&toAddress=김해',
  };
  for (const [label, query] of Object.entries(invalid)) assert.equal(L.readPlaceParams(new URLSearchParams(query), 'to'), null, label);
  assert.ok(L.readPlaceParams(new URLSearchParams(`to=${'가'.repeat(100)}`), 'to'), '이름 100자는 된다');
  assert.ok(L.readPlaceParams(new URLSearchParams(`to=집&toLat=35&toLng=129&toAddress=${'가'.repeat(255)}`), 'to'), '주소 255자는 된다');
  // 문자열 쿼리도 받는다
  assert.deepEqual(json(L.readPlaceParams('?to=집&toLat=35&toLng=129', 'to')), { name: '집', lat: 35, lng: 129 });
  assert.throws(() => L.readPlaceParams(new URLSearchParams('to=집'), 'via'), /알 수 없는 장소 구분/);
  console.log('PASS: 장소 쿼리 읽기(정상값, 좌표 누락·범위 밖·문자열·지수, 이름·주소 길이·제어 문자, 하나라도 틀리면 null)');
}

// --- 스크립트 문자열은 텍스트로만 (검증은 그대로 통과하고, 화면은 value·textContent로 넣는다)
{
  const name = '<script>alert(1)</script>';
  const address = '<img src=x onerror=alert(1)>';
  const url = L.buildSearchUrl({ to: { name, lat: 35.1, lng: 129.1, address } });
  assert.doesNotMatch(url, /[<>"' ]/, '주소에는 인코딩된 값만');
  const parsed = json(L.readPlaceParams(new URL(url, 'https://gilit.test').searchParams, 'to'));
  assert.deepEqual(parsed, { name, lat: 35.1, lng: 129.1, address }, '바꾸지 않은 원래 문자열 그대로');
  assert.deepEqual(read_('to=%22%3E%3Cscript%3E&toLat=35&toLng=129'), { name: '"><script>', lat: 35, lng: 129 });
  // 길찾기 화면은 목적지를 innerHTML로 넣지 않는다
  const search = await read('../js/pages/search.js');
  assert.match(search, /toInput\.value = destination\?\.name \?\? "";/);
  assert.doesNotMatch(search, /innerHTML[^\n]*destination/);
  console.log('PASS: <script>·태그 문자열은 텍스트 그대로 왕복, 길찾기 화면은 value로만 채움');
}

// --- 인코딩·디코딩 왕복
{
  const places = [
    { name: '집', lat: 35.2342, lng: 128.8811, address: '경상남도 김해시 내외중앙로 47' },
    { name: 'A&B=C?#%+', lat: -12.3456789, lng: 179.9999999, address: '서울 중구 세종대로 110 (태평로1가) & 주변' },
    { name: '센텀 시티 오피스 3층', lat: 0, lng: 0 },
    { name: '한글 이름 😀', lat: 35.1, lng: 129.1 },
    { name: '좌표 없음' },
  ];
  for (const place of places) {
    const url = L.buildSearchUrl({ to: place });
    const back = json(L.readPlaceParams(new URL(url, 'https://gilit.test').searchParams, 'to'));
    assert.deepEqual(back, json(place), url);
  }
  // 소수 7자리 넘는 좌표는 7자리로 맞춰 돌아온다 (서버 저장 정밀도)
  const rounded = json(L.readPlaceParams(new URL(L.buildSearchUrl({ to: { name: '집', lat: 35.123456789, lng: 129.987654321 } }), 'https://gilit.test').searchParams, 'to'));
  assert.deepEqual(rounded, { name: '집', lat: 35.1234568, lng: 129.9876543 });
  // 결과 화면 주소(buildResultUrl)의 목적지 형식도 그대로 읽는다 ("조건 수정"으로 돌아올 때)
  const result = L.buildResultUrl({ from: '김해시청', to: '동의대학교', date: '2026-11-20', time: '09:00', buffer: 10, toLat: 35.1441, toLng: 129.0336, toAddress: '부산 엄광로 176' });
  assert.deepEqual(json(L.readPlaceParams(new URL(result, 'https://gilit.test').searchParams, 'to')), { name: '동의대학교', lat: 35.1441, lng: 129.0336, address: '부산 엄광로 176' });
  console.log('PASS: 인코딩·디코딩 왕복(특수문자·이모지·0 좌표·좌표 없음, 7자리 반올림, 결과 화면 주소 형식)');
}

// --- 즐겨찾기·기록 화면 탭
{
  assert.equal(L.savedTabFromQuery('?tab=favorites'), 'favorites');
  assert.equal(L.savedTabFromQuery('?tab=history'), 'history');
  assert.equal(L.savedTabFromQuery(new URLSearchParams('tab=history')), 'history');
  for (const query of ['', '?', '?tab=', '?tab=History', '?tab=HISTORY', '?tab=history%20', '?tab=stats', '?tab=<script>', '?tab=favorites&tab=history', '?tabs=history']) {
    assert.equal(L.savedTabFromQuery(query), 'favorites', `무효 → 기본 탭: ${query}`);
  }
  assert.equal(L.savedTabFromQuery(undefined), 'favorites');
  assert.equal(L.savedPageUrl('favorites'), '/pages/favorites.html?tab=favorites');
  assert.equal(L.savedPageUrl('history'), '/pages/favorites.html?tab=history');
  assert.equal(L.savedPageUrl('nope'), '/pages/favorites.html?tab=favorites');
  // 즐겨찾기 화면은 이 함수로 탭을 고른다 (잘못된 값은 기본 탭)
  const favorites = await read('../js/pages/favorites.js');
  assert.match(favorites, /let tab = savedTabFromQuery\(location\.search\);/);
  assert.match(favorites, /import \{ savedTabFromQuery \} from "\/js\/links\.js";/);
  console.log('PASS: 탭 쿼리(favorites·history 유효, 빈 값·대소문자·공백·중복·다른 이름 → 기본 탭), 화면 연결');
}
