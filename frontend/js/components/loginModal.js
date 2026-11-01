import { icon } from "/js/components/icon.js";
import { openModal } from "/js/components/modal.js";

export function openLoginModal({ onLogin }) {
  const { element, close } = openModal({
    content: `
      <div class="modal-logo">${icon("route", { size: 26 })}</div>
      <div class="modal-title">길잇</div>
      <p>로그인하고 즐겨찾기와 이동 기록을<br />어디서든 편리하게 확인하세요.</p>
      <button class="social-button google" type="button" data-provider="google"><span class="google-g">G</span>Google로 계속하기</button>
      <button class="social-button kakao" type="button" data-provider="kakao"><span class="kakao-bubble">●</span>카카오로 계속하기</button>
      <small>계속하면 서비스 이용약관 및 개인정보 처리방침에 동의하게 됩니다.</small>
    `,
  });

  element.querySelectorAll("[data-provider]").forEach((button) => {
    button.addEventListener("click", () => {
      onLogin(button.dataset.provider);
      close();
    });
  });
}
