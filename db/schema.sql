-- 길잇 DB 스키마. MySQL 8.0.16 이상 (AWS RDS for MySQL 8), utf8mb4, InnoDB.
-- 다시 실행해도 되도록 CREATE TABLE IF NOT EXISTS를 쓴다. 이미 있는 테이블의 구조는 바꾸지 않으므로,
-- 컬럼을 바꿀 때는 ALTER TABLE을 따로 작성한다.
-- 모든 DATETIME은 한국 시간(KST)이다. 서버는 연결할 때 SET time_zone = '+09:00'을 실행한다 (db/README.md).
-- 테이블 설명과 API 필드 매핑은 db/README.md, docs/api-spec.md를 본다.

SET NAMES utf8mb4;

-- 회원. 이메일 가입자와 소셜 가입자가 함께 있다. 계정은 이메일 하나당 하나다.
CREATE TABLE IF NOT EXISTS users (
  id            BIGINT       NOT NULL AUTO_INCREMENT,
  email         VARCHAR(255) NOT NULL,              -- 소문자로 바꿔 저장한다
  password_hash VARCHAR(255) NULL,                  -- bcrypt 해시. 소셜 가입자는 NULL
  nickname      VARCHAR(50)  NOT NULL,
  agreed_at     DATETIME     NULL,                  -- 필수 약관(이용약관·개인정보 처리방침) 동의 시각
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login_at DATETIME     NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_email (email)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 소셜 로그인 연결. 소셜 로그인은 (provider, provider_user_id)로 사용자를 찾는다.
CREATE TABLE IF NOT EXISTS social_accounts (
  id               BIGINT       NOT NULL AUTO_INCREMENT,
  user_id          BIGINT       NOT NULL,
  provider         VARCHAR(20)  NOT NULL,           -- 'google' | 'kakao'
  provider_user_id VARCHAR(100) NOT NULL,           -- Google sub, 카카오 회원번호
  created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_social_provider_user (provider, provider_user_id),
  UNIQUE KEY uq_social_user_provider (user_id, provider),  -- 한 사용자에 같은 제공자 계정은 하나
  CONSTRAINT fk_social_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT chk_social_provider CHECK (provider IN ('google', 'kakao'))
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 즐겨찾기 장소
CREATE TABLE IF NOT EXISTS favorite_places (
  id         BIGINT        NOT NULL AUTO_INCREMENT,
  user_id    BIGINT        NOT NULL,
  label      VARCHAR(50)   NOT NULL,                -- '집', '학교', '회사', '기타' (API의 type)
  place_name VARCHAR(100)  NOT NULL,                -- API의 name
  address    VARCHAR(255)  NULL,
  lat        DECIMAL(10,7) NOT NULL,
  lng        DECIMAL(10,7) NOT NULL,
  created_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_favorite_user (user_id),
  CONSTRAINT fk_favorite_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 길찾기 검색 기록. 비로그인 검색도 user_id NULL로 남겨 이용 통계에 쓴다.
-- 회원이 탈퇴하면 기록은 남기고 user_id만 NULL로 바꾼다.
CREATE TABLE IF NOT EXISTS search_history (
  id                    BIGINT        NOT NULL AUTO_INCREMENT,
  user_id               BIGINT        NULL,
  origin_name           VARCHAR(100)  NULL,
  origin_lat            DECIMAL(10,7) NULL,
  origin_lng            DECIMAL(10,7) NULL,
  dest_name             VARCHAR(100)  NULL,
  dest_lat              DECIMAL(10,7) NULL,
  dest_lng              DECIMAL(10,7) NULL,
  arrive_at             DATETIME      NOT NULL,        -- 도착 희망 시각
  buffer_min            INT           NOT NULL DEFAULT 0,  -- 여유 시간(분)
  recommended_depart_at DATETIME      NULL,            -- 추천 경로의 권장 출발 시각
  travel_mode           VARCHAR(20)   NOT NULL,        -- 'car' | 'transit'
  ai_summary            TEXT          NULL,
  created_at            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_history_user_created (user_id, created_at),   -- 내 검색 기록 (최신순)
  KEY idx_history_dest (dest_name),                     -- 인기 목적지
  KEY idx_history_origin (origin_name),                 -- 인기 출발지
  CONSTRAINT fk_history_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
  CONSTRAINT chk_history_travel_mode CHECK (travel_mode IN ('car', 'transit')),
  CONSTRAINT chk_history_buffer CHECK (buffer_min >= 0)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 페이지 방문 로그. 방문자 수 통계에 쓴다.
CREATE TABLE IF NOT EXISTS visit_logs (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  user_id    BIGINT       NULL,
  session_id VARCHAR(64)  NULL,                    -- 같은 방문자의 중복 방문 구분용 (서버가 발급한 쿠키 값)
  path       VARCHAR(255) NOT NULL,
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_visit_created (created_at),             -- 일별·월별 방문자
  KEY idx_visit_path (path),
  KEY idx_visit_user (user_id),                   -- FK 검사용
  CONSTRAINT fk_visit_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
