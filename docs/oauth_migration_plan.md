# OAuth Migration Plan

## 목적

현재 Meetagain은 `.env`에 직접 넣은 고정 토큰과 `gws CLI` 인증 파일에 의존합니다.
이 방식은 1인 개발과 로컬 실험에는 빠르지만, 실제 운영에서는 아래 문제가 있습니다.

- 배포 환경이 바뀌면 토큰/인증 파일을 다시 맞춰야 함
- 사용자가 직접 계정을 연결하거나 해제할 수 없음
- Google, Trello 권한 범위를 사용자 단위로 분리하기 어려움
- 장기적으로 멀티유저/멀티워크스페이스 운영에 불리함

이 문서는 Google / Trello / Slack 인증을 `OAuth 기반 연결`로 옮기기 위한 최소 설계안입니다.

## 현재 구조

### Google

- [calendar_service.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/services/calendar_service.py)
- [gmail_service.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/services/gmail_service.py)
- [drive_service.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/services/drive_service.py)

특징:
- `gws CLI` subprocess 호출
- 인증은 로컬 credential file / gws auth 상태에 의존
- 애플리케이션 레벨에서 토큰 수명 관리 없음

### Trello

- [trello_service.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/services/trello_service.py)

특징:
- `.env`의 `TRELLO_API_KEY`, `TRELLO_API_TOKEN` 직접 사용
- 보드 접근 권한이 사용자 연결 상태와 분리돼 있음

### Slack

- [slack_service.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/services/slack_service.py)
- [app.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/app.py)

특징:
- `.env`의 `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN` 직접 사용
- 설치형 제품 관점의 OAuth install flow는 아직 없음

## 목표 상태

### 공통 원칙

- 사용자가 웹에서 각 서비스를 직접 연결
- `access token`, `refresh token`, `expires_at`, `scope`를 저장
- 서비스 호출은 `.env` 대신 `연결된 사용자 자격`을 우선 사용
- 토큰 만료 시 자동 갱신
- 연결 해제와 재연결이 가능해야 함
- `.env` 값은 개발/관리자 fallback으로만 유지

### 제품 레벨 목표

- Google: Calendar, Gmail, Drive를 사용자 OAuth로 호출
- Trello: 사용자 보드 접근 권한으로 카드 조회/등록
- Slack: 워크스페이스 설치형 OAuth + 봇 토큰 저장

## 권장 전환 순서

### 1. Google 먼저

이유:
- 현재 `gws CLI` 의존성이 가장 크고 운영 취약점도 큼
- Before / During / After 전체에 영향이 크기 때문에 먼저 계층 분리가 필요함

범위:
- Calendar
- Gmail
- Drive

전환 방식:
- `GoogleAuthService` 추가
- 사용자별 OAuth 토큰 저장
- Google API 클라이언트 직접 호출
- 기존 `gws` 서비스는 fallback으로 남김

### 2. Trello 다음

이유:
- API 표면적이 상대적으로 작음
- 일일 아카이빙/후속처리와 직결됨

전환 방식:
- `TrelloAuthService` 추가
- 사용자 access token 저장
- 보드 목록 조회 후 연결 대상 보드 선택
- 현재 `TRELLO_API_KEY`, `TRELLO_API_TOKEN`은 관리자 fallback으로만 유지

### 3. Slack 마지막

이유:
- Slack은 현재도 사실상 설치형 토큰 모델에 가깝지만, 제품형 OAuth로 옮기려면 설치/재설치/워크스페이스 매핑까지 설계해야 함
- Google/Trello보다 범위가 크고 운영 영향이 큼

전환 방식:
- Slack install URL
- OAuth callback
- workspace 별 bot token 저장
- app-level token / socket mode 전략 재정의

## 최소 아키텍처

### 새 계층

```text
src/
  auth/
    token_store.py
    google_auth_service.py
    trello_auth_service.py
    slack_install_service.py
  integrations/
    google_calendar_client.py
    google_gmail_client.py
    google_drive_client.py
    trello_client.py
```

### 책임 분리

- `auth/*`
  - OAuth URL 생성
  - callback code 교환
  - token 저장/조회
  - refresh token 갱신

- `integrations/*`
  - 실제 API 호출
  - 서비스별 raw SDK / REST 호출 래핑

- 기존 `services/*`
  - 도메인 로직 유지
  - auth/integration 계층을 사용하도록 점진 전환

