# GitHub 릴리즈 정리

## 저장소 설명 추천

```text
Slack-based AI meeting lifecycle agent for briefing, transcript processing, follow-up automation, and Trello/Contacts sync.
```

## 저장소 짧은 소개 문구 추천

```text
Slack에서 미팅 생성, 브리핑, 회의록, 액션아이템, 제안서 초안, Trello 후속 처리를 연결하는 AI 미팅 에이전트
```

## GitHub Topics 추천

```text
slack-bot
meeting-agent
ai-agent
meeting-notes
calendar-automation
trello
anthropic
google-workspace
productivity
python
```

## 릴리즈 노트 초안

### v0.1.0

- Slack 자연어 미팅 생성 추가
- Google Calendar / Google Meet 생성 연동
- 브리핑 생성 플로우 추가
- transcript 업로드 기반 회의록 처리 추가
- 결정사항 / 액션아이템 추출 추가
- Trello 체크리스트 반영 추가
- 회사 문서 / 인물 문서 업데이트 추가
- 제안서 초안 생성 추가

## 공개 전 체크리스트

- `.env` 미포함 확인
- `cache/`, `artifacts/` 미포함 확인
- `company_knowledge.md` 미포함 확인
- README 최신화 확인
- 기본 실행 명령 확인
- 데모/실서비스 구분 문구 확인

## 운영 MVP 범위 제안

- 유지
  - Slack 미팅 생성
  - 브리핑
  - transcript 업로드 처리
  - 회의록 생성
  - 액션아이템 추출
  - Trello 반영
  - Contacts 문서 업데이트

- 조건부 유지
  - 제안서 초안 생성
  - 리서치 초안 생성

- 후순위
  - Meet 종료 자동 감지
  - 실시간 피드백
  - 완전 자유대화형 Slack UX
