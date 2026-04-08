# MEETAGAIN — Channel Monitor Agent
## Product Requirements Document
**v1.0 | 2025.04.04 | Parametacorp 사업전략팀**

---

## 1. 개요 (Overview)

### 1.1 배경

Meetagain은 Slack 기반 AI 미팅 라이프사이클 에이전트로, Before / During / After 세 단계에 걸쳐 미팅의 준비·기록·후속 처리를 자동화합니다.

기존 After Agent는 transcript 기반으로 회의록과 액션아이템을 생성하고 Trello에 반영하는 구조입니다. 그러나 미팅 외 채널에서 발생하는 중요 정보(외부 미팅 정리, 의사결정, 보고 내용 등)는 수동으로 아카이빙해야 하는 불편함이 존재합니다.

### 1.2 문제 정의

> **Pain Point**
> - Slack 채널에 올라오는 미팅 정리, 의사결정, 보고 메시지를 매번 수동으로 Trello에 옮겨야 함
> - 아카이빙할 가치가 있는 메시지인지 매번 직접 판단해야 함
> - 누가 언제 작성한 내용인지 출처 정보가 유실됨
> - 액션아이템이 있어도 별도로 정리하지 않으면 누락됨

### 1.3 목표

- Slack 전체 채널을 상시 모니터링하여 아카이빙 가치 있는 메시지를 자동 감지
- 사용자 승인(컨펌) 후 Trello 카드에 코멘트 + 체크리스트 자동 등록
- 원작성자, 채널, 시간 등 출처 메타데이터 보존
- 핵심 액션아이템 추출 및 기한 포함 제안 (최대 3개)

---

## 2. 기능 범위 (Scope)

### 2.1 이번 버전에 포함

- Slack 전체 접근 가능 채널 실시간 모니터링
- Claude API 기반 아카이빙 가치 판단 (2단계 분류)
- Trello 보드/카드 자동 추천 (프로젝트 모니터 / 세일즈 파이프라인)
- 핵심 액션아이템 추출 (최대 3개, 기한 포함)
- Slack 스레드 기반 컨펌 UI (Block Kit)
- 승인 시 Trello 코멘트 + 체크리스트 자동 등록
- 원작성자 / 채널 / 시간 / 아카이빙 주체 메타데이터 포함
- 등록 완료 후 Trello 카드 직접 링크 Slack 전송

### 2.2 이번 버전에서 제외

- 카드 생성 (기존 카드에 코멘트 추가만)
- 체크리스트 완료 처리 자동화 (Trello에서 직접)
- DM / 스레드 답글 모니터링
- 메시지 수정 시 재분류

---

## 3. 사용자 시나리오 (User Story)

> **핵심 시나리오**
> 1. 외부 미팅 후 팀원이 Slack 채널에 미팅 정리 메시지를 올린다.
> 2. Meetagain이 해당 메시지를 감지하고 아카이빙 가치 여부를 판단한다.
> 3. 가치가 있다고 판단되면, 원본 메시지 스레드에 컨펌 메시지를 전송한다.
> 4. 사용자는 추천 카드와 액션아이템을 확인하고 [등록] 버튼을 누른다.
> 5. Trello 카드에 코멘트와 체크리스트가 자동으로 등록된다.
> 6. Slack에 완료 메시지와 Trello 링크가 전송된다.

### 3.1 컨펌 메시지 예시 (Slack Block Kit)

```
🤖 Meetagain 아카이빙 제안

📋 추천 카드: 세일즈 파이프라인 › 미래에셋증권
✍️  원작성자: 김우성(Woosung Kim)  |  #parasta_biz  |  4/3 11:45

⚡ 핵심 액션아이템
  • 미래에셋 특화 dApp UI/UX 추가 제작 — 담당자 지정 필요
  • VASP·증권성·KYC 법률 검토 요청 — 이번 주 내
  • PAXG형 금토큰 발행 방안 조사 — 다음 미팅 전

  [✅ 등록]  [🔄 카드 변경]  [❌ 건너뜀]
```

