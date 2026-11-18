-- 004: search_history.user_id NOT NULL (검색 기록은 로그인 사용자 것만)
--   1. FK fk_history_user를 ON DELETE SET NULL에서 ON DELETE CASCADE로 바꾼다 (탈퇴하면 그 사용자의 기록도 지운다)
--   2. user_id를 BIGINT NOT NULL로 바꾼다
--   서버(backend/app/history/)는 이 변경과 함께 비로그인 검색을 저장하지 않고, 삭제·200개 상한을 DELETE로 처리한다.
--
-- ▶ 적용 전 확인 쿼리: user_id가 NULL인 행(비로그인 검색, 예전 방식으로 분리된 기록)이 있으면 2번에서 실패한다
--   (Data truncated / Invalid use of NULL value). 결과가 0이어야 한다.
--
--     SELECT COUNT(*) AS null_rows FROM search_history WHERE user_id IS NULL;
--
--   0이 아니면 먼저 그 행을 지운다. 로컬 개발 DB(gilit, gilit_test)에서만 한다.
--   운영 RDS는 이 변경이 들어간 schema.sql로 새로 만든 DB라 NULL 행이 없다 (위 확인 쿼리로 0인지만 본다).
--
--     DELETE FROM search_history WHERE user_id IS NULL;
--
-- ▶ 다시 실행해도 된다. 각 단계마다 information_schema로 현재 상태를 보고 필요할 때만 ALTER를 실행한다.
--   1번은 FK를 지우고 다시 만드는 두 단계라, 2번이 NULL 행 때문에 실패해도 1번만 적용된 상태로 남는다.
--   그때는 NULL 행을 지우고 이 파일을 다시 실행하면 된다.
-- ▶ 새 DB는 schema.sql만 실행하면 된다 (이 변경이 이미 들어 있다).
-- ▶ 실행 계정: 테이블 구조를 바꾸므로 ALTER 권한이 있는 관리자 계정 (서비스 계정 gilit_app에는 없다).
--   mysql 클라이언트에서 문자셋을 utf8mb4로 실행한다 (--default-character-set=utf8mb4).

SET NAMES utf8mb4;

-- 1-1. ON DELETE SET NULL인 fk_history_user가 있으면 지운다
SET @ddl := IF(
  (SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS
   WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'search_history'
     AND CONSTRAINT_NAME = 'fk_history_user' AND DELETE_RULE <> 'CASCADE') > 0,
  'ALTER TABLE search_history DROP FOREIGN KEY fk_history_user',
  'DO 0');
PREPARE migration_step FROM @ddl;
EXECUTE migration_step;
DEALLOCATE PREPARE migration_step;

-- 2. user_id NOT NULL (NULL 행이 있으면 여기서 실패한다. 위의 확인 쿼리 참고)
SET @ddl := IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'search_history'
     AND COLUMN_NAME = 'user_id' AND IS_NULLABLE = 'YES') > 0,
  'ALTER TABLE search_history MODIFY user_id BIGINT NOT NULL',
  'DO 0');
PREPARE migration_step FROM @ddl;
EXECUTE migration_step;
DEALLOCATE PREPARE migration_step;

-- 1-2. fk_history_user를 ON DELETE CASCADE로 다시 만든다 (없을 때만)
SET @ddl := IF(
  (SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS
   WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'search_history'
     AND CONSTRAINT_NAME = 'fk_history_user') = 0,
  'ALTER TABLE search_history ADD CONSTRAINT fk_history_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE',
  'DO 0');
PREPARE migration_step FROM @ddl;
EXECUTE migration_step;
DEALLOCATE PREPARE migration_step;

-- 확인: user_id의 IS_NULLABLE이 NO, fk_history_user의 DELETE_RULE이 CASCADE여야 한다.
SELECT COLUMN_NAME, IS_NULLABLE, COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'search_history' AND COLUMN_NAME = 'user_id';
SELECT CONSTRAINT_NAME, DELETE_RULE
FROM information_schema.REFERENTIAL_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'search_history';
