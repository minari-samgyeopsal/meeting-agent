# Meetagain

Slack 안에서 미팅의 준비, 기록, 후속 처리를 연결하는 AI 미팅 라이프사이클 에이전트입니다.

- Before: 브리핑 생성
- During: transcript 기반 회의록 생성
- After: 액션아이템, 제안서 초안, Trello, Contacts 후속 처리

## 핵심 기능

- 자연어 기반 미팅 생성
  - Slack 메시지로 미팅 생성
  - Google Calendar 일정 및 Google Meet 링크 생성
- 미팅 전 브리핑
  - 회사/인물 정보
  - 최근 맥락
  - 어젠다 요약
- transcript 기반 후처리
  - 클라이언트용/내부용 회의록
  - 결정사항 / 액션아이템 추출
  - 제안서 초안 / 리서치 초안 조건부 생성
  - Trello 체크리스트 반영
  - 회사 문서 / 인물 문서 업데이트

## 현재 동작 방식

### 1. 미팅 생성

Slack에서 자연어로 미팅을 생성할 수 있습니다.

예시:

```text
@hackathon_meetingagent 오늘 오후 3시 카카오와 미팅 잡아줘 목적은 PoC 제안이야
```

### 2. 미팅 브리핑

생성된 미팅이나 오늘 일정 기준으로 브리핑을 요청할 수 있습니다.

예시:

```text
@hackathon_meetingagent 오늘미팅 브리핑해줘
```

### 3. transcript 업로드 후 회의록 정리

Slack에서 transcript 파일을 업로드한 뒤 정리를 요청할 수 있습니다.

예시:

```text
이 파일로 회의록 정리해줘
```

설명이 부족하면 봇이 최근 미팅 후보를 보여주고 어느 미팅에 연결할지 다시 묻습니다.

### 4. transcript 업로드 기반 정리

Slack에서 transcript 파일(`txt`, `md`, `srt`, `vtt`)을 올리면 Meetagain이:

1. 미팅 연결 대상을 확인하고
2. 회의록을 생성한 뒤
3. 추가 후속 작업 여부를 다시 묻습니다.

## 아키텍처

### Before Agent
- Calendar 일정 조회
- 외부 미팅 식별
- 브리핑 데이터 수집
- Slack 브리핑 초안 생성

### During Agent
- transcript 처리
- 회의록 구조화
- 클라이언트용 / 내부용 회의록 생성

### After Agent
- 결정사항 / 액션아이템 파싱
- Slack 요약 생성
- Trello 업데이트
- Contacts 문서 업데이트
- 제안서 / 리서치 초안 생성

### Channel Monitor v1
- 기본값은 일일 배치 전용
- 필요할 때만 개인 DM 실시간 감지
- 채널/비공개채널 일일 배치 수집
- 아카이빙 가치 판단
- Trello 카드 추천
- 액션아이템 최대 3개 추출
- Slack 스레드 확인용 Block Kit payload 생성
- 애매한 메시지는 리뷰 큐로 별도 집계

## 기술 스택

- Python
- Slack Bolt
- Anthropic Claude
- Google Workspace CLI (`gws`)
- Trello API

## 프로젝트 구조

```text
src/
  agents/
    before_agent.py
    during_agent.py
    after_agent.py
  services/
    calendar_service.py
    drive_service.py
    gmail_service.py
    slack_service.py
    trello_service.py
    search_service.py
  models/
  utils/
docs/
tests/
scripts/
```

## 빠른 시작

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 변수 설정

`.env.example`를 참고해 `.env`를 구성합니다.

필수 예시:

```env
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
SLACK_APP_TOKEN=
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6
TRELLO_API_KEY=
TRELLO_API_TOKEN=
```

### 3. 앱 실행

```bash
python3 -m src.app
```

### 4. 테스트 실행

```bash
python3 -m unittest tests.test_app_unittest
python3 -m unittest tests.test_after_agent_unittest
python3 -m unittest tests.test_calendar_service_unittest
python3 -m unittest tests.test_channel_monitor_agent_unittest
python3 -m unittest tests.test_cli_unittest tests.test_services_dry_run_unittest
```

### 5. 채널 모니터 일일 배치

전일 `17:00`부터 당일 `17:00`까지 지정 채널을 수집하고, 자동 제안과 리뷰 후보를 같이 만듭니다.

```bash
python3 -m src.cli channel-monitor-daily --channel C01234567 --json
```

리뷰 큐를 본인 DM이나 지정 채널로 보내려면:

```bash
python3 -m src.cli channel-monitor-daily --channel C01234567 --send-dm-email me@parametacorp.com
python3 -m src.cli channel-monitor-daily --channel C01234567 --send-channel D01234567
```

환경 변수로 기본 대상을 고정할 수도 있습니다.
- `CHANNEL_MONITOR_BATCH_HOUR`
- `CHANNEL_MONITOR_TARGET_CHANNELS`
- `CHANNEL_MONITOR_REVIEW_DM_EMAIL`
- `CHANNEL_MONITOR_REVIEW_CHANNEL`
- `ENABLE_CHANNEL_MONITOR_REALTIME=false`

## 운영/설계 문서

- [요구사항 문서](/Users/minhwankim/workspace/260325_Clade_Meetagain/docs/meeting-agent-requirements-v2_3.md)
- [구현 현황](/Users/minhwankim/workspace/260325_Clade_Meetagain/docs/implementation_status.md)
- [LLM 사용 정리](/Users/minhwankim/workspace/260325_Clade_Meetagain/docs/llm_usage.md)
- [제출 문서](/Users/minhwankim/workspace/260325_Clade_Meetagain/SUBMISSION.md)

## 현재 상태

현재 프로젝트는 해커톤 데모를 거쳐 라이브 안정화 단계로 넘어가는 중입니다.

이미 확인된 흐름:
- Slack 자연어 미팅 생성
- Google Calendar + Meet 링크 생성
- transcript 업로드 기반 회의록 생성
- 액션아이템 추출
- Trello 반영
- 회사/인물 문서 생성

남은 과제:
- transcript와 미팅 자동 매칭 UX 고도화
- 화자명/참석자명 매핑 품질 개선
- Slack 결과 포맷 polishing
- 라이브 운영 안정성 강화
