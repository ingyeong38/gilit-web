import { ApiError, loginWithEmail, signup } from "/js/api.js";
import { login as loginWithProvider, setUser } from "/js/auth.js";
import { icon } from "/js/components/icon.js";
import { openModal } from "/js/components/modal.js";

// 서버 검증 규칙과 같다 (docs/api-spec.md). 바꾸면 함께 고친다.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const NAME_MIN = 2;
const NAME_MAX = 20;
const PASSWORD_MIN = 8;
const PASSWORD_MAX = 64;

const GOOGLE_LOGO = `<svg width="22" height="22" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>`;
const KAKAO_LOGO = `<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><path fill="#000" fill-opacity=".9" d="M12 3.5c-5.25 0-9.5 3.35-9.5 7.48 0 2.67 1.78 5.02 4.46 6.34l-.9 3.32c-.08.29.25.52.5.36l3.96-2.62c.48.06.97.09 1.48.09 5.25 0 9.5-3.35 9.5-7.49S17.25 3.5 12 3.5Z"/></svg>`;

function field({ name, label, type = "text", iconName, placeholder, autocomplete }) {
  const id = `auth-${name}`;
  const toggle = type === "password"
    ? `<button class="password-toggle" type="button" aria-label="비밀번호 보기" aria-pressed="false">${icon("eye", { size: 18 })}</button>`
    : "";
  return `
    <div class="field auth-field">
      <label class="field-label" for="${id}">${label}</label>
      <div class="input-wrap">
        ${icon(iconName, { size: 18 })}
        <input id="${id}" name="${name}" type="${type}" placeholder="${placeholder}" autocomplete="${autocomplete}" data-rule="${name}" aria-describedby="${id}-error" />
        ${toggle}
      </div>
      <p class="field-error" id="${id}-error" data-error="${name}" hidden></p>
    </div>
  `;
}

const LOGIN_VIEW = `
  <div class="modal-logo">${icon("route", { size: 26 })}</div>
  <div class="modal-title" id="auth-title">길잇</div>
  <p>로그인하고 즐겨찾기와 이동 기록을<br />어디서든 편리하게 확인하세요.</p>
  <form class="auth-form" novalidate>
    ${field({ name: "email", label: "이메일", type: "email", iconName: "mail", placeholder: "example@email.com", autocomplete: "email" })}
    ${field({ name: "password", label: "비밀번호", type: "password", iconName: "lock", placeholder: "비밀번호를 입력하세요", autocomplete: "current-password" })}
    <p class="form-notice" role="status" hidden></p>
    <p class="form-error" role="alert" hidden></p>
    <button class="btn btn-primary auth-submit" type="submit">로그인</button>
  </form>
  <div class="auth-switch">아직 계정이 없으신가요?<button type="button" data-view="signup">회원가입</button></div>
  <div class="auth-divider">또는</div>
  <div class="social-row">
    <button class="social-circle google" type="button" data-provider="google" aria-label="Google로 로그인">${GOOGLE_LOGO}</button>
    <button class="social-circle kakao" type="button" data-provider="kakao" aria-label="카카오로 로그인">${KAKAO_LOGO}</button>
  </div>
  <small>계속하면 서비스 이용약관 및 개인정보 처리방침에 동의하게 됩니다.</small>
`;

const SIGNUP_VIEW = `
  <div class="modal-logo">${icon("route", { size: 26 })}</div>
  <div class="modal-title" id="auth-title">회원가입</div>
  <p>길잇 계정을 만들고 즐겨찾기와 이동 기록을<br />어디서든 편리하게 확인하세요.</p>
  <form class="auth-form" novalidate>
    ${field({ name: "nickname", label: "이름(닉네임)", iconName: "user", placeholder: `${NAME_MIN}~${NAME_MAX}자`, autocomplete: "nickname" })}
    ${field({ name: "email", label: "이메일", type: "email", iconName: "mail", placeholder: "example@email.com", autocomplete: "email" })}
    ${field({ name: "password", label: "비밀번호", type: "password", iconName: "lock", placeholder: "영문·숫자 포함 8자 이상", autocomplete: "new-password" })}
    ${field({ name: "passwordConfirm", label: "비밀번호 확인", type: "password", iconName: "lock", placeholder: "비밀번호를 한 번 더 입력하세요", autocomplete: "new-password" })}
    <div class="auth-agree" role="group" aria-label="약관 동의">
      <label class="auth-check"><input type="checkbox" name="agreeTerms" data-rule="agree" aria-describedby="auth-agree-error" /><span><b>[필수]</b> 서비스 이용약관 동의</span></label>
      <label class="auth-check"><input type="checkbox" name="agreePrivacy" data-rule="agree" aria-describedby="auth-agree-error" /><span><b>[필수]</b> 개인정보 처리방침 동의</span></label>
    </div>
    <p class="field-error" id="auth-agree-error" data-error="agree" hidden></p>
    <p class="form-error" role="alert" hidden></p>
    <button class="btn btn-primary auth-submit" type="submit">가입하기</button>
  </form>
  <div class="auth-switch">이미 계정이 있으신가요?<button type="button" data-view="login">로그인</button></div>
`;

const required = (message) => (form, name) => (form.elements[name].value.trim() ? "" : message);

function checkEmail(form) {
  const email = form.elements.email.value.trim();
  if (!email) return "이메일을 입력해 주세요.";
  return EMAIL_PATTERN.test(email) ? "" : "올바른 이메일 형식이 아닙니다.";
}

