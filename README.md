# 미팅 에이전트 (Meetagain)

Slack 하나로 외부 미팅의 준비(브리핑), 기록(회의록), 후속 처리(Trello·Contacts·내부 미팅 패키지)를 자동화하는 AI 기반 미팅 라이프사이클 에이전트입니다.

## 🎯 프로젝트 목표

- **Before**: 미팅 전 자동 브리핑 (업체·인물·서비스 연결점·이전 맥락)
- **During**: 미팅 중 회의록 생성 및 실시간 지원
- **After**: 미팅 후 자동 후속 처리 (Trello·제안서·리서치 초안)

## 💻 기술 스택

- **Google Workspace**: gws CLI (Calendar, Drive, Gmail, Meet)
- **통신**: Slack MCP
- **AI**: Claude API (요구사항 정의서 v2.3)
- **검색**: DuckDuckGo Search
- **파이프라인**: Trello API
- **언어**: Python 3.10+

## 📁 프로젝트 구조

```
260325_Clade_Meetagain/
├── docs/                           # 기준 문서
│   ├── guidelines.md
│   ├── glossary.md
│   ├── project_brief.md
│   ├── harness.md
│   ├── meeting-agent-requirements-v2_3.md
│   └── implementation_status.md
│
├── src/                            # 구현 코드
│   ├── agents/
│   │   ├── before_agent.py         # 미팅 준비
│   │   ├── during_agent.py         # transcript 기반 회의록 생성
│   │   └── after_agent.py          # 후속 처리
│   │
│   ├── services/                   # 외부 API 통합
│   │   ├── calendar_service.py     # Google Calendar
│   │   ├── drive_service.py        # Google Drive
│   │   ├── gmail_service.py        # Gmail
│   │   ├── slack_service.py        # Slack MCP
│   │   ├── trello_service.py       # Trello
│   │   └── search_service.py       # Web Search (DuckDuckGo)
│   │
│   ├── models/                     # 데이터 모델
│   │   ├── meeting.py              # Meeting
│   │   ├── contact.py              # Company, Person
│   │   └── action_item.py          # ActionItem
│   │
│   └── utils/                      # 유틸리티
│       ├── config.py               # 설정 로딩
│       ├── logger.py               # 로깅
│       ├── cache.py                # 캐싱
│       └── helpers.py              # 공통 함수
│
├── CLAUDE.md                       # 작업 기준 문서
├── .env.example                    # 환경 변수 템플릿
├── requirements.txt                # 의존성
└── README.md                       # 이 문서
```

## 🚀 시작하기

### 1. 환경 설정

```bash
# 저장소 클론
cd 260325_Clade_Meetagain

# 가상 환경 생성
python -m venv venv
source venv/bin/activate  # macOS/Linux
# 또는
venv\\Scripts\\activate  # Windows

# 의존성 설치
pip install -r requirements.txt
```

### 2. 환경 변수 설정

```bash
# .env.example를 .env로 복사
cp .env.example .env

# 필수 항목 설정
# - SLACK_BOT_TOKEN
# - SLACK_SIGNING_SECRET
# - ANTHROPIC_API_KEY
# - ANTHROPIC_MODEL (default: claude-sonnet-4-6)
# - GWS_CRED_FILE 또는 GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE (Google Workspace 인증)
# - TRELLO_API_KEY, TRELLO_API_TOKEN
```

### 3. Google Workspace 인증

```bash
# gws CLI 설치
pip install google-workspace-cli

# 초기 인증 (1회)
gws auth setup
```

### 4. 실행

#### 수동 실행 CLI

