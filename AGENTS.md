# 미팅 에이전트 — AGENTS.md

## 프로젝트 개요
Slack 기반 1인용 AI 미팅 비서입니다.  
외부 미팅의 준비(Before) → 기록(During) → 후속(After) 전 과정을 지원합니다.

현재 구현 대상은 **Phase 1: Before 에이전트 전체 + Gmail 연동**입니다.  
에이전트 두뇌는 **Claude API (claude-sonnet-4-6)**, 개발 언어는 **Node.js**를 사용합니다.

---

## 프로젝트 목표
이 프로젝트의 1차 목표는 아래를 자동화하는 것입니다.

- 오늘 예정된 미팅 중 외부 미팅 식별
- 외부 미팅 대상 업체/인물 정보 수집
- 최근 이메일 이력 검색
- Slack DM 기반 브리핑 Draft 전달
- 사용자의 어젠다 입력을 캘린더와 동기화
- 자연어 기반 미팅 생성 및 참석자 초대

---

## 핵심 원칙
- 중요한 발송(회의록, 요약, 대외 공유 내용)은 반드시 **Slack Draft 또는 확인 가능한 형태**로 생성하고, **사용자가 수동 확인 후 발송**합니다.
- **자동 발송 금지 원칙은 어떤 상황에서도 예외 없이 적용**합니다.
- 모든 Claude API 출력은 **한국어 기본**입니다.
- 불필요한 Claude API 호출은 최소화합니다. 가능한 경우 **캐시 우선, 조건부 실행**을 사용합니다.
- 실패한 외부 API가 있더라도, 가능한 범위 내에서 **부분 성공 형태로 계속 진행**합니다.
- 구현은 항상 **실행 가능한 최소 단위**를 우선합니다. 불필요한 고도화는 이번 Phase에서 하지 않습니다.

---

## Phase 1 구현 범위
이번 작업에서는 아래만 구현합니다.

### 포함
- Before 에이전트
- Gmail 연동
- Calendar 조회
- 외부 미팅 식별
- Contacts 조회/저장
- 웹 검색 기반 브리핑 생성
- Slack DM 브리핑 Draft 전송
- Slack 스레드 어젠다 답장 → Calendar 설명란 동기화
- 자연어 미팅 생성 + 참석자 초대

### 제외
이번 작업에서는 아래를 구현하지 않습니다.

- During 에이전트의 transcript 수집
- 회의록 자동 생성 본 구현
- After 에이전트 전체
- Trello 후속 처리 자동화 본 구현
- 내부 미팅 패키지 생성 본 구현
- 실시간 피드백
- 외부 에이전트 연결
- Cloud Run 배포 고도화
- 운영 모니터링/대시보드 고도화

---

## Phase 1 완료 조건
아래가 동작하면 Phase 1 완료로 봅니다.

1. 오늘 캘린더 이벤트를 조회할 수 있다.
2. 외부 미팅 여부를 3단계 로직으로 판별할 수 있다.
3. 업체/인물 정보 캐시를 조회하고, 필요 시 조회/저장할 수 있다.
4. Gmail 최근 3개월 검색 결과를 브리핑에 반영할 수 있다.
5. Slack DM으로 브리핑 Draft를 전달할 수 있다.
6. Slack 스레드 어젠다 답장을 Calendar 설명란에 반영할 수 있다.
7. 자연어 입력으로 미팅 생성과 참석자 초대를 수행할 수 있다.

---

## 기술 스택

| 역할 | 도구 |
|---|---|
| 에이전트 두뇌 | Claude API (claude-sonnet-4-6) |
| Slack 연동 | Slack Bolt for Node.js |
| Google 연동 | gws CLI (googleworkspace/cli) |
| 파이프라인 관리 | Trello API (REST) |
| 인프라 | Google Cloud Run (무료 플랜) |
| 웹 검색 | Claude API web_search tool |

---