// 로그인에서는 비밀번호 형식을 따지지 않는다. 틀린 경우는 서버가 하나의 문구로 알려 준다.
const LOGIN_RULES = {
  email: checkEmail,
  password: required("비밀번호를 입력해 주세요."),
};

const SIGNUP_RULES = {
  nickname(form) {
    const name = form.elements.nickname.value.trim();
    if (!name) return "이름을 입력해 주세요.";
    return name.length < NAME_MIN || name.length > NAME_MAX ? `이름은 ${NAME_MIN}~${NAME_MAX}자로 입력해 주세요.` : "";
  },
  email: checkEmail,
  password(form) {
    const password = form.elements.password.value;
    if (!password) return "비밀번호를 입력해 주세요.";
    if (password.length < PASSWORD_MIN || password.length > PASSWORD_MAX) {
      return `비밀번호는 ${PASSWORD_MIN}~${PASSWORD_MAX}자로 입력해 주세요.`;
    }
    return /[A-Za-z]/.test(password) && /\d/.test(password) ? "" : "비밀번호에 영문과 숫자를 모두 포함해 주세요.";
  },
  passwordConfirm(form) {
    const confirm = form.elements.passwordConfirm.value;
    if (!confirm) return "비밀번호를 한 번 더 입력해 주세요.";
    return confirm === form.elements.password.value ? "" : "비밀번호가 일치하지 않습니다.";
  },
  agree(form) {
    const { agreeTerms, agreePrivacy } = form.elements;
    return agreeTerms.checked && agreePrivacy.checked ? "" : "필수 약관에 모두 동의해 주세요.";
  },
};

// 처음 제출할 때 모든 칸을 검사하고, 그 뒤로는 입력할 때마다 다시 검사한다.
function setupForm(form, rules, onSubmit) {
  const formError = form.querySelector(".form-error");
  const button = form.querySelector('[type="submit"]');
  let submitted = false;

  const check = (name) => {
    const message = rules[name](form, name);
    const error = form.querySelector(`[data-error="${name}"]`);
    error.textContent = message;
    error.hidden = !message;
    form.querySelectorAll(`[data-rule="${name}"]`).forEach((input) => {
      input.setAttribute("aria-invalid", String(Boolean(message)));
    });
    return !message;
  };

  form.addEventListener("input", () => {
    if (submitted) Object.keys(rules).forEach(check);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submitted = true;
    const invalid = Object.keys(rules).filter((name) => !check(name));
    if (invalid.length) {
      form.querySelector(`[data-rule="${invalid[0]}"]`).focus();
      return;
    }

    formError.hidden = true;
    button.disabled = true;
    try {
      await onSubmit();
    } catch (error) {
      const fromServer = error instanceof ApiError && error.status < 500;
      formError.textContent = fromServer ? error.message : "잠시 후 다시 시도해 주세요.";
      formError.hidden = false;
    } finally {
      button.disabled = false;
    }
  });
}

function bindPasswordToggles(root) {
  root.querySelectorAll(".password-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const input = button.parentElement.querySelector("input");
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-pressed", String(show));
      button.innerHTML = icon(show ? "eyeOff" : "eye", { size: 18 });
    });
  });
}

// view: "login" | "signup". 로그인에 성공하면 사용자 정보를 저장하고 onLogin을 부른다.
// onDismiss는 로그인하지 않고 닫았을 때(X, 배경 클릭, Esc) 불린다.
export function openAuthModal({ view = "login", onLogin, onDismiss }) {
  const { element, close } = openModal({ className: "modal auth-modal", content: "", onDismiss });
  const modal = element.querySelector(".modal");
  modal.setAttribute("aria-labelledby", "auth-title");

  const finishLogin = () => {
    close();
    onLogin?.();
  };

  const render = (nextView, { email = "", notice = "" } = {}) => {
    modal.querySelectorAll(":scope > :not(.modal-close)").forEach((child) => child.remove());
    modal.insertAdjacentHTML("beforeend", nextView === "signup" ? SIGNUP_VIEW : LOGIN_VIEW);
    modal.scrollTop = 0;

    const form = modal.querySelector(".auth-form");
    bindPasswordToggles(form);
    modal.querySelector("[data-view]").addEventListener("click", (event) => {
      render(event.currentTarget.dataset.view);
    });

    if (nextView === "signup") {
      setupForm(form, SIGNUP_RULES, async () => {
        const user = await signup({
          name: form.elements.nickname.value.trim(),
          email: form.elements.email.value.trim(),
          password: form.elements.password.value,
          agreeTerms: form.elements.agreeTerms.checked,
          agreePrivacy: form.elements.agreePrivacy.checked,
        });
        render("login", { email: user.email, notice: "가입이 완료되었어요. 로그인해 주세요." });
      });
      form.elements.nickname.focus();
      return;
    }

    setupForm(form, LOGIN_RULES, async () => {
      const user = await loginWithEmail({
        email: form.elements.email.value.trim(),
        password: form.elements.password.value,
      });
      setUser(user);
      finishLogin();
    });
    modal.querySelectorAll("[data-provider]").forEach((button) => {
      button.addEventListener("click", () => {
        loginWithProvider(button.dataset.provider);
        finishLogin();
      });
    });

    form.elements.email.value = email;
    if (notice) {
      const noticeEl = form.querySelector(".form-notice");
      noticeEl.textContent = notice;
      noticeEl.hidden = false;
    }
    (email ? form.elements.password : form.elements.email).focus();
  };

  render(view);
}