### 3.2 Trello 등록 결과

#### 코멘트

```
📋 [미래에셋증권 미팅 정리 - 4/3]
채널: #parasta_biz  |  작성자: 김우성(Woosung Kim)  |  11:45 AM
아카이빙: 류혁곤  |  2025-04-04 12:03
──────────────────────────────────
• 전략 쪽은 IT와 무관하게 코빗 지갑을 이용하는 사업 추진중
• 당사 테마틱 볼트 컨셉에 대해 긍정적 반응
• Supercycl thematic vault defi에 running profit 형태 제휴 서비스 합의
• 미래에셋 특화 dApp UI/UX 추가 제작 필요
• legal 해결되면 바로 진행 가능
• PAXG형 금토큰 발행 방안 모색 필요

⚡ 액션아이템
• 미래에셋 특화 dApp UI/UX 추가 제작 — 담당자 지정 필요
• VASP·증권성·KYC 법률 검토 요청 — 이번 주 내
• PAXG형 금토큰 발행 방안 조사 — 다음 미팅 전
──────────────────────────────────
🔗 Slack 원문 링크
```

#### 체크리스트

```
체크리스트명: ⚡ 액션아이템 (출처: 미래에셋 미팅 4/3)

  ☐ 미래에셋 특화 dApp UI/UX 추가 제작 — 담당자 지정 필요
  ☐ VASP·증권성·KYC 법률 검토 요청 — 이번 주 내
  ☐ PAXG형 금토큰 발행 방안 조사 — 다음 미팅 전

* 수정/삭제/완료 처리는 Trello에서 직접
```

---

## 4. 기능 상세 (Functional Spec)

### 4.1 채널 모니터링

| 항목 | 내용 |
|------|------|
| 모니터링 범위 | Meetagain이 초대된 전체 Slack 채널 |
| 감지 단위 | 채널 메시지 (DM, 스레드 답글 제외) |
| 처리 제외 | 봇 메시지, 파일 단독 첨부, 10자 미만 메시지 |
| 중복 처리 | 동일 메시지에 대해 컨펌 요청 1회만 발송 |

### 4.2 AI 판단 로직 (2단계)

#### 1단계: 아카이빙 가치 판단

아래 조건 중 1개 이상 해당 시 아카이빙 대상으로 분류:

- 외부 미팅 정리 / 회의록 요약
- 의사결정 내용 포함
- 외부 파트너·거래처의 반응 또는 입장
- 법률/리스크 검토 요청
- 액션아이템 또는 후속 조치 요청

#### 2단계: 보드 및 카드 추천

| 판단 기준 | 추천 보드 | 추천 카드 |
|----------|----------|----------|
| 회사명/거래처 언급 | 세일즈 파이프라인 | 해당 거래처 카드 |
| 프로젝트/기술/내부업무 | 프로젝트 모니터 | 관련 프로젝트 카드 |
| 판단 불가 | 사용자가 직접 선택 | 카드 변경 버튼 제공 |

> 카드 추천 방식: Trello API로 현재 카드 목록 조회 후 메시지 내용과 유사도 기반 매칭

### 4.3 액션아이템 추출

| 항목 | 내용 |
|------|------|
| 추출 개수 | 최대 3개 (핵심 위주) |
| 포함 정보 | 할 일 내용 + 기한 또는 시급도 |
| 기한 없을 경우 | "담당자 지정 필요" / "추후 논의" 등 컨텍스트 기반 표현 |
| 추출 불가 시 | 액션아이템 섹션 미표시 |

### 4.4 Slack 컨펌 UI

