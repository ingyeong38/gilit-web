import { icon } from "/js/components/icon.js";
import { escapeHtml } from "/js/utils.js";

let toastEl = null;
let hideTimer = null;

export function showToast(message, { error = false } = {}) {
  if (!toastEl) {
    toastEl = document.createElement("div");
    toastEl.className = "toast";
    toastEl.setAttribute("role", "status");
    document.body.append(toastEl);
  }
  toastEl.innerHTML = `${error ? "" : `<span>${icon("check", { size: 16 })}</span>`}${escapeHtml(message)}`;
  // 새로 만든 요소도 전환 효과가 나도록 다음 프레임에 표시한다.
  requestAnimationFrame(() => toastEl.classList.add("show"));
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => toastEl.classList.remove("show"), 2200);
}
