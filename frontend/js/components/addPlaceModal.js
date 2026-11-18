import { icon } from "/js/components/icon.js";
import { openModal } from "/js/components/modal.js";
import { setupAutocomplete } from "/js/components/placeAutocomplete.js";
import { escapeHtml } from "/js/utils.js";

const TYPES = ["집", "학교", "회사", "기타"];

// 장소는 자동완성 목록에서 골라야 한다 (서버는 좌표 없는 즐겨찾기를 이름으로 다시 찾다가 400을 낸다).
// 고르면 name·address·lat·lng를 보관하고, 그 뒤 검색어를 고치면 선택이 풀려 다시 골라야 한다.
// 별칭(장소 이름)은 선택 사항이다. 비우면 고른 장소의 이름으로 저장한다.
export function openAddPlaceModal({ onAdd }) {
  let autocomplete;
  const { element, close } = openModal({
    className: "modal place-modal",
    onDismiss: () => autocomplete?.destroy(),
    content: `
      <span class="place-modal-icon">${icon("location", { size: 23 })}</span>
      <div class="modal-title">즐겨찾기 장소 추가</div>
      <p>자주 방문하는 장소를 저장하고 빠르게 길을 찾아보세요.</p>
      <label class="field modal-field"><span>장소 검색</span><div class="input-wrap">${icon("search", { size: 18 })}<input name="place" placeholder="장소나 주소를 검색해 목록에서 선택하세요" autocomplete="off" aria-describedby="place-selected" /></div></label>
      <div class="place-selected" id="place-selected" aria-live="polite">목록에서 장소를 선택해야 저장할 수 있어요.</div>
      <label class="field modal-field"><span>장소 이름 (선택)</span><div class="input-wrap">${icon("star", { size: 18 })}<input name="name" placeholder="예: 집, 학교, 회사 (비우면 장소 이름)" maxlength="100" /></div></label>
      <div class="place-types">
        <span>분류</span>
        <div>${TYPES.map((type) => `<button type="button" data-type="${type}" class="${type === "기타" ? "active" : ""}">${type}</button>`).join("")}</div>
      </div>
      <div class="modal-actions">
        <button class="btn btn-secondary" type="button" data-action="cancel">취소</button>
        <button class="btn btn-primary" type="button" data-action="save" disabled>장소 저장</button>
      </div>
    `,
  });

  const placeInput = element.querySelector('[name="place"]');
  const nameInput = element.querySelector('[name="name"]');
  const selectedText = element.querySelector(".place-selected");
  const saveButton = element.querySelector('[data-action="save"]');
  const typeButtons = element.querySelectorAll("[data-type]");
  let selectedType = "기타";
  let selectedPlace = null;

  const isLocated = (place) => typeof place?.lat === "number" && typeof place?.lng === "number"
    && Number.isFinite(place.lat) && Number.isFinite(place.lng);

  autocomplete = setupAutocomplete(placeInput, {
    label: "즐겨찾기 장소 검색 결과",
    onChange: (place) => {
      selectedPlace = isLocated(place) ? place : null;
      selectedText.classList.toggle("selected", Boolean(selectedPlace));
      selectedText.innerHTML = selectedPlace
        ? `${icon("check", { size: 14 })} ${escapeHtml(selectedPlace.address || selectedPlace.name)}`
        : place ? "위치 정보가 없는 장소예요. 다른 결과를 선택해 주세요." : "목록에서 장소를 선택해야 저장할 수 있어요.";
      saveButton.disabled = !selectedPlace;
    },
  });

  typeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      selectedType = button.dataset.type;
      typeButtons.forEach((other) => other.classList.toggle("active", other === button));
    });
  });

  const finish = () => {
    autocomplete.destroy();
    close();
  };
  element.querySelector('[data-action="cancel"]').addEventListener("click", finish);
  saveButton.addEventListener("click", () => {
    if (!selectedPlace) return;
    const { name: placeName, address, lat, lng } = selectedPlace;
    onAdd({ name: nameInput.value.trim() || placeName, address: address || placeName, type: selectedType, lat, lng });
    finish();
  });

  placeInput.focus();
}
