"""인증 예외와 사용자에게 보여 줄 문구 (docs/api-spec.md "회원").

AuthError의 message는 그대로 응답 본문 { "message": ... }이 된다. 내부 정보(SQL, 해시, 토큰)를 넣지 않는다.
"""

NAME_INVALID = "이름은 2~20자로 입력해 주세요."
EMAIL_INVALID = "올바른 이메일 형식이 아닙니다."
PASSWORD_INVALID = "비밀번호는 영문과 숫자를 포함해 8~64자로 입력해 주세요."
PASSWORD_REQUIRED = "비밀번호를 입력해 주세요."
AGREEMENT_REQUIRED = "필수 약관에 모두 동의해 주세요."
EMAIL_TAKEN = "이미 가입된 이메일입니다."
LOGIN_FAILED = "이메일 또는 비밀번호가 올바르지 않습니다."
LOGIN_REQUIRED = "로그인이 필요합니다."
TOO_MANY_REQUESTS = "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
ORIGIN_FORBIDDEN = "허용되지 않은 출처의 요청입니다."


class AuthError(Exception):
    """인증 처리 중 사용자에게 알려야 하는 실패. status와 message로 응답한다."""

    def __init__(self, status: int, message: str, headers: dict[str, str] | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = headers
        self.code = code  # 프론트가 문구를 고를 때 쓰는 실패 코드 (닉네임 검증 등). 없으면 응답에 넣지 않는다


class EmailAlreadyExistsError(Exception):
    """저장소가 이메일 UNIQUE 위반을 알릴 때 쓴다 (MySQL은 오류 1062)."""


class SocialAccountExistsError(Exception):
    """같은 (provider, provider_user_id)가 이미 연결돼 있을 때 (동시 첫 로그인). 다시 조회해서 로그인한다."""


class SocialEmailConflictError(Exception):
    """소셜 첫 로그인의 검증된 이메일이 기존 계정과 겹친다. 계정을 만들거나 연결하지 않는다 (설계 3-2)."""