## 환경 변수 (.env)
```env
ANTHROPIC_API_KEY=
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
TRELLO_API_KEY=
TRELLO_TOKEN=
TRELLO_BOARD_ID=69731ce5bc41747a88054157
COMPANY_DOMAIN_1=parametacorp.com
COMPANY_DOMAIN_2=iconloop.com
BRIEFING_CHANNEL=                # 기본값: 본인 DM
디렉토리 구조
meeting-agent/
├── AGENTS.md
├── src/
│   ├── agents/
│   │   ├── before.js       # Before 에이전트 (브리핑, 미팅 생성)
│   │   ├── during.js       # During 에이전트 (향후 구현)
│   │   └── after.js        # After 에이전트 (향후 구현)
│   ├── skills/
│   │   ├── calendar.js     # gws calendar 래퍼
│   │   ├── drive.js        # gws drive 래퍼
│   │   ├── gmail.js        # gws gmail 래퍼
│   │   ├── slack.js        # Slack Bolt 핸들러
│   │   ├── trello.js       # Trello API 래퍼 (향후 확장)
│   │   └── contacts.js     # Drive Contacts CRUD
│   ├── prompts/
│   │   ├── briefing.js     # 브리핑 생성 프롬프트
│   │   ├── minutes.js      # 회의록 생성 프롬프트 (향후 구현)
│   │   └── package.js      # 내부 미팅 패키지 프롬프트 (향후 구현)
│   └── utils/
│       ├── cache.js        # 7일 뉴스 캐시, 30일 인물 캐시
│       └── identifier.js   # 외부 미팅 식별 로직
├── data/
│   └── meeting-rules.json  # 외부 미팅 식별 학습 패턴
├── .env
└── package.json
외부 미팅 식별 로직

identifier.js는 아래 3단계 순서로 판단합니다.
앞 단계에서 확정되면 뒤 단계는 실행하지 않습니다.

판단 규칙
1순위: 참석자 이메일에 @parametacorp.com, @iconloop.com 외 도메인이 있으면 외부 미팅 확정
2순위: 이벤트 제목에 Contacts/Companies 목록의 업체명이 포함되면 외부 미팅으로 간주
3순위: 판단 불가 시 Slack DM으로 사용자에게 질의 발송
질의 응답 규칙
- 사용자 응답이 "네"면 외부 미팅으로 확정
- 사용자 응답이 "아니요"면 내부 미팅으로 처리
- 1시간 무응답 시 외부 미팅으로 간주
예외 규칙
- "3시 콜", "Weekly Sync" 등
- 업체명 없음
- 외부 이메일 없음
- Contacts/Companies 매칭 없음

위 조건이면 내부 미팅으로 간주하고 브리핑을 생성하지 않음
Slack 표준 질의 문구

코드에서 사용자에게 보내는 메시지는 아래 문구를 그대로 사용합니다.
[ ] 내부만 동적으로 치환합니다.

외부 미팅 여부 확인
📅 [이벤트명] ([시각]) 은 외부 미팅인가요?
✅ 네 → 브리핑 진행
⏭️ 아니요 → 건너뜀
(1시간 내 미응답 시 외부 미팅으로 간주하여 자동 브리핑 진행합니다)
업체명 파싱 실패
📋 [이벤트명] 미팅을 브리핑하려는데, 상대 업체명이 확인되지 않아요.
어느 업체와의 미팅인가요? (예: 카카오, 네이버)
참석자 이메일 미확인
👤 [이름] 님의 이메일 주소를 찾지 못했어요.
직접 입력해주시면 캘린더 초대와 Contacts에 저장할게요.
어젠다 등록 안내
📝 어젠다를 등록하려면 이 스레드에 답장해주세요.
입력하신 내용은 Calendar 이벤트 설명란에도 자동 반영됩니다.
Trello 카드 신규 생성 확인
📌 [업체명] 카드가 Trello에 없어요.
Contact/Meeting 리스트에 새로 생성할까요?
✅ 네  ❌ 아니요
Drive Contacts 구조
Contacts/
├── Companies/
│   └── 업체명.md
└── People/
    └── 이름_업체명.md

company_knowledge.md
파일 규칙
Companies 파일명 형식: 업체명.md
People 파일명 형식: 이름_업체명.md
예: 김민환_카카오.md
Companies 파일 역할
업체 기본 정보 저장
최근 검색 시점 저장
뉴스 캐시 저장
People 파일 역할
인물 기본 정보 저장
이메일/직책/성향/최근 업데이트 시점 관리
company_knowledge.md 역할
파라메타 서비스, 핵심 레퍼런스, 기본 설명 저장
내부 미팅 패키지 및 브리핑 생성 시 공통 컨텍스트로 활용
/업데이트 같은 별도 운영 명령으로 갱신 가능하도록 고려
Contacts 예시
People 예시
# 김민환 (카카오)
이메일: minwhan@kakao.com
직책: 사업개발팀 팀장
LinkedIn: https://...
성향: 직접적 커뮤니케이션 선호, 숫자 근거 중시
last_updated: 2026-03-20
Companies 예시
# 카카오
도메인: kakao.com
업종: IT/플랫폼
last_searched: 2026-03-20
news_cache:
  - 제목: "카카오 AI 애드 출시 예정" | 링크: https://... | 날짜: 2026-03-18
  - 제목: "카카오엔터 IP 확장 전략 발표" | 링크: https://... | 날짜: 2026-03-15
캐시 규칙

cache.js는 아래 기준으로 동작합니다.

업체 뉴스: last_searched 기준 7일 이내면 웹 검색 스킵
인물 정보: last_updated 기준 30일 이내면 웹 검색 스킵
미팅 없는 날: Before 에이전트 전체 스킵 (Claude API 호출 0)
액션아이템 0개: After 패키지 생성 스킵
캐시 원칙
캐시가 유효하면 Claude API 호출보다 캐시 사용을 우선합니다.
캐시 만료 시에만 웹 검색 또는 추가 조회를 수행합니다.
캐시 조회 실패 시 전체 프로세스를 중단하지 않습니다.
Gmail 검색 규칙
검색 쿼리: "[이름] [업체명]" 최근 3개월
이메일 주소 확인 우선순위: Slack 워크스페이스 → Gmail 검색 → Contacts → 직접 입력 요청
동명이인 처리: 업체명 함께 포함된 스레드로 필터링
Gmail 실패 시 처리
검색 실패 시 브리핑 생성을 중단하지 않습니다.
브리핑에는 아래와 같이 표기합니다.
"최근 이메일 이력 없음"
또는 "최근 이메일 조회 실패"
브리핑 생성 원칙

Before 에이전트가 생성하는 브리핑은 아래 정보를 우선 포함합니다.

미팅 기본 정보: 일시, 제목, 참석자
외부 업체 정보
상대 인물 정보
최근 뉴스 또는 캐시된 뉴스
최근 이메일 이력 요약
사용자가 추가한 어젠다
필요한 경우 확인이 필요한 누락 정보
브리핑 출력 원칙
한국어 기본
과도한 서술 금지
실무용 요약 우선
사실과 추정 구분
확인되지 않은 내용은 단정 금지
자연어 미팅 생성 규칙

사용자의 자연어 입력으로 캘린더 이벤트를 생성합니다.

입력 예시
내일 오후 3시 카카오 김민환 팀장과 30분 미팅 잡아줘
금요일 10시에 네이버 미팅 만들고 minwhan@naver.com 초대해줘
다음 주 화요일 오후 2시 1시간 동안 알로뱅크 미팅 생성해줘
필수 처리
날짜/시간 파싱
미팅 길이 파싱
업체명 분리
참석자명 분리
이메일 주소 확인
Calendar 이벤트 생성
참석자 초대
Slack DM으로 생성 결과 요약 전달
이메일 미확인 시 처리
Slack 워크스페이스 → Gmail → Contacts 순으로 조회
찾지 못하면 사용자에게 직접 입력 요청
이메일 없이는 외부 참석자 초대를 완료하지 않음
어젠다 동기화 규칙
브리핑 메시지의 스레드에 사용자가 어젠다를 답장하면 Calendar 이벤트 설명란에 반영합니다.
기존 설명란이 있으면 보존하고, 어젠다 영역만 append 또는 update 합니다.
동기화 실패 시 Slack DM으로 실패 사실을 알립니다.
에러 처리 원칙
외부 API 실패 시 전체 프로세스를 즉시 중단하지 않습니다.
가능한 범위까지 진행하고, 실패한 단계는 Slack DM에 명시합니다.
상대 업체명/이메일이 없으면 사용자 질의로 폴백합니다.
Gmail 검색 실패 시 브리핑은 생성하되 조회 실패로 표기합니다.
웹 검색 실패 시 캐시/Contacts 기반 최소 브리핑만 생성합니다.
Calendar 이벤트 생성 실패 시 Slack DM으로 원인과 재시도 필요 여부를 알립니다.
예외는 삼키지 말고 로깅 가능한 형태로 남깁니다.
회의록 규격

아래는 향후 Phase에서 사용할 규격이며, 이번 Phase에서 본 구현은 하지 않습니다.

클라이언트용 (Google Docs, A4 1페이지)
섹션: 일시/참석자 | 어젠다 | 주요 결론 | To Do
분량: A4 1페이지 이내
톤: 중립적, 합의 사항 위주, 주관적 의견 제외
내부용 (Google Docs, A4 2페이지)
섹션: [클라이언트용 전체] + 내부 의견(빈칸) + AI 인사이트 + 의사결정 필요 항목
분량: A4 2페이지 이내
AI 인사이트 인풋: 회의록 + 이전 이메일 + Trello 이력 + Contacts + company_knowledge.md
내부 미팅 패키지 프롬프트 인풋 순서

아래는 향후 After 에이전트에서 사용할 규칙이며, 이번 Phase에서 본 구현은 하지 않습니다.

Claude API 호출 시 아래 순서로 컨텍스트를 조합합니다.

① company_knowledge.md
② Contacts/Companies/업체명.md
③ Contacts/People/이름_업체명.md
④ 오늘 회의록 전문
⑤ Trello 이력
⑥ Gmail 최근 3개월 이메일 요약
기대 산출물
협상 포인트 분석
AI 인사이트
의사결정 항목 3~5개
리서치 초안
제안서 초안
Trello 규칙

아래는 향후 확장 기준이며, 이번 Phase에서는 본 구현 대상이 아닙니다.

보드 ID: 69731ce5bc41747a88054157 (parametapipeline)
신규 카드 기본 리스트: Contact/Meeting
카드 이동: 자동 이동 없음
이력 참조 범위: 미완료 체크리스트 전체 + 최근 코멘트 3개 + 회의록 링크 요약
체크리스트명 형식: "액션아이템 — YYYY/MM/DD 미팅"
구현 Phase
Phase 1 (현재): Before 에이전트 전체 + Gmail 연동
Phase 2: After 에이전트 (회의록, Trello, 내부 패키지)
Phase 3: During 에이전트 (transcript 수집, 회의록 자동 생성)
Phase 4: 고도화 (실시간 피드백, 외부 에이전트 연결)
Phase 1 구현 순서
gws CLI 인증 세팅 (gws auth setup)
Slack 봇 등록 및 DM 수신
캘린더 조회 + 외부 미팅 식별
웹 검색 + Contacts 조회/저장
Gmail 이전 이메일 검색
Slack 브리핑 발송
어젠다 스레드 답장 → Calendar 동기화
자연어 미팅 생성 + 참석자 초대
구현 지침
초기 구현은 mock 기반으로 시작하되, 실행 가능한 최소 구조를 유지합니다.
각 파일은 placeholder만 만들지 말고, 최소 1개 이상의 명확한 책임을 수행해야 합니다.
README에는 반드시 로컬 실행 방법, 필수 환경 변수, 인증 선행 작업을 정리합니다.
아직 미구현인 항목은 주석이 아니라 TBD로 명시합니다.
미래 Phase 기능은 파일 틀만 만들 수 있으나, 현재 Phase 구현과 섞지 않습니다.
Codex 작업 지침

Codex는 이 문서를 우선 기준 문서로 사용합니다.

반드시 지킬 것
Phase 1 범위를 벗어나지 말 것
자동 발송 금지 원칙을 깨지 말 것
Claude API 출력 한국어 기본 원칙을 지킬 것
불필요한 복잡성 추가 금지
실행 가능한 최소 구조와 코드 우선
원하는 기본 산출물
package.json
필요한 디렉토리 및 파일 생성
각 파일의 초기 구현
.env.example
README.md
미구현/TBD 항목 정리

## Phase 1 Execution Constraint
Phase 1 implementation MUST start with mock-based flow first.
Real integrations (Google Calendar, Gmail, Slack API) should be implemented after basic flow is validated.

## First Task for Codex

Implement minimal Phase 1 Before agent with mock data:

Flow:
1. mock calendar events
2. detect external meetings
3. mock research data
4. generate Slack briefing text

Requirements:
- Node.js + TypeScript
- no real API calls yet
- simple modular structure
- runnable locally

Output:
- project scaffold
- source files
- README
- .env.example
