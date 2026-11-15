-- 003: favorite_places 제약 (즐겨찾기 F9)
--   1. UNIQUE(user_id, place_name): 같은 사용자의 같은 별칭 금지
--      콜레이션 utf8mb4_0900_ai_ci라 대소문자·악센트·전각을 구분하지 않는다 ('Home'='home', 'Café'='cafe', 'Ａ'='A').
--      서버의 메모리 저장소(name_key)도 같은 규칙이다 (backend/tests/test_favorites_mysql.py에서 대조).
--   2. CHECK label IN ('집', '학교', '회사', '기타')  -- MySQL 8.0.16 이상에서 실제로 검사한다
--   3. idx_favorite_user(user_id) 삭제: 1번 UNIQUE가 user_id로 시작하므로 FK(fk_favorite_user)의 인덱스를 대신한다
--
-- ▶ 적용 전 확인 쿼리: 이름이 겹치는 행이 있으면 1번에서 실패한다 (Duplicate entry ... for key 'uq_favorite_user_name').
--   결과가 비어 있어야 한다. 나오면 겹치는 행의 place_name을 고치거나 지운 뒤 적용한다.
--
--     SELECT user_id, place_name, COUNT(*) AS n, GROUP_CONCAT(id ORDER BY id) AS ids
--     FROM favorite_places
--     GROUP BY user_id, place_name
--     HAVING COUNT(*) > 1;
--
--   분류 값이 4가지 밖인 행이 있으면 2번에서 실패한다 (Check constraint 'chk_favorite_label' is violated).
--
--     SELECT id, user_id, label FROM favorite_places WHERE label NOT IN ('집', '학교', '회사', '기타');
--
-- ▶ 다시 실행해도 된다. MySQL 8에는 ADD/DROP ... IF [NOT] EXISTS가 없으므로, 각 단계마다 information_schema로
--   이미 있는지 확인하고 필요할 때만 ALTER를 실행한다 (이미 적용된 DB에서는 아무것도 바꾸지 않는다).
-- ▶ 새 DB는 schema.sql만 실행하면 된다 (이 변경이 이미 들어 있다).
-- ▶ 실행 계정: 테이블 구조를 바꾸므로 ALTER 권한이 있는 관리자 계정 (서비스 계정 gilit_app에는 없다).
--   mysql 클라이언트에서 문자셋을 utf8mb4로 실행한다 (--default-character-set=utf8mb4). CHECK의 한글 값 때문이다.

SET NAMES utf8mb4;

-- 1. UNIQUE(user_id, place_name)
SET @ddl := IF(
  (SELECT COUNT(*) FROM information_schema.STATISTICS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'favorite_places' AND INDEX_NAME = 'uq_favorite_user_name') = 0,
  'ALTER TABLE favorite_places ADD UNIQUE KEY uq_favorite_user_name (user_id, place_name)',
  'DO 0');
PREPARE migration_step FROM @ddl;
EXECUTE migration_step;
DEALLOCATE PREPARE migration_step;

-- 2. CHECK label
SET @ddl := IF(
  (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
   WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'favorite_places'
     AND CONSTRAINT_NAME = 'chk_favorite_label' AND CONSTRAINT_TYPE = 'CHECK') = 0,
  'ALTER TABLE favorite_places ADD CONSTRAINT chk_favorite_label CHECK (label IN (''집'', ''학교'', ''회사'', ''기타''))',
  'DO 0');
PREPARE migration_step FROM @ddl;
EXECUTE migration_step;
DEALLOCATE PREPARE migration_step;

-- 3. idx_favorite_user 삭제 (1번 UNIQUE가 있을 때만. FK에 쓸 인덱스가 하나도 없게 되지 않도록)
SET @ddl := IF(
  (SELECT COUNT(*) FROM information_schema.STATISTICS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'favorite_places' AND INDEX_NAME = 'idx_favorite_user') > 0
  AND
  (SELECT COUNT(*) FROM information_schema.STATISTICS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'favorite_places' AND INDEX_NAME = 'uq_favorite_user_name') > 0,
  'ALTER TABLE favorite_places DROP INDEX idx_favorite_user',
  'DO 0');
PREPARE migration_step FROM @ddl;
EXECUTE migration_step;
DEALLOCATE PREPARE migration_step;

-- 확인: uq_favorite_user_name과 chk_favorite_label이 있고 idx_favorite_user가 없어야 한다.
SELECT INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns_in_index, NON_UNIQUE
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'favorite_places'
GROUP BY INDEX_NAME, NON_UNIQUE;
SELECT CONSTRAINT_NAME, CONSTRAINT_TYPE
FROM information_schema.TABLE_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'favorite_places';
