"""회원가입·로그인 입력 검증 (docs/api-spec.md "검증 규칙").

Pydantic 기본 검증에 맡기지 않고 여기서 직접 검사한다. 공통 오류 변환(app/api/errors.py)은 필드 이름 "name"을
장소 이름으로 보기 때문에, 그대로 두면 회원가입에서 엉뚱한 문구가 나간다.
프론트(frontend/js/components/authModal.js)도 같은 규칙으로 먼저 검사한다. 규칙을 바꾸면 함께 고친다.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.auth.errors import (
    AGREEMENT_REQUIRED,
    EMAIL_INVALID,
    NAME_INVALID,
    PASSWORD_INVALID,
    PASSWORD_REQUIRED,
    AuthError,
)

NAME_MIN = 2
NAME_MAX = 20
EMAIL_MAX = 254
PASSWORD_MIN = 8
PASSWORD_MAX = 64
PASSWORD_MAX_BYTES = 72  # bcrypt는 72바이트까지만 쓴다. 넘으면 bcrypt 5가 ValueError를 낸다

# 프론트의 EMAIL_PATTERN과 같다. fullmatch로 쓰므로 끝의 줄바꿈도 허용하지 않는다.
EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
# \d는 유니코드 숫자(예: 아라비아 숫자 '٣')까지 받으므로 ASCII로 한정한다. 프론트 정규식과 같다.
HAS_LETTER = re.compile(r"[A-Za-z]")
HAS_DIGIT = re.compile(r"[0-9]")


@dataclass(frozen=True)
class SignupInput:
    name: str
    email: str
    password: str = field(repr=False)


@dataclass(frozen=True)
class LoginInput:
    email: str
    password: str = field(repr=False)


def _invalid(message: str) -> AuthError:
    return AuthError(400, message)


def normalize_email(value: Any) -> str:
    """앞뒤 공백을 지우고 소문자로 바꾼다. 형식이 틀리면 400."""
    if not isinstance(value, str):
        raise _invalid(EMAIL_INVALID)
    email = value.strip().lower()
    if not email or len(email) > EMAIL_MAX or not EMAIL_PATTERN.fullmatch(email):
        raise _invalid(EMAIL_INVALID)
    return email


def normalize_name(value: Any) -> str:
    if not isinstance(value, str):
        raise _invalid(NAME_INVALID)
    name = unicodedata.normalize("NFC", value).strip()
    # 제어·서식 문자(줄바꿈, 제로폭 문자 등)는 화면에서 보이지 않거나 레이아웃을 깨뜨린다.
    if not NAME_MIN <= len(name) <= NAME_MAX or any(unicodedata.category(ch).startswith("C") for ch in name):
        raise _invalid(NAME_INVALID)
    return name


def check_new_password(value: Any) -> str:
    if not isinstance(value, str):
        raise _invalid(PASSWORD_INVALID)
    if not (
        PASSWORD_MIN <= len(value) <= PASSWORD_MAX
        and len(value.encode("utf-8")) <= PASSWORD_MAX_BYTES
        and HAS_LETTER.search(value)
        and HAS_DIGIT.search(value)
    ):
        raise _invalid(PASSWORD_INVALID)
    return value  # 비밀번호는 공백 제거 등 변형 없이 그대로 쓴다


def validate_signup(payload: dict[str, Any]) -> SignupInput:
    """프론트와 같은 순서(이름 → 이메일 → 비밀번호 → 약관)로 검사하고 첫 오류를 돌려준다."""
    name = normalize_name(payload.get("name"))
    email = normalize_email(payload.get("email"))
    password = check_new_password(payload.get("password"))
    # 문자열 "true"나 1은 동의로 보지 않는다.
    if payload.get("agreeTerms") is not True or payload.get("agreePrivacy") is not True:
        raise _invalid(AGREEMENT_REQUIRED)
    return SignupInput(name=name, email=email, password=password)


def validate_login(payload: dict[str, Any]) -> LoginInput:
    """로그인은 비밀번호 형식을 따지지 않는다. 틀린 경우는 하나의 401 문구로 알린다."""
    email = normalize_email(payload.get("email"))
    password = payload.get("password")
    if not isinstance(password, str) or not password:
        raise _invalid(PASSWORD_REQUIRED)
    return LoginInput(email=email, password=password)
