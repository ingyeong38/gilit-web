"""닉네임 변경 검증 (PATCH /api/auth/me, docs/api-spec.md "닉네임 변경").

규칙 (프론트 frontend/js/mypage.js의 NICKNAME_* 상수·validateNickname과 같다. 바꾸면 함께 고친다)
- NFC 정규화 후 앞뒤 공백 제거, 길이 2~20자(글자 수 기준)
- 허용 문자: 한글 완성형(가-힣), 영문(A-Za-z), 숫자(0-9), 공백(스페이스), 특수문자 - _ ! # 만
- 한글·영문·숫자 중 최소 1자 포함, 연속 공백 불허
- 불허: 그 외 문자, 이모지, 한글 자모 단독, 탭·줄바꿈 등 스페이스 이외의 공백 문자
- 중복 닉네임 허용
- 규칙은 변경 요청 값에만 적용한다(기존 닉네임은 검사하지 않는다)

검사 순서와 실패 코드: empty → chars → spaces → length → required (프론트와 같은 순서)
두 쪽의 결과가 같은지는 frontend/tests/fixtures/nickname-cases.json을 pytest와 프론트 테스트가 함께 읽어 확인한다.
"""

import re
import unicodedata
from typing import Any

from app.auth.errors import AuthError

NICKNAME_MIN = 2
NICKNAME_MAX = 20
# fullmatch로 쓴다. 공백은 U+0020만 (탭·줄바꿈·전각 공백·NBSP는 없으므로 불허)
NICKNAME_ALLOWED = re.compile(r"[가-힣A-Za-z0-9 \-_!#]+")
NICKNAME_REQUIRED = re.compile(r"[가-힣A-Za-z0-9]")
NICKNAME_CONSECUTIVE_SPACES = re.compile(r" {2,}")

# 앞뒤에서 지우는 문자. 프론트 String.prototype.trim()과 같은 집합(ECMAScript WhiteSpace + LineTerminator)이다.
# 파이썬 str.strip()은 \x1c-\x1f를 지우고 ﻿는 남겨서 결과가 달라지므로 쓰지 않는다.
TRIM_CHARS = "\t\n\v\f\r                  　﻿"

# 프론트 NICKNAME_MESSAGES와 같은 문장
NICKNAME_MESSAGES = {
    "empty": "닉네임을 입력해 주세요.",
    "length": f"닉네임은 {NICKNAME_MIN}~{NICKNAME_MAX}자로 입력해 주세요.",
    "chars": "사용할 수 없는 문자가 있어요. 한글, 영문, 숫자, 공백, - _ ! #만 쓸 수 있어요.",
    "spaces": "공백은 한 칸씩만 쓸 수 있어요.",
    "required": "한글, 영문, 숫자를 1자 이상 포함해 주세요.",
}


def nickname_error(code: str) -> AuthError:
    return AuthError(400, NICKNAME_MESSAGES[code], code=code)


def normalize_nickname(value: Any) -> str:
    """요청 값을 검사하고 저장할 값(NFC, 앞뒤 공백 제거)을 돌려준다. 어기면 400 AuthError(code 포함)."""
    if not isinstance(value, str):
        raise nickname_error("empty")
    nickname = unicodedata.normalize("NFC", value).strip(TRIM_CHARS)
    if not nickname:
        raise nickname_error("empty")
    if not NICKNAME_ALLOWED.fullmatch(nickname):
        raise nickname_error("chars")
    if NICKNAME_CONSECUTIVE_SPACES.search(nickname):
        raise nickname_error("spaces")
    if not NICKNAME_MIN <= len(nickname) <= NICKNAME_MAX:
        raise nickname_error("length")
    if not NICKNAME_REQUIRED.search(nickname):
        raise nickname_error("required")
    return nickname