```bash
# Before Agent 정기 브리핑
python3 -m src.cli before

# company_knowledge 갱신
python3 -m src.cli before --update-company-knowledge

# 구조화된 미팅 생성
python3 -m src.cli create-meeting \
  --title "카카오 미팅" \
  --start 2026-03-25T15:00:00 \
  --end 2026-03-25T16:00:00 \
  --attendee user@kakao.com \
  --template client \
  --agenda "서비스 소개\n다음 단계 협의"

# During Agent만 실행
python3 -m src.cli during --meeting-id <EVENT_ID>

# 로컬 transcript 파일로 During 실행
python3 -m src.cli during --meeting-id <EVENT_ID> --transcript-file ./sample_transcript.txt

# 미팅 상태 조회
python3 -m src.cli status --meeting-id <EVENT_ID>

# During 후 After까지 연속 실행
python3 -m src.cli during --meeting-id <EVENT_ID> --trigger-after-agent

# Pipeline 직접 실행
python3 -m src.cli pipeline --meeting-id <EVENT_ID>

# 로컬 transcript 파일로 Pipeline 실행
python3 -m src.cli pipeline --meeting-id <EVENT_ID> --transcript-file ./sample_transcript.txt

# DRY_RUN 기준 end-to-end 스모크 테스트
python3 -m src.cli smoke --json

# 스모크 테스트 후 bundle까지 바로 출력/저장
python3 -m src.cli smoke --bundle
python3 -m src.cli smoke --bundle --save-bundle ./artifacts/latest_bundle.md

# client/internal/review 시나리오를 한 번에 검증
python3 -m src.cli smoke-suite
python3 -m src.cli smoke-suite --output-dir ./artifacts/smoke_suite_latest
python3 -m src.cli smoke-suite --json

# 시연용 결과물(smoke-suite + ops-export + doctor snapshot) 한 번에 생성
python3 -m src.cli demo
python3 -m src.cli demo --output-dir ./artifacts/demo_today
python3 -m src.cli demo --json

# 어젠다/템플릿을 포함한 스모크 테스트
python3 -m src.cli smoke \
  --title "카카오 미팅" \
  --attendee owner@parametacorp.com \
  --attendee user@kakao.com \
  --template client \
  --agenda "- 서비스 소개\n- 다음 단계 협의"

# 생성된 transcript/회의록/draft/state 묶음 조회
python3 -m src.cli bundle --meeting-id <EVENT_ID>
python3 -m src.cli bundle --meeting-id <EVENT_ID> --json
python3 -m src.cli bundle --meeting-id <EVENT_ID> --save ./artifacts/<EVENT_ID>_bundle.md

# 최근 실행된 meeting state 목록 조회
python3 -m src.cli list
python3 -m src.cli list --limit 20
python3 -m src.cli list --json
python3 -m src.cli list --save ./artifacts/meeting_list.md
python3 -m src.cli list --needs-after
python3 -m src.cli list --stalled-agenda
python3 -m src.cli list --follow-up-needed

# 전체 진행 현황과 주의 항목 대시보드
python3 -m src.cli dashboard
python3 -m src.cli dashboard --json
python3 -m src.cli dashboard --save ./artifacts/dashboard.md
python3 -m src.cli dashboard --needs-after
python3 -m src.cli dashboard --follow-up-needed

# DRY_RUN/캐시/최근 상태 기준 운영 점검
python3 -m src.cli doctor
python3 -m src.cli doctor --json
python3 -m src.cli doctor --save ./artifacts/doctor.md
python3 -m src.cli doctor --needs-after
python3 -m src.cli doctor --stalled-agenda

# 운영 점검 결과를 한 번에 파일로 저장
python3 -m src.cli ops-export
python3 -m src.cli ops-export --output-dir ./artifacts/ops_export_latest
python3 -m src.cli ops-export --include-bundles --bundle-limit 5
python3 -m src.cli ops-export --follow-up-needed
python3 -m src.cli ops-export --json

# Slack에서 최근 미팅/대시보드/운영 점검 확인
/meetagain help
/meetagain list 5
/meetagain dashboard 10 needs-after
/meetagain doctor 5 follow-up

# After Agent만 실행
python3 -m src.cli after --meeting-id <EVENT_ID>

# 상태 기반 재실행
python3 -m src.cli rerun --meeting-id <EVENT_ID> --stage auto
```

