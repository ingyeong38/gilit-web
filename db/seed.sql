-- 길잇 테스트용 더미 데이터. 개발·테스트 DB에서만 실행한다 (운영 DB 금지).
-- db/schema.sql을 먼저 실행한다. id를 고정해 두어 다시 실행해도 같은 행이 중복으로 들어가지 않는다.
-- 시각은 실행 시점 기준 상대값이라 이용 통계 화면에서 최근 데이터로 보인다.
--
-- 비밀번호: password_hash는 bcrypt 형식만 흉내 낸 더미 문자열이다. 어떤 비밀번호와도 맞지 않으므로
-- 시드 계정으로는 이메일 로그인을 할 수 없다. 로그인 테스트는 회원가입 API로 새 계정을 만든다.

SET NAMES utf8mb4;
SET time_zone = '+09:00';

INSERT INTO users (id, email, password_hash, nickname, agreed_at, created_at, last_login_at) VALUES
  (1, 'tester@example.com', '$2b$12$SEED.DUMMY.HASH.NOT.A.REAL.PASSWORD.xxxxxxxxxxxxxxxxx', '길잇테스터',
   NOW() - INTERVAL 10 DAY, NOW() - INTERVAL 10 DAY, NOW() - INTERVAL 1 HOUR),
  -- 카카오로만 가입한 사용자: password_hash가 NULL이다.
  (2, 'kakao-user@example.com', NULL, '카카오사용자',
   NOW() - INTERVAL 5 DAY, NOW() - INTERVAL 5 DAY, NOW() - INTERVAL 1 DAY)
ON DUPLICATE KEY UPDATE id = id;

INSERT INTO social_accounts (id, user_id, provider, provider_user_id, created_at) VALUES
  (1, 2, 'kakao', '1000000001', NOW() - INTERVAL 5 DAY)
ON DUPLICATE KEY UPDATE id = id;

INSERT INTO favorite_places (id, user_id, label, place_name, address, lat, lng) VALUES
  (1, 1, '집',   '집',              '경상남도 김해시 내외중앙로 47',     35.2285000, 128.8894000),
  (2, 1, '학교', '동의대학교',      '부산광역시 부산진구 엄광로 176',    35.1441000, 129.0336000),
  (3, 2, '회사', '센텀시티 오피스', '부산광역시 해운대구 센텀중앙로 90', 35.1690000, 129.1316000)
ON DUPLICATE KEY UPDATE id = id;

INSERT INTO search_history
  (id, user_id, origin_name, origin_lat, origin_lng, dest_name, dest_lat, dest_lng,
   arrive_at, buffer_min, recommended_depart_at, travel_mode, ai_summary, created_at) VALUES
  (1, 1, '김해시청', 35.2285000, 128.8894000, '동의대학교', 35.1441000, 129.0336000,
   DATE(NOW()) + INTERVAL 1 DAY + INTERVAL 9 HOUR, 10, DATE(NOW()) + INTERVAL 1 DAY + INTERVAL 8 HOUR + INTERVAL 12 MINUTE,
   'car', '남해고속도로 경유가 가장 안정적이에요', NOW() - INTERVAL 2 HOUR),
  (2, 1, '김해공항 국내선', 35.1732000, 128.9482000, '부산역', 35.1151000, 129.0414000,
   DATE(NOW()) - INTERVAL 1 DAY + INTERVAL 18 HOUR + INTERVAL 30 MINUTE, 15, DATE(NOW()) - INTERVAL 1 DAY + INTERVAL 17 HOUR + INTERVAL 40 MINUTE,
   'car', NULL, NOW() - INTERVAL 1 DAY),
  (3, 2, '센텀시티', 35.1690000, 129.1316000, '동의대학교', 35.1441000, 129.0336000,
   DATE(NOW()) - INTERVAL 2 DAY + INTERVAL 10 HOUR, 5, DATE(NOW()) - INTERVAL 2 DAY + INTERVAL 9 HOUR + INTERVAL 20 MINUTE,
   'car', NULL, NOW() - INTERVAL 2 DAY),
  -- 비로그인 검색
  (4, NULL, '김해시청', 35.2285000, 128.8894000, '부산역', 35.1151000, 129.0414000,
   DATE(NOW()) + INTERVAL 14 HOUR, 0, NULL,
   'car', NULL, NOW() - INTERVAL 30 MINUTE)
ON DUPLICATE KEY UPDATE id = id;

INSERT INTO visit_logs (id, user_id, session_id, path, created_at) VALUES
  (1, NULL, 'seed-session-a', '/index.html',          NOW() - INTERVAL 2 DAY),
  (2, NULL, 'seed-session-a', '/pages/search.html',   NOW() - INTERVAL 2 DAY + INTERVAL 1 MINUTE),
  (3, 2,    'seed-session-b', '/pages/search.html',   NOW() - INTERVAL 2 DAY + INTERVAL 3 HOUR),
  (4, 1,    'seed-session-c', '/pages/search.html',   NOW() - INTERVAL 1 DAY),
  (5, 1,    'seed-session-c', '/pages/result.html',   NOW() - INTERVAL 1 DAY + INTERVAL 2 MINUTE),
  (6, NULL, 'seed-session-d', '/index.html',          NOW() - INTERVAL 40 MINUTE),
  (7, NULL, 'seed-session-d', '/pages/result.html',   NOW() - INTERVAL 30 MINUTE),
  (8, 1,    'seed-session-e', '/pages/favorites.html', NOW() - INTERVAL 1 HOUR),
  (9, 1,    'seed-session-e', '/pages/stats.html',    NOW() - INTERVAL 50 MINUTE)
ON DUPLICATE KEY UPDATE id = id;
