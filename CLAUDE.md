# 미팅 에이전트 프로젝트 (260325_CLADE_MEETAGAIN)

작업 시작 전 반드시 읽을 것

아래 문서를 순서대로 읽고 컨텍스트를 잡은 뒤 작업을 시작한다.

docs/meeting-agent-requirements-v2_3.md — 개발의 1차 기준 문서(PRD / 요구사항 정의서)
docs/project_brief.md — 프로젝트 목적, 범위, 성공 기준에 대한 상위 배경 문서
docs/guidelines.md — 공통 AI 협업 원칙 (상위 운영 원칙)
docs/glossary.md — 용어 정의 (중의적 용어 해석 기준)
docs/harness.md — 기획 단계에서 문서를 정리할 때 사용한 작업 경계 문서 (개발 단계에서는 참고용)
문서 해석 원칙
meeting-agent-requirements-v2_3.md를 개발의 직접 기준 문서로 사용한다.
project_brief.md, guidelines.md, glossary.md, harness.md는 배경, 제약, 용어 해석을 위한 참고 문서로 사용한다.
참고 문서와 PRD 간 해석 충돌이 발생하면, 임의로 확장하거나 추정하지 말고 충돌 지점을 명시한 뒤 확인한다.

---

## 프로젝트 개요
            
- **프로젝트명**: 미팅 에이전트
- **목적**: Slack 하나로 외부 미팅의 준비(브리핑), 기록(회의록), 후속 처리(Trello·Contacts·내부 미팅 패키지)를 자동화하는 1인용 미팅 라이프사이클 에이전트
- **주요 사용자**: 1인 실무 담당자
- **인터페이스**: Slack 단일 채널 (DM + 공용 채널 + Slash Command)
- **사내 도메인**: @parametacorp.com · @iconloop.com

## 기술 스택

- **Google 연동**: gws CLI (Drive · Calendar · Meet · Gmail 통합)
- **커뮤니케이션**: Slack MCP
- **파이프라인**: Trello API
- **AI**: Claude API + Web Search

## 에이전트 구조

```
미팅 에이전트 (오케스트레이터)
├── Before Agent   — 미팅 전 준비 (브리핑, 일정, 리서치)
├── During Agent   — 미팅 중 지원
└── After Agent    — 미팅 후 처리 (회의록, 후속 액션)
```

---

## 작업 원칙 (guidelines.md 핵심 요약)

- 요청 범위를 벗어나 임의로 확장하지 않는다
- 불확실한 사항은 추정하지 말고 미확정으로 명시한다
- 문서 우선순위: `harness.md` → `project_brief.md` → 작업 문서
- 전체 구조 합의 후 세부 작업을 진행한다
- 검증 전에는 완료로 간주하지 않는다

---

## 허용 / 금지 작업 (harness.md 핵심 요약)

### 허용
- 요구사항 정의서 v2.3 범위 내 구현
- Before / During / After Agent 단계적 구현
- gws CLI 기반 Google Workspace 연동
- Slack MCP 기반 메시지 처리
- Trello API 체크리스트 추가

### 금지
- 요구사항 범위 외 기능 임의 추가
- Trello 카드 이동 (수동 처리 항목)
- 전문 에이전트 위임 기능 선구현 (추후 단계)
- 승인 없이 문서 구조 변경
- 사용자 확인 전 산출물 확정

---

## 구현 순서

1. **Phase 1**: Before Agent (FR-B01 ~ FR-B16)
2. **Phase 2**: During Agent (FR-D01 ~ FR-D11)
3. **Phase 3**: After Agent (FR-A01 ~ FR-A13)
4. **공통**: CM-01 ~ CM-08 (전 단계 공통 적용)

---

## 의사결정 원칙

- 불확실한 사항은 임의 판단하지 않고 반드시 확인 후 진행
- 각 Phase 완료 후 검증 단계를 거친 뒤 다음 Phase 진행
- 문서와 코드는 항상 동기화 상태 유지