#### Slack 앱 실행

```bash
python3 -m src.app
```

Slash command 또는 멘션으로 다음 명령을 호출할 수 있습니다.

```text
/meetagain before
/meetagain create 카카오 미팅|2026-03-25T15:00:00|2026-03-25T16:00:00|user@kakao.com|서비스 소개
/meetagain create 카카오 미팅|2026-03-25T15:00:00|2026-03-25T16:00:00|user@kakao.com|서비스 소개|client
/meetagain create 내일 15:00 카카오 미팅 with user@kakao.com about 서비스 소개
/meetagain create 내일 오후 3:00 카카오 미팅 with user@kakao.com about 서비스 소개
/meetagain create 내일 15:00 카카오 미팅 with user@kakao.com about 서비스 소개 template review
/meetagain update-company-knowledge
/meetagain during <EVENT_ID>
/meetagain status <EVENT_ID>
/meetagain rerun <EVENT_ID> auto
/meetagain agenda <EVENT_ID> <AGENDA>
/meetagain after <EVENT_ID>
/meetagain pipeline <EVENT_ID>
```

#### 로컬 테스트

```bash
python3 -m unittest tests.test_before_agent_unittest tests.test_after_agent_unittest
python3 -m unittest tests.test_app_unittest tests.test_calendar_service_unittest
python3 -m unittest tests.test_during_agent_unittest tests.test_drive_service_unittest
python3 -m unittest tests.test_services_dry_run_unittest
python3 -m unittest tests.test_agents_dry_run_unittest
python3 -m unittest tests.test_pipeline_dry_run_unittest
python3 -m unittest tests.test_cli_unittest tests.test_meeting_state_unittest
```

## 📋 주요 기능

현재 구현 상태의 단일 기준은 [`docs/implementation_status.md`](docs/implementation_status.md)입니다.

### Before Agent

| 요구사항 | 기능 | 상태 |
|---------|------|------|
| FR-B01 | Calendar 24시간 조회 | ✅ |
| FR-B02 | 미팅 파싱 (외부 식별) | ✅ |
| FR-B03 | Contacts 로드 | ✅ |
| FR-B04 | 웹 검색 (업체) | ✅ |
| FR-B05 | 웹 검색 (인물) | ✅ |
| FR-B06 | company_knowledge 로드 | ✅ |
| FR-B06-2 | 이전 맥락 수집 | ✅ |
| FR-B07 | 브리핑 발송 (Draft) | ✅ |
| FR-B08 | 어젠다 등록 + Calendar 설명 업데이트 | ✅ |
| FR-B09~B12 | 미팅 생성/초대/채널 공유 | ⏳ 부분 구현 |
| FR-B13 | company_knowledge 갱신 | ✅ |
| FR-B14~B16 | 템플릿/Contacts 저장/어젠다 재활용 | ⏳ 부분 구현 |

### During Agent

| 요구사항 | 기능 | 상태 |
|---------|------|------|
| FR-D01 | transcript 로드 경로 정의 | ✅ |
| FR-D02~D04 | 회의록 2종 생성 및 저장 | ✅ |
| FR-D05~D06 | 액션 아이템·결정사항 추출 | ✅ |
| FR-D07~D11 | STT/Contacts/실시간 피드백 | ⏳ 부분 구현 |

### After Agent

| 요구사항 | 기능 | 상태 |
|---------|------|------|
| FR-A01 | 회의록 파싱 | ✅ |
| FR-A04 | Slack Draft 생성 | ✅ |
| FR-A05~A06 | Trello 체크리스트/카드 처리 | ✅ |
| FR-A07~A08 | 제안서·리서치 초안 생성 | ✅ |
| FR-A11 | 담당자 DM 알림 | ✅ |
| FR-A02~A03 | 회의록 완성도 보강 | ⏳ 부분 구현 |
| FR-A09~A10 | 멘션/Contacts 업데이트 | ⏳ 부분 구현 |
| FR-A12~A13 | 리마인더/후속 미팅 생성 | ⏳ 부분 구현 |

