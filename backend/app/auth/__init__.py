"""회원 인증 (SFR-001). 이메일 가입·로그인과 서버 세션.

- validation.py: 입력 검증 (400 + 명세 문구)
- passwords.py: bcrypt 해시
- stores.py: UserStore / SessionStore 프로토콜과 메모리 구현
- service.py: AuthService (가입, 로그인, 로그아웃, 세션 확인)
- rate_limit.py: 요청 횟수 제한
웹 API와 의존성(require_user, optional_user)은 app/api/auth.py에 있다.
"""

from app.auth.errors import AuthError, EmailAlreadyExistsError
from app.auth.passwords import PasswordHasher
from app.auth.rate_limit import RateLimiter
from app.auth.service import AUTH_STORES, SESSION_TTL, AuthService, CurrentUser, create_auth_service, hash_token
from app.auth.stores import MemorySessionStore, MemoryUserStore, SessionRecord, SessionStore, User, UserStore

__all__ = [
    "AUTH_STORES",
    "SESSION_TTL",
    "AuthError",
    "AuthService",
    "CurrentUser",
    "EmailAlreadyExistsError",
    "MemorySessionStore",
    "MemoryUserStore",
    "PasswordHasher",
    "RateLimiter",
    "SessionRecord",
    "SessionStore",
    "User",
    "UserStore",
    "create_auth_service",
    "hash_token",
]
