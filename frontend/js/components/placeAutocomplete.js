import { searchPlaces } from "/js/api.js";
import { escapeHtml } from "/js/utils.js";
import { icon } from "/js/components/icon.js";

// 입력 직후 요청 번호를 바꿔 디바운스 대기 중에도 이전 응답을 무효화한다.
// options.label: 목록의 aria-label (기본: from이면 출발지, 아니면 목적지 검색 결과)
// options.onChange(place | null): 목록에서 고르면 그 장소({ name, address, lat, lng, ... }), 입력을 고쳐 선택이 풀리면 null
export function setupAutocomplete(input, { label, onChange } = {}) {
  const field = input.closest(".field");
  const panel = document.createElement("div");
  panel.className = "autocomplete";
  panel.hidden = true;
  const status = document.createElement("div");
  status.className = "autocomplete-label";
  status.setAttribute("role", "status");
  const list = document.createElement("div");
  list.id = `${input.name}-places`;
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", label ?? (input.name === "from" ? "출발지 검색 결과" : "목적지 검색 결과"));
  panel.append(status, list);
  field.append(panel);
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", list.id);
  input.setAttribute("aria-expanded", "false");
  let requestId = 0, timer, places = [], active = -1;
  let selectedPlace = null;

  function close() {
    ++requestId;
    clearTimeout(timer);
    panel.hidden = true;
    places = [];
    active = -1;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    input.setAttribute("aria-busy", "false");
  }

  function show(message, busy = false) {
    panel.hidden = false;
    status.textContent = message;
    list.replaceChildren();
    places = [];
    active = -1;
    input.removeAttribute("aria-activedescendant");
    input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-busy", String(busy));
  }

  function select(index) {
    if (!places[index]) return;
    selectedPlace = places[index];
    input.value = selectedPlace.name;
    input.focus();
    close();
    onChange?.(selectedPlace);
  }

  async function search(id) {
    const query = input.value.trim();
    if (id !== requestId || !query) return;
    try {
      const results = await searchPlaces(query);
      if (id !== requestId) return;
      if (!Array.isArray(results) || results.some((p) => !p || typeof p.name !== "string" || typeof p.address !== "string")) {
        throw new Error("장소 응답 형식 오류");
      }
      show(results.length ? `검색 결과 ${results.length}개` : "일치하는 장소가 없어요");
      places = results;
      list.innerHTML = results.map((place, index) => `<div role="option" tabindex="-1" aria-selected="false" id="${list.id}-${index}" data-place-index="${index}">
        <span>${icon("location", { size: 17 })}</span><div><b>${escapeHtml(place.name)}</b><small>${escapeHtml(place.address)}</small></div></div>`).join("");
    } catch {
      if (id !== requestId) return;
      show("장소를 검색하지 못했어요. 다시 입력하거나 재시도해 주세요.");
      const retry = document.createElement("button");
      retry.type = "button";
      retry.textContent = "다시 검색";
      retry.addEventListener("click", () => { input.focus(); schedule(); });
      status.append(retry);
    }
  }

  function schedule() {
    close();
    if (!input.value.trim()) return;
    show("검색 중…", true);
    const id = requestId;
    timer = setTimeout(() => search(id), 200);
  }

  function activate(index) {
    active = index;
    const options = list.querySelectorAll('[role="option"]');
    options.forEach((option, i) => option.setAttribute("aria-selected", String(i === index)));
    input.setAttribute("aria-activedescendant", options[index].id);
    options[index].scrollIntoView({ block: "nearest" });
  }

  input.addEventListener("focus", schedule);
  input.addEventListener("input", () => {
    const hadPlace = selectedPlace !== null;
    selectedPlace = null;
    if (hadPlace) onChange?.(null);
    schedule();
  });
  input.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    if (event.key === "Escape") { if (!panel.hidden) event.preventDefault(); close(); return; }
    if (panel.hidden) return;
    if (event.key === "Enter") {
      event.preventDefault(); // 검색 중/결과 없음 상태에서도 폼 제출과 충돌하지 않는다.
      if (active >= 0) select(active);
      else if (places.length) select(0);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (places.length) activate(active < 0 ? (event.key === "ArrowDown" ? 0 : places.length - 1)
        : (active + (event.key === "ArrowDown" ? 1 : -1) + places.length) % places.length);
    } else if (event.key === "Tab") close();
  });
  // 마우스 선택 전에 blur가 목록을 닫지 않게 한다. 터치 스크롤은 방해하지 않는다.
  panel.addEventListener("mousedown", (event) => event.preventDefault());
  panel.addEventListener("click", (event) => {
    const option = event.target.closest("[data-place-index]");
    if (option) { event.preventDefault(); select(Number(option.dataset.placeIndex)); }
  });
  field.addEventListener("focusout", (event) => {
    if (!field.contains(event.relatedTarget)) close();
  });
  const onDocumentPointerDown = (event) => {
    if (!field.contains(event.target)) close();
  };
  document.addEventListener("pointerdown", onDocumentPointerDown);
  return {
    close,
    // 모달처럼 입력칸이 사라지는 곳에서 부른다. 문서에 단 이벤트를 뗀다.
    destroy: () => { close(); document.removeEventListener("pointerdown", onDocumentPointerDown); },
    getPlace: () => selectedPlace?.name === input.value.trim() ? selectedPlace : null,
    setPlace: (place) => { selectedPlace = place; },
  };
}