## 🔄 구현 단계

| Phase | 에이전트 | 상태 | 완료 |
|-------|---------|------|------|
| **현재** | Before | ⏳ 부분 구현 | 진행 중 |
| **현재** | During | ⏳ 부분 구현 | 진행 중 |
| **현재** | After | ⏳ 부분 구현 | 진행 중 |
| **다음** | Slack 진입점 고도화 / 자동화 | ⏳ 예정 | - |

## ⚙️ 설정 옵션

### 기능 플래그

```env
ENABLE_AGENDA_AUTO_REGISTER=true      # 어젠다 자동 등록
ENABLE_CONTACT_AUTO_SAVE=true         # 신규 연락처 자동 저장
ENABLE_CALENDAR_AGENDA_SYNC=true      # Calendar 메모 자동 동기화
```

### Trello 리스트 (7개)

- **Leads**: 신규 리드
- **Contact/Meeting**: 처음 미팅
- **Proposal**: 제안서 발송
- **Negotiation (On MoU)**: 계약 협상
- **수주**: 성약
- **Drop**: 거절·중단
- **대기**: 대기 중

### 캐싱 전략

- **업체 뉴스**: 7일 유효 (이후 갱신)
- **인물 정보**: Drive Contacts에서 우선 로드
- **company_knowledge**: 수정일 변경 시에만 읽음

### 실행 전제

- `DRY_RUN=true`로 두면 실제 외부 시스템 변경 없이 흐름 점검 가능
- `DRY_RUN=true`에서는 Drive 산출물을 `CACHE_DIR/dry_run_drive/` 아래 로컬 미러로 저장해 단계 간 재사용 가능
- transcript 파일은 `MeetingTranscripts/<EVENT_ID>.txt` 경로를 기준으로 읽음
- 회의록은 `MeetingNotes/<EVENT_ID>_client.md`, `MeetingNotes/<EVENT_ID>_internal.md`로 저장
- 생성 초안은 `GeneratedDrafts/` 아래에 저장
- 미팅 상태 파일은 `MeetingState/<EVENT_ID>.json`에 저장

## 📊 After Agent 내부 미팅 패키지

미팅 후 자동 생성되는 내부 미팅 패키지 구성:

1. **회의록** (클라이언트용 + 내부용)
   - 클라이언트용: 어젠다 + 결론 + To Do
   - 내부용: 클라이언트용 + 내부 의견 섹션

2. **액션 아이템 목록**
   - 담당자 · 작업 · 기한

3. **AI 검토의견** ⭐ 신규
   - 기존 커뮤니케이션 + 파라메타 정보 기반
   - 전략적 어드바이스 · 리스크 플래그 · 다음 단계 추천

4. **의사결정사항**
   - 검토의견 기반 정리

## 📚 문서

- [작업 기준 문서](CLAUDE.md)
- [프로젝트 브리프](docs/project_brief.md)
- [하네스](docs/harness.md)
- [요구사항 정의서 v2.3](docs/meeting-agent-requirements-v2_3.md)
- [구현 상태 정리](docs/implementation_status.md)
- [가이드라인](docs/guidelines.md)
- [용어집](docs/glossary.md)

## 🤝 기여하기

1. 기준 문서 검토 (docs/)
2. Phase별 요구사항 확인
3. PR 제출 전 테스트 실행

## 📞 연락처

질문사항이나 이슈는 프로젝트 저장소에서 확인하세요.

---

**마지막 업데이트**: 2026년 3월 25일  
**버전**: 1.1.0 (상태 정리 + 수동 실행 CLI)