| 버튼 | 동작 |
|------|------|
| ✅ 등록 | 추천 카드에 코멘트 + 체크리스트 즉시 등록 → 완료 메시지 + Trello 링크 전송 |
| 🔄 카드 변경 | 보드 내 카드 목록 표시 → 사용자가 직접 선택 → 등록 진행 |
| ❌ 건너뜀 | 컨펌 메시지 dismiss, 아무 처리 없음 |

### 4.5 Trello 등록

| 항목 | 내용 |
|------|------|
| 등록 방식 | 기존 카드에 코멘트 추가 (카드 생성 없음) |
| 코멘트 내용 | 원문 메시지 전체 + 메타데이터 + 액션아이템 |
| 체크리스트 | 카드에 신규 체크리스트 추가 (액션아이템 기반) |
| 등록 주체 | Meetagain 봇 계정 (작성자 표기는 코멘트 내 메타데이터로) |
| 수정/삭제 | Trello에서 직접 처리 |

---

## 5. 시스템 아키텍처

### 5.1 전체 흐름

```
Slack 채널 메시지 수신 (Slack Bolt event_handler)
  ↓
channel_monitor_agent.py — 1단계 가치 판단 (Claude API)
  ↓ (가치 있음)
trello_service.py — 카드 목록 조회 + 추천 카드 선정
  ↓
channel_monitor_agent.py — 2단계 액션아이템 추출 (Claude API)
  ↓
slack_service.py — 스레드에 Block Kit 컨펌 메시지 전송
  ↓ (사용자 [✅ 등록] 클릭)
trello_service.py — 코멘트 등록 + 체크리스트 등록
  ↓
slack_service.py — 완료 메시지 + Trello 카드 링크 전송
```

### 5.2 신규/수정 파일

| 파일 | 구분 | 변경 내용 |
|------|------|----------|
| `agents/channel_monitor_agent.py` | **신규** | 전체 채널 모니터링, AI 판단, 액션아이템 추출 |
| `services/trello_service.py` | 수정 | 카드 목록 조회, 카드 추천, 코멘트/체크리스트 등록 함수 추가 |
| `services/slack_service.py` | 수정 | Block Kit 컨펌 메시지 전송, 인터랙션 핸들러 추가 |
| `app.py` | 수정 | channel_monitor_agent 이벤트 핸들러 등록 |

---

## 6. 구현 스펙 (Implementation Spec)

### 6.1 channel_monitor_agent.py 핵심 함수

```python
async def should_archive(message: str) -> bool:
    """1단계: 아카이빙 가치 여부 판단 — Claude API 호출 → True/False 반환"""

async def extract_action_items(message: str) -> list[dict]:
    """액션아이템 추출 (최대 3개)
    반환: [{'task': str, 'deadline': str}, ...]
    """

async def recommend_trello_card(message: str, cards: list) -> dict:
    """카드 목록과 메시지 내용 기반 추천 카드 선정
    반환: {'board': str, 'card_id': str, 'card_name': str}
    """

async def handle_channel_message(event, client, say):
    """Slack Bolt 이벤트 핸들러 (메인 진입점)"""

async def handle_archive_action(ack, body, client):
    """Block Kit 버튼 인터랙션 처리 ([등록] / [카드 변경] / [건너뜀])"""
```

### 6.2 Claude API 프롬프트 설계

#### 1단계: 가치 판단 프롬프트

```
[System]
당신은 Slack 메시지를 분석하여 비즈니스 아카이빙 가치를 판단하는 AI입니다.
아래 조건 중 하나 이상 해당하면 true, 그렇지 않으면 false를 반환하세요.

아카이빙 가치 기준:
- 외부 미팅/회의 정리 내용
- 의사결정 사항
- 외부 파트너/거래처의 반응 또는 입장
- 법률/리스크 검토 요청
- 구체적인 액션아이템 또는 후속 조치

JSON 형식으로만 응답: {"archive": true/false, "reason": "한 줄 이유"}
```

#### 2단계: 액션아이템 추출 프롬프트

