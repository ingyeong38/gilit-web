# Google·카카오 OAuth 실제 인증 준비

## 현재 구현과 키가 없는 동작

프론트 버튼은 `/api/auth/google/start`, `/api/auth/kakao/start`로 페이지 이동한다.
백엔드는 state 서명·만료·재사용 검증, Google PKCE, 서버 측 인가 코드 교환과 사용자 조회를 처리한다.
`AuthService.social_login`은 기존 소셜 계정을 조회하거나 신규 계정을 만들고 서버 세션을 발급한다.
같은 이메일의 기존 계정에 자동 연결하지 않는다. 인증된 이메일이 겹치면 `email_exists`로 실패한다.
MySQL 저장소는 `users`와 `social_accounts`를 트랜잭션으로 생성하고 `sessions`에는 세션 토큰 해시를 저장한다.
콜백은 `/pages/search.html?auth_result=...`로 이동하며 프론트는 `/api/auth/me` 응답으로만 소셜 로그인 상태를 복원한다.
소셜 로그아웃은 `/api/auth/logout`을 호출한다.

인증키가 없거나 일부만 있으면 해당 제공자만 꺼진다. 시작 요청은 `auth_result=not_configured`로 복귀하며
인증 세션을 발급하지 않는다. 일부 설정이 있으면 빠진 변수 이름만 서버 로그에 남긴다.
다른 공급자의 완전한 설정은 그대로 활성화되며, 이메일 등 다른 API는 계속 실행된다.
`OAUTH_MOCK`은 기존 개발용 기능이지만 실제 인증에는 사용하지 않는다. 자동 테스트는 의존성을 주입하여
외부 서비스·실제 인증키 없이 흐름을 검증한다. 모의 테스트 통과는 실제 로그인 성공을 뜻하지 않는다.

## 안전하게 환경변수 입력

`backend/.env.example`을 참고하여 **backend/.env**를 작성한다. 기존 파일은 덮어쓰지 않고 필요한 항목만 추가한다.
실제 비밀값은 프론트 파일·문서·Git·채팅에 넣지 않는다. `.env`는 Git 제외 대상이다.
환경변수 우선순위는 프로세스 환경변수 > backend/.env > 루트 .env이며 수정 후 서버를 재시작한다.

| 변수 | 입력할 내용 |
| --- | --- |
| SECRET_KEY | 서버 전용으로 안전하게 생성한 무작위 비밀값 |
| OAUTH_REDIRECT_BASE | `http://localhost:8000` (경로 없이) |
| GOOGLE_CLIENT_ID | Google 웹 애플리케이션 OAuth 클라이언트 ID |
| GOOGLE_CLIENT_SECRET | 동일 클라이언트의 Secret |
| KAKAO_LOGIN_CLIENT_ID | 카카오 앱의 REST API 키 |
| KAKAO_LOGIN_CLIENT_SECRET | 해당 REST API 키의 Client Secret |
| OAUTH_MOCK | 실제 인증은 `false` |

DB를 이미 사용한다면 `AUTH_STORE`와 `DB_*` 설정을 유지한다. 기본 memory 모드는 브라우저 새로고침에는
세션이 유지되지만 서버 재시작 시 계정·세션이 사라진다. 영구 저장은 기존 MySQL 스키마와
`AUTH_STORE=mysql`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`가 필요하다.
TLS 연결을 쓰는 환경은 `DB_SSL_CA`도 설정한다. DB 준비는 `db/README.md`를 따른다.
이번 OAuth 설정만을 위해 기존 DB 데이터를 초기화하거나 스키마를 변경하지 않는다.

## Google 콘솔

1. Google Cloud Console에서 서비스 프로젝트를 선택한다.
2. Google Auth Platform > Branding에서 앱 이름·지원 이메일 등 동의 화면을 구성한다.
3. Audience에서 대상 사용자를 선택하고 테스트 사용자 제한이 적용되면 실제 테스트 계정을 추가한다.
4. Clients에서 웹 애플리케이션 OAuth 클라이언트를 생성하거나 기존 클라이언트를 선택한다.
5. 승인된 리디렉션 URI에 `http://localhost:8000/api/auth/google/callback`을 등록한다.
6. 해당 클라이언트 ID·Secret을 backend/.env에 직접 입력한다.

코드는 `openid email profile`을 요청한다. 콘솔에 직접 접근하지 않은 상태에서는 설정 완료 여부를 알 수 없다.
공식 안내: https://developers.google.com/identity/protocols/oauth2/web-server

## 카카오 콘솔

1. Kakao Developers에서 서비스 앱을 선택한다.
2. 카카오 로그인 > 사용 설정 > 상태를 ON으로 설정한다.
3. 앱 > 플랫폼 키 > REST API 키에서 로그인 리다이렉트 URI
   `http://localhost:8000/api/auth/kakao/callback`을 등록한다.
4. 해당 REST API 키와 Client Secret을 backend/.env에 직접 입력한다.
5. 카카오 로그인 > 동의항목에서 닉네임·필요한 이메일 항목을 확인한다.
   서버는 이메일 없는 계정도 처리하며, 이름이 없으면 기본 이름을 표시한다.

지도용 JavaScript 키는 변경하지 않는다. REST 방식으로 사용자 정보를 조회하므로 OpenID Connect 활성화는 필수가 아니다.
공식 안내: https://developers.kakao.com/docs/ko/kakaologin/prerequisite

## 실행 및 실제 검증

의존성은 backend/requirements-dev.txt를 사용한다. backend/에서 설치된 가상환경의 Python으로 실행한다.

```sh
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

브라우저는 **http://localhost:8000**으로 연다. 이 서버는 프론트와 실제 API를 함께 제공하므로
별도 정적 서버나 8003 프록시가 필요 없다. 포트 점유 시 기존 서버의 소유·작업 폴더를 확인한다.
localhost와 127.0.0.1을 브라우저 주소에서 혼용하지 않는다. 콜백 주소는 프로토콜·호스트·포트·경로까지 일치해야 한다.

각 공급자별로 버튼 클릭 → 제공자 동의 → 콜백 → `/api/auth/me` 200 → 헤더 이름 → 새로고침 유지 →
로그아웃 → `/api/auth/me` 401을 확인한다. 취소·이메일 충돌·잘못된 state도 성공 처리되지 않아야 한다.
쿠키는 HttpOnly·SameSite=Lax를 유지한다. COOKIE_SECURE는 기본 true이며, localhost HTTP에서 실제 쿠키 저장·전송을
대상 브라우저에서 확인한다. 로컬 예외가 필요하면 백엔드 담당자와 설정하고 운영은 반드시 Secure를 유지한다.

## 자동 검증

```sh
# 프로젝트 루트
node --test frontend/tests/*.test.mjs
python -m unittest discover -s scripts/tests -v
# backend/에서
python -m pytest
```

기본 pytest는 실제 제공자와 실제 DB를 호출하는 테스트를 제외한다. MySQL 실환경 검증은 별도 테스트 DB가 필요하며
기존 개발·운영 DB를 테스트 대상으로 쓰지 않는다. 실제 키·계정 인증 전 최종 실환경 판정은 UNVERIFIED다.
