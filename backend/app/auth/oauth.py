"""소셜 로그인 제공자 (OAuth 2.0 인가 코드. Google은 PKCE S256, 카카오는 state만 — KakaoOAuthClient 참고).

OAuthClient 인터페이스 하나로 제공자를 붙인다 (GoogleOAuthClient, KakaoOAuthClient, 개발용 MockOAuthClient).
웹 흐름(state 쿠키, 콜백, 계정 처리)은 제공자와 무관하다 (app/api/oauth.py, AuthService.social_login).

비밀 값(client secret, 인가 코드, 토큰)은 예외 메시지와 로그에 넣지 않는다.
"""

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode

import requests

logger = logging.getLogger("app.auth.oauth")

HTTP_TIMEOUT_SEC = 5


class OAuthError(Exception):
    """제공자와의 통신 실패 (토큰 교환·프로필 조회). 메시지는 로그용이고 비밀 값을 담지 않는다."""


@dataclass(frozen=True)
class OAuthProfile:
    provider: str  # google | kakao
    subject: str  # 제공자의 사용자 고유 ID (Google sub, 카카오 회원번호). 계정은 이것으로 찾는다
    email: str | None  # 제공자가 준 이메일 (검증 여부는 email_verified)
    email_verified: bool
    name: str | None = field(default=None)


class OAuthClient(Protocol):
    provider: str

    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        """사용자를 보낼 제공자 인증 화면 주소."""
        ...

    def fetch_profile(self, code: str, code_verifier: str, redirect_uri: str) -> OAuthProfile:
        """인가 코드를 토큰으로 바꾸고 프로필을 가져온다. 실패하면 OAuthError."""
        ...


# --- PKCE (RFC 7636) ---


def new_code_verifier() -> str:
    return secrets.token_urlsafe(48)  # 64자. RFC 7636: 43~128자


def code_challenge_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# --- Google ---


class GoogleOAuthClient:
    """Google OpenID Connect. 인가 코드를 서버에서 직접 TLS로 교환하므로 ID 토큰 서명 검증 대신 userinfo를 쓴다."""

    provider = "google"
    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
    SCOPE = "openid email profile"

    def __init__(self, client_id: str, client_secret: str, session: requests.Session | None = None) -> None:
        self.client_id = client_id
        self._client_secret = client_secret
        self._session = session or requests.Session()

    def __repr__(self) -> str:  # client secret이 찍히지 않게 한다
        return "GoogleOAuthClient()"

    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": self.SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",  # 여러 구글 계정 중 고를 수 있게 한다
        }
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"

    def fetch_profile(self, code: str, code_verifier: str, redirect_uri: str) -> OAuthProfile:
        token = _post_form(
            self._session,
            self.TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            "Google 토큰 교환",
        )
        info = _get_bearer(self._session, self.USERINFO_URL, _access_token(token, "Google"), "Google 프로필 조회")
        subject = info.get("sub")
        if not isinstance(subject, str) or not subject:
            raise OAuthError("Google 프로필에 sub가 없습니다.")
        email = info.get("email") if isinstance(info.get("email"), str) else None
        return OAuthProfile(
            provider=self.provider,
            subject=subject,
            email=email,
            email_verified=_is_true(info.get("email_verified")),
            name=info.get("name") if isinstance(info.get("name"), str) else None,
        )


# --- 카카오 ---


