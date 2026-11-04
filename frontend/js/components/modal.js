import { icon } from "/js/components/icon.js";

// AuthModal, AddPlaceModal이 함께 쓰는 틀. 배경 클릭과 Esc로 닫힌다.
// onDismiss는 사용자가 닫을 때(X, 배경 클릭, Esc)만 불린다. 코드에서 close()로 닫을 때는 불리지 않는다.
export function openModal({ className = "modal", content, onDismiss }) {
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
  const dismiss = () => {
    close();
    onDismiss?.();
  };
  const onKeydown = (event) => {
    if (event.key === "Escape") dismiss();
  };

  backdrop.addEventListener("mousedown", (event) => {
    if (event.target === backdrop) dismiss();
  });
  backdrop.querySelector(".modal-close").addEventListener("click", dismiss);
  window.addEventListener("keydown", onKeydown);
  document.body.append(backdrop);

  return { element: backdrop, close };
}
