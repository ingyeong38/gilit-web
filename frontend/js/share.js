// 경로 공유 링크. 서버에 저장하지 않고, 사용자가 입력·선택한 검색 조건만 결과 화면 주소에 담는다.
// 링크를 열면 결과 화면이 /api/routes로 항상 실시간 재계산한다 (경로·소요시간·AI 요약 값은 링크에 넣지 않는다).
// 장소 형식과 검증은 links.js(readPlaceParams·placeToParams)를 그대로 쓴다. 틀린 장소는 링크에 넣지 않는다.
// 읽은 값은 화면에 value·textContent로만 넣는다 (innerHTML 금지).
import { placeToParams, readPlaceParams } from "/js/links.js";
import { isValidDate, isValidTime, toIsoTime } from "/js/utils.js";

export const RESULT_PATH = "/pages/result.html";
export const SEARCH_PATH = "/pages/search.html";
export const SHARE_BUFFERS = ["0", "5", "10", "15"]; // 검색 화면 여유시간 버튼과 같다
// 출발지 입력칸에 현재 위치(geolocation)를 채울 때 쓰는 이름. 이 이름이면 출발지를 링크에 담지 않는다 (위치 노출 방지).
export const CURRENT_LOCATION_NAME = "현재 위치";
// 결과 화면 → 길찾기 화면: 도착 시각이 지나 다시 고르게 할 때의 안내 표시
export const NOTICE_PARAM = "notice";
export const ARRIVAL_PASSED_NOTICE = "arrival-passed";

function toQuery(query) {
  return query instanceof URLSearchParams ? query : new URLSearchParams(query ?? "");
}

// 장소 하나를 links.js로 읽고 다시 만든다. 틀리면 null.
function placeParams(query, prefix) {
  const place = readPlaceParams(query, prefix);
  return place ? placeToParams(prefix, place) : null;
}

function bufferParam(query) {
  const buffer = query.get("buffer");
  return SHARE_BUFFERS.includes(buffer) ? buffer : null;
}

export function isCurrentLocationOrigin(query) {
  return toQuery(query).get("from")?.trim() === CURRENT_LOCATION_NAME;
}

// 결과 화면 쿼리 → 공유 링크. 화이트리스트: from*/to*(이름·좌표·주소), date(YYYY-MM-DD), time(HH:MM), buffer.
// 출발지가 현재 위치면 출발지를 통째로 뺀다 (받는 사람이 직접 입력). 결과: { url, originOmitted } 또는 null(공유할 수 없는 조건).
export function buildShareLink(query, { origin } = {}) {
  const params = toQuery(query);
  const originOmitted = isCurrentLocationOrigin(params);
  const from = originOmitted ? {} : placeParams(params, "from");
  const to = placeParams(params, "to");
  const date = params.get("date");
  const time = params.get("time");
  const buffer = bufferParam(params);
  if (!from || !to || !isValidDate(date) || !isValidTime(time) || buffer === null) return null;
  if (!originOmitted && from.from === to.to) return null;
  const search = new URLSearchParams({ ...from, ...to, date, time, buffer });
  return { url: `${origin ?? ""}${RESULT_PATH}?${search}`, originOmitted };
}

// 도착 희망 시각(한국 시간)이 지금 이전인지. 날짜·시각 형식이 틀리면 false (형식 오류는 기존 안내가 처리한다).
export function isArrivalPassed({ date, time } = {}, now = new Date()) {
  if (!isValidDate(date) || !isValidTime(time)) return false;
  return Date.parse(toIsoTime(date, time)) <= now.getTime();
}

// 도착 시각이 지난 링크 → 길찾기 화면. 장소·여유시간은 채우고 날짜·시각은 빼서 다시 고르게 한다.
export function retimeSearchUrl(query) {
  const params = toQuery(query);
  const search = new URLSearchParams({
    ...(isCurrentLocationOrigin(params) ? {} : placeParams(params, "from") ?? {}),
    ...(placeParams(params, "to") ?? {}),
  });
  const buffer = bufferParam(params);
  if (buffer !== null) search.set("buffer", buffer);
  search.set(NOTICE_PARAM, ARRIVAL_PASSED_NOTICE);
  return `${SEARCH_PATH}?${search}`;
}

// 클립보드 복사. navigator.clipboard(보안 컨텍스트) → execCommand("copy") 순서로 시도한다.
// 성공하면 쓴 방법("clipboard" | "execCommand"), 둘 다 실패하면 던진다 (화면은 선택 가능한 입력창을 보여 준다).
export async function copyText(text, { clipboard, secure = false, execCopy } = {}) {
  if (clipboard && secure) {
    try {
      await clipboard.writeText(text);
      return "clipboard";
    } catch {
      // 권한 거부 등. 아래 대체 수단으로 넘어간다.
    }
  }
  if (execCopy && execCopy(text)) return "execCommand";
  throw new Error("복사 실패");
}

export function copiedMessage(originOmitted) {
  return originOmitted ? "링크를 복사했어요. 현재 위치는 링크에 담지 않았어요" : "링크를 복사했어요";
}
