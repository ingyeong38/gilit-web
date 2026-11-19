// 화면 사이에 장소·탭을 URL 쿼리로 넘기는 형식. 만들기(build)와 읽기(read)를 한곳에 둔다.
// 장소 형식은 결과 화면 주소(buildResultUrl)·"조건 수정"과 같은 이름을 쓴다: {prefix}, {prefix}Lat, {prefix}Lng, {prefix}Address
// prefix는 "to"(목적지)와 "from"(출발지). 지금 길찾기 화면은 목적지만 이 형식으로 읽는다.
// 경로 공유처럼 출발지까지 넘길 때는 buildSearchUrl({ from, to })와 readPlaceParams(query, "from")을 그대로 쓴다.
// 읽은 값은 화면에 textContent·value로만 넣는다 (innerHTML 금지). 여기서는 문자열 검사만 한다.
// 주소 규칙(255자, 제어 문자 불가)은 utils.js와 같은 함수(placeAddress)를 쓴다.
import { placeAddress } from "/js/utils.js";

export const PLACE_PREFIXES = ["from", "to"];
export const MAX_PLACE_NAME_LENGTH = 100; // 즐겨찾기 이름·검색 기록 장소 이름과 같은 한도 (VARCHAR(100))

const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/;
// 십진수만 (부호 -, 정수부 1~3자리, 소수부 1~20자리). 지수 표기·공백·16진수·"+"는 받지 않는다.
const COORDINATE_TEXT = /^-?\d{1,3}(?:\.\d{1,20})?$/;
const COORDINATE_LIMITS = { Lat: 90, Lng: 180 };

function checkPrefix(prefix) {
  if (!PLACE_PREFIXES.includes(prefix)) throw new Error(`알 수 없는 장소 구분: ${prefix}`);
}

// 장소 이름: 문자열, 앞뒤 공백 제거 후 1~100자, 제어 문자 없음. 아니면 null.
export function placeName(value) {
  if (typeof value !== "string") return null;
  const name = value.trim();
  if (!name || name.length > MAX_PLACE_NAME_LENGTH || CONTROL_CHARS.test(name)) return null;
  return name;
}

function isCoordinate(value, limit) {
  return typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= limit;
}

// 숫자 좌표 → 쿼리 문자열. 소수 7자리(서버 저장 정밀도)까지, 끝의 0은 뺀다. 지수 표기가 나오지 않는다.
export function formatCoordinate(value) {
  return value.toFixed(7).replace(/\.?0+$/, "") || "0";
}

// 쿼리 문자열 → 숫자 좌표. 형식이나 범위가 틀리면 NaN.
export function parseCoordinate(text, limit) {
  if (typeof text !== "string" || !COORDINATE_TEXT.test(text)) return NaN;
  const value = Number(text);
  return Math.abs(value) <= limit ? value : NaN;
}

// 장소 하나 → 쿼리 값 { [prefix]: 이름, [prefix]Lat, [prefix]Lng, [prefix]Address }.
// 이름이 틀리면 null. 좌표는 둘 다 올바를 때만, 주소는 좌표가 있고 형식이 맞을 때만 넣는다
// (readPlaceParams는 좌표 없는 주소를 틀린 것으로 본다).
export function placeToParams(prefix, place = {}) {
  checkPrefix(prefix);
  const name = placeName(place?.name);
  if (!name) return null;
  const params = { [prefix]: name };
  if (isCoordinate(place.lat, 90) && isCoordinate(place.lng, 180)) {
    params[`${prefix}Lat`] = formatCoordinate(place.lat);
    params[`${prefix}Lng`] = formatCoordinate(place.lng);
    const address = placeAddress(place.address);
    if (address) params[`${prefix}Address`] = address;
  }
  return params;
}

// 쿼리에서 장소 하나를 읽는다. 하나라도 틀리면 null (화면은 그 장소를 채우지 않는다).
// - 이름({prefix}) 필수
// - 좌표는 둘 다 있거나 둘 다 없어야 한다. 있으면 형식·범위 검사
// - 주소({prefix}Address)는 없어도 된다. 있으면 형식 검사, 좌표 없이 오면 틀린 것으로 본다
// 돌려주는 값: { name, lat, lng, address? } (좌표가 있음 = 선택 완료 상태로 채울 수 있음) 또는 { name } (이름만)
export function readPlaceParams(query, prefix) {
  checkPrefix(prefix);
  const params = query instanceof URLSearchParams ? query : new URLSearchParams(query ?? "");
  const rawName = params.get(prefix);
  if (rawName === null) return null;
  const name = placeName(rawName);
  if (!name) return null;

  const rawLat = params.get(`${prefix}Lat`);
  const rawLng = params.get(`${prefix}Lng`);
  const rawAddress = params.get(`${prefix}Address`);
  if (rawLat === null && rawLng === null) return rawAddress === null ? { name } : null;
  const lat = parseCoordinate(rawLat, COORDINATE_LIMITS.Lat);
  const lng = parseCoordinate(rawLng, COORDINATE_LIMITS.Lng);
  if (Number.isNaN(lat) || Number.isNaN(lng)) return null;
  if (rawAddress === null) return { name, lat, lng };
  const address = placeAddress(rawAddress);
  return address ? { name, lat, lng, address } : null;
}

// 길찾기 화면 주소. 지금은 목적지(to)만 쓰고, 출발지(from)도 같은 형식으로 받을 수 있다. 틀린 장소는 빼고 만든다.
export function buildSearchUrl(places = {}) {
  const params = {};
  for (const prefix of PLACE_PREFIXES) {
    if (places[prefix]) Object.assign(params, placeToParams(prefix, places[prefix]) ?? {});
  }
  const query = new URLSearchParams(params).toString();
  return `/pages/search.html${query ? `?${query}` : ""}`;
}

// --- 즐겨찾기·기록 화면의 탭 (?tab=favorites | history) ---

export const SAVED_TABS = ["favorites", "history"];
export const DEFAULT_SAVED_TAB = "favorites";

// 알 수 없는 값·빈 값·대소문자 다른 값은 기본 탭(즐겨찾기)
export function savedTabFromQuery(query) {
  const params = query instanceof URLSearchParams ? query : new URLSearchParams(query ?? "");
  const tab = params.get("tab");
  return SAVED_TABS.includes(tab) ? tab : DEFAULT_SAVED_TAB;
}

export function savedPageUrl(tab = DEFAULT_SAVED_TAB) {
  return `/pages/favorites.html?tab=${SAVED_TABS.includes(tab) ? tab : DEFAULT_SAVED_TAB}`;
}
