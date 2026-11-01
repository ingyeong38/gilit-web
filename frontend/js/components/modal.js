import { icon } from "/js/components/icon.js";

// LoginModal, AddPlaceModal이 함께 쓰는 틀. 배경 클릭과 Esc로 닫힌다.
export function openModal({ className = "modal", content }) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="${className}" role="dialog" aria-modal="true">
      <button class="modal-close" type="button" aria-label="닫기">${icon("close")}</button>
      ${content}
    </div>
  `;

  const close = () => {
    backdrop.remove();
    window.removeEventListener("keydown", onKeydown);
  };
  const onKeydown = (event) => {
    if (event.key === "Escape") close();
  };

  backdrop.addEventListener("mousedown", (event) => {
    if (event.target === backdrop) close();
  });
  backdrop.querySelector(".modal-close").addEventListener("click", close);
  window.addEventListener("keydown", onKeydown);
  document.body.append(backdrop);

  return { element: backdrop, close };
}
