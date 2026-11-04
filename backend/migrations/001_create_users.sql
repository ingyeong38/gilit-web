-- 사용자 계정 테이블. MySQL 8 기준 (DB가 정해지면 문법을 맞춘다).
-- 규칙과 처리 방식은 docs/api-spec.md의 "이메일 회원가입·로그인"을 따른다.

CREATE TABLE users (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  email         VARCHAR(254)    NOT NULL,           -- 소문자로 바꿔 저장한다
  name          VARCHAR(20)     NOT NULL,
  password_hash CHAR(60)        NULL,               -- bcrypt 해시. 소셜 전용 계정은 NULL
  provider      ENUM('email', 'google', 'kakao') NOT NULL,  -- 처음 가입한 방법
  terms_agreed_at   DATETIME    NULL,               -- 이메일 가입 시 필수 약관 동의 시각
  privacy_agreed_at DATETIME    NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_email (email),
  CONSTRAINT chk_users_email_password CHECK (provider <> 'email' OR password_hash IS NOT NULL)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 소셜 계정 연결. 소셜 로그인은 (provider, provider_user_id)로 사용자를 찾는다.
CREATE TABLE user_social_accounts (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id          BIGINT UNSIGNED NOT NULL,
  provider         ENUM('google', 'kakao') NOT NULL,
  provider_user_id VARCHAR(255)    NOT NULL,        -- Google sub, 카카오 회원번호
  created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_social_provider_user (provider, provider_user_id),
  UNIQUE KEY uq_social_user_provider (user_id, provider),
  CONSTRAINT fk_social_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
