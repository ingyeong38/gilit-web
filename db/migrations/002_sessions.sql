-- 002: 로그인 세션 테이블 (서버 세션 쿠키 gilit_session)
-- 쿠키 값(무작위 토큰) 원문은 저장하지 않고 SHA-256 해시(16진수 64자)만 저장한다. DB가 유출돼도 쿠키를 만들 수 없다.
-- 만료는 로그인 시각 + 14일 고정이다. 만료된 행은 서버가 로그인할 때 지운다 (expires_at 인덱스).
-- 사용자를 지우면 세션도 함께 지워진다 (ON DELETE CASCADE).
--
-- 이미 만든 DB에만 실행한다. 새 DB는 schema.sql만 실행하면 된다. 다시 실행해도 된다 (IF NOT EXISTS).
-- 실행 계정: CREATE 권한이 있는 관리자 계정

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS sessions (
  token_hash     CHAR(64)    NOT NULL,                       -- SHA-256(쿠키 값)
  user_id        BIGINT      NOT NULL,
  login_provider VARCHAR(20) NOT NULL,                       -- 'email' | 'google' | 'kakao' (API의 provider)
  created_at     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- 1시간에 한 번까지만 갱신한다
  expires_at     DATETIME    NOT NULL,
  PRIMARY KEY (token_hash),
  KEY idx_sessions_user (user_id),
  KEY idx_sessions_expires (expires_at),
  CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT chk_sessions_provider CHECK (login_provider IN ('email', 'google', 'kakao'))
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