## 토큰 저장 모델

최소 저장 스키마 예시:

```json
{
  "provider": "google",
  "owner_type": "user",
  "owner_id": "mincircle@parametacorp.com",
  "access_token": "encrypted",
  "refresh_token": "encrypted",
  "expires_at": "2026-04-09T13:00:00+09:00",
  "scope": [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file"
  ],
  "metadata": {
    "email": "mincircle@parametacorp.com"
  }
}
```

권장:
- 초기는 로컬 파일 또는 SQLite 가능
- 실제 운영은 DB + 암호화 저장 권장

## Google 전환 설계

### 필요한 scope

- Calendar 읽기/쓰기
- Gmail 읽기
- Drive 읽기/쓰기

예시:
- `https://www.googleapis.com/auth/calendar`
- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/drive.file`

### 구현 방향

1. `GoogleAuthService`
   - 로그인 URL 생성
   - callback 처리
   - refresh token 저장

2. `GoogleTokenProvider`
   - 만료 전 access token 확인
   - 필요 시 refresh

3. 새 API 클라이언트
   - `GoogleCalendarClient`
   - `GoogleGmailClient`
   - `GoogleDriveClient`

4. 기존 서비스 교체
   - `CalendarService`: `gws` 대신 API client 우선
   - `GmailService`: `gws` 대신 Gmail REST 우선
   - `DriveService`: `gws` 대신 Drive REST 우선

### 마이그레이션 원칙

- 1차: OAuth 연결 추가
- 2차: `OAuth token 있으면 API 사용, 없으면 gws fallback`
- 3차: 충분히 안정화되면 `gws` 제거

## Trello 전환 설계

### 필요한 동작

- 사용자 보드 목록 조회
- 보드 선택
- 카드 조회
- 코멘트 추가
- 체크리스트 추가

### 구현 방향

1. `TrelloAuthService`
   - authorize URL
   - callback 처리
   - token 저장

2. `TrelloApiClient`
   - board/cards/checklists/comments REST 호출

3. `TrelloService` 전환
   - `.env` token 우선 구조 제거
   - 사용자 연결 토큰 우선

### 주의점

- 사용자가 여러 보드를 쓸 수 있으므로 `default board` 선택 상태 저장 필요
- 현재 `TRELLO_BOARD_ID`는 관리자 fallback으로만 유지하는 편이 좋음

## Slack 전환 설계

### 목표

- 워크스페이스 설치형 앱
- workspace 별 bot token 저장
- 사용자별/워크스페이스별 연결 상태 관리

### 구현 방향

1. Slack install URL
2. OAuth callback
3. workspace/team id 기준 bot token 저장
4. `SlackService`가 `.env` 고정 토큰 대신 저장된 workspace token 사용

### 주의점

- 지금 구조는 단일 workspace/단일 bot 전제
- Socket Mode 유지 여부를 먼저 결정해야 함

## 권장 최소 구현 순서

### Phase A. 인증 저장소 추가

- `token_store.py`
- provider별 토큰 CRUD
- local file or SQLite

### Phase B. Google OAuth 추가

- 로그인 URL
- callback
- 토큰 저장
- Calendar 조회 1개 기능만 먼저 API로 전환

### Phase C. Google 전체 전환

- Gmail 검색
- Drive read/write
- `gws` fallback 유지

### Phase D. Trello OAuth 추가

- 사용자 연결
- 보드 선택
- 카드 조회/등록

### Phase E. Slack install flow

- workspace install
- bot token 저장
- 앱 구동 토큰 관리 정리

## 지금 바로 바꾸지 말아야 할 것

- Claude 호출 구조
- 미팅 도메인 로직
- Channel monitor의 판단/추천 규칙
- Slack/Trello 버튼 action payload 구조

즉, 인증 계층만 교체하고 도메인 로직은 최대한 건드리지 않는 것이 맞습니다.

## 현실적인 결론

- Google, Trello는 OAuth로 가는 것이 맞음
- Slack은 제품 설치형 구조로 갈 때 함께 재설계하는 것이 맞음
- 현재 코드베이스에서는 `인증 계층 분리 -> Google 먼저 -> Trello -> Slack` 순서가 가장 안전함
- 한 번에 전부 바꾸는 것보다, `OAuth 우선 / 기존 env fallback` 이행 기간을 두는 편이 현실적임
