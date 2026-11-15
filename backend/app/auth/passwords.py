"""bcrypt 비밀번호 해시. 평문 비밀번호는 이 모듈 밖으로 저장되지 않는다."""

import threading

import bcrypt

DEFAULT_ROUNDS = 12  # docs/api-spec.md: cost 12 이상
MAX_BYTES = 72


class PasswordHasher:
    """해시와 비교. 계정이 없거나 소셜 전용 계정이어도 더미 해시와 한 번 비교해 응답 시간을 맞춘다.

    테스트는 rounds를 낮춰 빠르게 돌린다. 운영 코드는 기본값(12)을 쓴다.
    """

    def __init__(self, rounds: int = DEFAULT_ROUNDS) -> None:
        self.rounds = rounds
        self._dummy_hash: bytes | None = None
        self._lock = threading.Lock()

    @property
    def dummy_hash(self) -> bytes:
        # 같은 cost로 만든 해시여야 비교 시간이 실제 계정과 같다. 처음 쓸 때 한 번 만든다 (앱 시작을 늦추지 않는다).
        with self._lock:
            if self._dummy_hash is None:
                self._dummy_hash = bcrypt.hashpw(b"gilit-dummy-password-0", bcrypt.gensalt(self.rounds))
            return self._dummy_hash

    def hash(self, password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(self.rounds)).decode("ascii")

    def verify(self, password: str, password_hash: str | None) -> bool:
        """맞으면 True. password_hash가 None(계정 없음·소셜 전용)이어도 bcrypt 비교를 한 번 한다."""
        encoded = password.encode("utf-8")
        if password_hash is None or len(encoded) > MAX_BYTES:
            # 72바이트를 넘는 비밀번호는 가입 검증을 통과할 수 없으므로 어떤 해시와도 맞지 않는다.
            self._compare(b"gilit-dummy-password-1", self.dummy_hash)
            return False
        return self._compare(encoded, password_hash.encode("ascii"))

    @staticmethod
    def _compare(password: bytes, password_hash: bytes) -> bool:
        try:
            return bcrypt.checkpw(password, password_hash)
        except ValueError:  # 저장된 값이 bcrypt 형식이 아닌 경우
            return False
