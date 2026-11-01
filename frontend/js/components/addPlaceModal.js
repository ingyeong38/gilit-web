import { icon } from "/js/components/icon.js";
import { openModal } from "/js/components/modal.js";

const TYPES = ["집", "학교", "회사", "기타"];

export function openAddPlaceModal({ onAdd }) {
  const { element, close } = openModal({
    className: "modal place-modal",
    content: `
      <span class="place-modal-icon">${icon("location", { size: 23 })}</span>
      <div class="modal-title">즐겨찾기 장소 추가</div>
      <p>자주 방문하는 장소를 저장하고 빠르게 길을 찾아보세요.</p>
      <label class="field modal-field"><span>장소 이름</span><div class="input-wrap">${icon("star", { size: 18 })}<input name="name" placeholder="예: 집, 학교, 회사" /></div></label>
      <label class="field modal-field"><span>주소 또는 장소</span><div class="input-wrap">${icon("search", { size: 18 })}<input name="address" placeholder="장소를 검색하세요" /></div></label>
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

  const nameInput = element.querySelector('[name="name"]');
  const addressInput = element.querySelector('[name="address"]');
  const saveButton = element.querySelector('[data-action="save"]');
  const typeButtons = element.querySelectorAll("[data-type]");
  let selectedType = "기타";

  const updateSaveButton = () => {
    saveButton.disabled = !nameInput.value.trim() || !addressInput.value.trim();
  };
  nameInput.addEventListener("input", updateSaveButton);
  addressInput.addEventListener("input", updateSaveButton);

  typeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      selectedType = button.dataset.type;
      typeButtons.forEach((other) => other.classList.toggle("active", other === button));
    });
  });

  element.querySelector('[data-action="cancel"]').addEventListener("click", close);
  saveButton.addEventListener("click", () => {
    onAdd({ name: nameInput.value.trim(), address: addressInput.value.trim(), type: selectedType });
    close();
  });

  nameInput.focus();
}
