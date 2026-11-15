-- 001: users.email NULL 허용
-- 카카오 로그인은 이메일을 주지 않거나(동의 안 함) 검증되지 않은 이메일을 줄 수 있다.
-- 소셜 계정은 social_accounts의 (provider, provider_user_id)로 찾으므로 이메일이 없어도 계정을 만들 수 있게 한다.
-- MySQL의 UNIQUE(uq_users_email)는 NULL을 여러 개 허용한다. 이메일이 있는 계정끼리는 계속 하나만 있다.
--
-- 이미 만든 DB(schema.sql을 001 이전에 실행한 DB)에만 실행한다. 새 DB는 schema.sql만 실행하면 된다.
-- 다시 실행해도 결과가 같다 (MODIFY는 같은 정의로 덮어쓴다).
-- 실행 계정: 테이블 구조를 바꾸므로 ALTER 권한이 있는 관리자 계정 (서비스 계정 gilit_app에는 없다)

SET NAMES utf8mb4;

-- schema.sql의 정의와 같게 둔다 (마이그레이션으로 만든 DB와 schema.sql로 새로 만든 DB의 구조가 같아야 한다).
ALTER TABLE users
  MODIFY email VARCHAR(255) NULL;