class KakaoOAuthClient:
    """카카오 로그인 (REST API).

    PKCE는 쓰지 않는다. 카카오 로그인 REST API 문서(developers.kakao.com/docs/latest/ko/kakaologin/rest-api,
    2026-11 확인)의 인가 코드 받기에 code_challenge·code_challenge_method가 없고, 토큰 받기에도 code_verifier가
    없다. 문서에 없는 파라미터는 무시되거나 오류가 날 수 있어 보내지 않는다. 대신 state 서명 쿠키 검사(공용 흐름)와
    client_secret(카카오 기본값 [ON]이면 필수)으로 인가 코드 가로채기·로그인 CSRF를 막는다.
    공용 흐름은 PKCE 값을 넘겨주지만 이 클라이언트는 받기만 하고 쓰지 않는다.
    """

    provider = "kakao"
    AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
    TOKEN_URL = "https://kauth.kakao.com/oauth/token"
    USER_URL = "https://kapi.kakao.com/v2/user/me"
    FORM = "application/x-www-form-urlencoded;charset=utf-8"  # 카카오 문서가 요구하는 Content-Type

    def __init__(self, client_id: str, client_secret: str, session: requests.Session | None = None) -> None:
        self.client_id = client_id  # 카카오 앱의 REST API 키
        self._client_secret = client_secret
        self._session = session or requests.Session()

    def __repr__(self) -> str:
        return "KakaoOAuthClient()"

    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        # code_challenge는 쓰지 않는다 (위 설명). 동의항목은 카카오 콘솔 설정을 따르므로 scope도 보내지 않는다.
        params = {"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect_uri, "state": state}
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"

    def fetch_profile(self, code: str, code_verifier: str, redirect_uri: str) -> OAuthProfile:
        token = _post_form(
            self._session,
            self.TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
            "카카오 토큰 교환",
            headers={"Content-Type": self.FORM},
        )
        info = _get_bearer(
            self._session, self.USER_URL, _access_token(token, "카카오"), "카카오 프로필 조회", headers={"Content-Type": self.FORM}
        )
        return self.profile_from(info)

    @classmethod
    def profile_from(cls, info: dict) -> OAuthProfile:
        """/v2/user/me 응답을 프로필로 바꾼다.

        - id(Long, 회원번호)를 provider_user_id로 쓴다.
        - 이메일은 is_email_valid와 is_email_verified가 모두 참일 때만 검증된 것으로 본다. is_email_valid=false는
          다른 카카오계정이 그 이메일을 가져가 만료된 경우다.
        - 닉네임은 kakao_account.profile.nickname. properties.nickname은 카카오가 폐기 예정으로 공지해 쓰지 않는다.
        """
        subject = info.get("id")
        if isinstance(subject, bool) or not isinstance(subject, (int, str)) or not str(subject).strip():
            raise OAuthError("카카오 프로필에 회원번호(id)가 없습니다.")
        account = info.get("kakao_account") if isinstance(info.get("kakao_account"), dict) else {}
        profile = account.get("profile") if isinstance(account.get("profile"), dict) else {}
        email = account.get("email") if isinstance(account.get("email"), str) else None
        verified = account.get("is_email_valid") is True and account.get("is_email_verified") is True
        nickname = profile.get("nickname") if isinstance(profile.get("nickname"), str) else None
        return OAuthProfile(
            provider=cls.provider, subject=str(subject).strip(), email=email, email_verified=verified, name=nickname
        )


# --- 공용 HTTP ---


def _post_form(session, url: str, data: dict, step: str, headers: dict | None = None) -> dict:
    kwargs = {"data": data, "timeout": HTTP_TIMEOUT_SEC}
    if headers:
        kwargs["headers"] = headers
    try:
        response = session.post(url, **kwargs)
    except requests.RequestException as error:
        raise OAuthError(f"{step} 연결 실패: {type(error).__name__}") from None
    return _json_or_error(response, step)


def _get_bearer(session, url: str, access_token: str, step: str, headers: dict | None = None) -> dict:
    try:
        response = session.get(
            url, headers={"Authorization": f"Bearer {access_token}", **(headers or {})}, timeout=HTTP_TIMEOUT_SEC
        )
    except requests.RequestException as error:
        raise OAuthError(f"{step} 연결 실패: {type(error).__name__}") from None
    return _json_or_error(response, step)


def _access_token(token: dict, label: str) -> str:
    access_token = token.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthError(f"{label} 토큰 응답에 access_token이 없습니다.")
    return access_token


def _json_or_error(response, step: str) -> dict:
    if response.status_code != 200:
        # 응답 본문(error_description 등)에 코드 일부가 들어올 수 있어 상태 코드만 남긴다.
        raise OAuthError(f"{step} 실패: HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise OAuthError(f"{step} 응답이 JSON이 아닙니다.") from None
    if not isinstance(body, dict):
        raise OAuthError(f"{step} 응답 형식이 올바르지 않습니다.")
    return body


def _is_true(value) -> bool:
    # Google userinfo는 불리언이지만, 일부 응답은 문자열 "true"를 준다.
    return value is True or (isinstance(value, str) and value.lower() == "true")


# --- 개발용 Mock (OAUTH_MOCK=1, AUTH_STORE=memory에서만) ---

MOCK_CODE = "mock-code"


class MockOAuthClient:
    """외부 호출 없이 소셜 로그인 흐름을 시험한다. start가 곧바로 콜백으로 보내고 고정 프로필을 돌려준다.

    google은 검증된 이메일이 있는 프로필, kakao는 이메일 없는 프로필이다 (카카오는 이메일 동의를 받지 않는 경우가
    흔해서 개발 중에도 email NULL 가입 경로를 지나가게 한다).
    """

    def __init__(self, provider: str) -> None:
        self.provider = provider
        has_email = provider != "kakao"
        self.profile = OAuthProfile(
            provider=provider,
            subject=f"mock-{provider}-user",
            email=f"mock.{provider}@example.com" if has_email else None,
            email_verified=has_email,
            name=f"Mock {provider} 사용자",
        )

    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        # 제공자 화면을 건너뛰고 우리 콜백으로 바로 보낸다 (redirect_uri는 OAUTH_REDIRECT_BASE가 없으면 상대 경로).
        return f"{redirect_uri}?{urlencode({'code': MOCK_CODE, 'state': state})}"

    def fetch_profile(self, code: str, code_verifier: str, redirect_uri: str) -> OAuthProfile:
        if code != MOCK_CODE:
            raise OAuthError("Mock 인가 코드가 올바르지 않습니다.")
        return self.profile
