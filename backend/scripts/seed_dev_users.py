"""로컬 개발 DB에 이메일 로그인 테스트 계정을 만든다. backend에서 실행한다:

    venv/Scripts/python scripts/seed_dev_users.py                 # 기본 비밀번호 gilit1234
    venv/Scripts/python scripts/seed_dev_users.py --password abcd1234

DB 접속 정보는 .env(DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)에서 읽고 출력하지 않는다.
비밀번호는 서버와 같은 bcrypt(cost 12)로 해시해 저장한다. 이미 있는 계정은 건너뛴다 (비밀번호를 바꾸지 않는다).
운영 DB에 테스트 계정이 들어가지 않도록 DB_HOST가 로컬 주소가 아니면 --allow-remote 없이는 멈춘다.

db/seed.sql의 tester@example.com은 로그인할 수 없는 더미 해시이므로 여기서는 다른 이메일을 쓴다.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.errors import EmailAlreadyExistsError  # noqa: E402
from app.auth.mysql_stores import MySQLUserStore  # noqa: E402
from app.auth.passwords import PasswordHasher  # noqa: E402
from app.auth.validation import check_new_password  # noqa: E402
from app.config import Settings, load_env_files  # noqa: E402
from app.db import ConnectionPool  # noqa: E402
from app.departure import KST  # noqa: E402

DEV_USERS = (
    ("dev1@example.com", "개발테스터1"),
    ("dev2@example.com", "개발테스터2"),
)
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
DEFAULT_PASSWORD = "gilit1234"


def main() -> int:
    parser = argparse.ArgumentParser(description="로컬 개발 DB에 테스트 계정 만들기")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help=f"테스트 계정 비밀번호 (기본 {DEFAULT_PASSWORD})")
    parser.add_argument("--allow-remote", action="store_true", help="DB_HOST가 로컬이 아니어도 실행한다 (개발용 RDS 등)")
    args = parser.parse_args()

    load_env_files()
    settings = Settings.from_env()
    try:
        config = settings.mysql_config()
        check_new_password(args.password)
    except ValueError as error:
        print(error)
        return 1
    except Exception as error:  # AuthError: 비밀번호 규칙 위반
        print(f"비밀번호 규칙: {error}")
        return 1
    if config.host not in LOCAL_HOSTS and not args.allow_remote:
        print("DB_HOST가 로컬 주소가 아닙니다. 운영 DB가 아닌지 확인하고 --allow-remote를 붙여 다시 실행하세요.")
        return 1

    pool = ConnectionPool(config, size=1)
    store = MySQLUserStore(pool)
    hasher = PasswordHasher()
    now = datetime.now(KST)
    print(f"DB: {config.database} (사용자 {config.user})")
    try:
        for email, nickname in DEV_USERS:
            try:
                user = store.create_email_user(email, hasher.hash(args.password), nickname, now)
                print(f"  만듦   id={user.id} {email} ({nickname})")
            except EmailAlreadyExistsError:
                print(f"  있음   {email} (건너뜀, 비밀번호는 바꾸지 않음)")
    finally:
        pool.close()
    print(f"비밀번호: {args.password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
