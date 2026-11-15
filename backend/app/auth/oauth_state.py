"""OAuth state 쿠키 (gilit_oauth). 서버 저장소 없이 HMAC(SECRET_KEY)으로 서명한다.

쿠키 값: base64url(JSON {p: provider, s: state, v: PKCE verifier, e: 만료 epoch초}) + "." + base64url(HMAC-SHA256)
- 서명이 맞아야 내용을 읽는다 (위조 방지). 서명 비교와 state 비교는 hmac.compare_digest로 한다.
- 만료 10분, provider가 콜백 경로와 같아야 한다.
- 한 번 쓴 state는 만료될 때까지 다시 받지 않는다 (UsedStates). 프로세스 메모리에 두므로 워커가 여럿이면
  워커별로만 막는다. 인가 코드는 제공자가 한 번만 받아 주므로 재사용 공격은 그쪽에서도 막힌다.
verifier는 서명만 되고 암호화되지 않는다. 쿠키가 HttpOnly이고 verifier만으로는 로그인할 수 없다 (인가 코드도 필요).
"""

import base64
import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import dataclass, field
from datetime import timedelta

STATE_TTL = timedelta(minutes=10)


class OAuthStateError(Exception):
    """state 검사 실패. 메시지는 로그용 사유이고 쿠키 값이나 state를 담지 않는다."""


@dataclass(frozen=True)
class OAuthState:
    provider: str
    state: str
    verifier: str = field(repr=False)
    expires_at: int  # epoch 초


def new_state() -> str:
    return secrets.token_urlsafe(32)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, body: str) -> str:
    return _b64encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())


def encode_state_cookie(secret: str, value: OAuthState) -> str:
    payload = {"p": value.provider, "s": value.state, "v": value.verifier, "e": value.expires_at}
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(secret, body)}"


def decode_state_cookie(
    secret: str, cookie: str | None, provider: str, state: str | None, now_epoch: float
) -> OAuthState:
    """쿠키를 검사하고 내용을 돌려준다. 하나라도 어긋나면 OAuthStateError."""
    if not cookie:
        raise OAuthStateError("state 쿠키 없음")
    if not state:
        raise OAuthStateError("콜백에 state 없음")
    try:
        body, signature = cookie.split(".", 1)
        body.encode("ascii")
        signature.encode("ascii")
    except (ValueError, UnicodeEncodeError):
        raise OAuthStateError("state 쿠키 형식 오류") from None
    if not hmac.compare_digest(_sign(secret, body), signature):
        raise OAuthStateError("state 쿠키 서명 불일치")
    try:
        payload = json.loads(_b64decode(body))
        value = OAuthState(
            provider=str(payload["p"]), state=str(payload["s"]), verifier=str(payload["v"]), expires_at=int(payload["e"])
        )
    except (ValueError, KeyError, TypeError):
        raise OAuthStateError("state 쿠키 내용 오류") from None
    if value.expires_at <= now_epoch:
        raise OAuthStateError("state 쿠키 만료")
    if value.provider != provider:
        raise OAuthStateError("state 쿠키의 제공자 불일치")
    if not hmac.compare_digest(value.state.encode("utf-8"), state.encode("utf-8")):
        raise OAuthStateError("state 불일치")
    return value


class UsedStates:
    """한 번 쓴 state를 만료 시각까지 기억한다 (같은 쿠키·콜백 URL을 다시 보내는 재사용 차단)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._used: dict[str, int] = {}

    def consume(self, value: OAuthState, now_epoch: float) -> bool:
        """처음이면 True(이제 사용됨으로 표시), 이미 썼으면 False."""
        key = hashlib.sha256(value.state.encode("utf-8")).hexdigest()
        with self._lock:
            for old in [k for k, exp in self._used.items() if exp <= now_epoch]:
                del self._used[old]
            if key in self._used:
                return False
            self._used[key] = value.expires_at
            return True