```
[System]
당신은 Slack 메시지에서 핵심 액션아이템을 추출하는 AI입니다.
최대 3개, 각 항목은 '무엇을 해야 하는지'와 '기한 또는 시급도'를 포함하세요.
기한이 명시되지 않은 경우 컨텍스트 기반으로 추정하거나 '담당자 지정 필요'로 표현하세요.

JSON 형식으로만 응답:
[{"task": "할 일", "deadline": "기한 또는 시급도"}, ...]
액션아이템이 없으면 빈 배열 []을 반환하세요.
```

#### 3단계: 카드 추천 프롬프트

```
[System]
당신은 Slack 메시지 내용을 보고 가장 적합한 Trello 카드를 추천하는 AI입니다.

보드 선택 기준:
- 회사명/거래처 언급 → 세일즈 파이프라인
- 프로젝트/기술/내부업무 → 프로젝트 모니터

카드 목록과 메시지를 비교하여 가장 관련 높은 카드를 선택하세요.

JSON 형식으로만 응답:
{"board": "보드명", "card_id": "카드ID", "card_name": "카드명", "confidence": 0.0~1.0}
```

### 6.3 trello_service.py 추가 함수

```python
def get_all_cards_from_boards(board_ids: list) -> list[dict]:
    """지정 보드의 전체 카드 목록 조회"""

def add_comment_to_card(card_id: str, comment: str) -> bool:
    """카드에 코멘트 추가"""

def add_checklist_to_card(card_id: str, name: str, items: list[str]) -> bool:
    """카드에 체크리스트 추가"""

def format_archive_comment(message: str, meta: dict, action_items: list) -> str:
    """코멘트 포맷 생성 (메타데이터 + 원문 + 액션아이템)"""
```

### 6.4 환경 변수 추가

```env
TRELLO_PROJECT_BOARD_ID=   # 프로젝트 모니터 보드 ID
TRELLO_SALES_BOARD_ID=     # 세일즈 파이프라인 보드 ID
CHANNEL_MONITOR_ENABLED=true  # 모니터링 on/off 토글
```

---

## 7. 비기능 요구사항

| 항목 | 요구사항 |
|------|----------|
| 응답 속도 | 메시지 수신 후 컨펌 메시지 전송까지 5초 이내 |
| 중복 방지 | 동일 메시지에 컨펌 요청 중복 발송 방지 (메시지 ts 기반 dedup) |
| 오류 처리 | Claude API / Trello API 호출 실패 시 사용자에게 오류 안내 |
| 로깅 | 판단 결과 (archive 여부, 추천 카드, 액션아이템) 로그 기록 |
| 모니터링 토글 | `CHANNEL_MONITOR_ENABLED` 환경 변수로 전체 기능 on/off 가능 |

---

## 8. 구현 일정 (안)

| 단계 | 작업 | 산출물 |
|------|------|--------|
| Day 1 | `channel_monitor_agent.py` 기본 구조 + 1단계 판단 로직 | 가치 판단 동작 확인 |
| Day 2 | Trello 카드 추천 + 액션아이템 추출 | 추천 카드 + 액션아이템 출력 |
| Day 3 | Slack Block Kit 컨펌 UI + 인터랙션 핸들러 | 버튼 동작 확인 |
| Day 4 | Trello 코멘트 + 체크리스트 등록 | Trello 실제 등록 확인 |
| Day 5 | 통합 테스트 + 엣지케이스 처리 | 전체 플로우 검증 |

---

## 9. 성공 지표 (Success Metrics)

- 아카이빙 가치 판단 정확도: 실제 유용 메시지 중 감지율 **80% 이상**
- 카드 추천 정확도: 첫 번째 추천 카드 수락률 **70% 이상**
- 컨펌 버튼 승인률: **50% 이상** (건너뜀이 절반 미만)
- Trello 등록 오류율: **1% 미만**

---

*Meetagain Channel Monitor PRD v1.0 | Parametacorp 사업전략팀*
