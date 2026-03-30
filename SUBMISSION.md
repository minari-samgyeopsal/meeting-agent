# Meetagain — PARAIX Hackathon 제출서

## 1. 팀 정보
- 팀명 : [직접 입력]
- 팀원 : [직접 입력]
- 직군 구성 : [직접 입력]

## 2. 프로젝트 개요
- 해결하려는 문제 (1-2줄)
  외부 미팅은 일정 생성, 사전 브리핑, 회의록 정리, 액션아이템 추적, 후속 제안까지 여러 도구에 흩어져 있어 준비와 후속 실행이 자주 끊깁니다. 특히 소규모 팀이나 1인 담당자는 미팅 전후 맥락을 일관되게 관리하기 어렵습니다.
- 솔루션 한 줄 요약
  Slack을 중심으로 미팅 전 브리핑, 미팅 후 회의록/액션아이템/후속 초안/Trello 반영까지 연결하는 AI 기반 미팅 라이프사이클 자동화 도구입니다.

## 3. 주제 트랙
- [ ] 트랙 A : 블록체인 관련 제품/서비스
- [x] 트랙 B : 업무 자동화/혁신 툴

## 4. AI 활용 방식 및 주요 프롬프트
- 어떤 AI 도구를 어떻게 사용했는가
  현재 코드 기준으로 Anthropic Claude API를 핵심 생성 엔진으로 사용합니다. `BeforeAgent`에서는 미팅 브리핑과 회사 정보 문서 갱신에, `DuringAgent`에서는 transcript를 구조화된 회의 데이터로 정리하는 데, `AfterAgent`에서는 회의록 파싱, 결과 요약, 제안서 초안, 리서치 초안, 내부 검토 의견 생성에 사용합니다. 웹 검색은 DuckDuckGo 기반 `SearchService`, 업무 연동은 Google Workspace(`gws` CLI), Slack, Trello를 사용합니다.
- 기존 방식 대비 달라진 점
  기존에는 Calendar, Gmail, 검색, Trello, 회의록 정리를 각각 사람이 확인해야 했지만, 현재 구현은 `Before → During → After` 흐름으로 연결됩니다. 일정 생성, 브리핑, 회의록 생성, 액션아이템 추출, Trello 체크리스트 반영, 후속 초안 생성까지 하나의 Slack 중심 흐름으로 이어지며, `meeting state`를 저장해 상태 조회와 재실행도 가능하게 만들었습니다.
- 실제 사용한 주요 프롬프트 (필수 포함)
  1. 브리핑 생성 프롬프트
     - 위치: [before_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/before_agent.py)
     - 핵심 내용: 미팅 제목, 시간, 참석자, 회사 정보, 참석자 정보, 이전 맥락, 기존 어젠다, 회사 서비스 정보를 바탕으로 한국어 미팅 브리핑을 생성하도록 요청합니다.
  2. transcript 구조화 프롬프트
     - 위치: [during_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/during_agent.py)
     - 핵심 내용: transcript를 분석해 `meeting_title`, `attendees`, `agenda`, `summary`, `discussion_points`, `decisions`, `action_items`, `next_steps`, `internal_notes`, `agenda_status`를 포함한 JSON만 반환하도록 요청합니다.
  3. 회의록 파싱 프롬프트
     - 위치: [after_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/after_agent.py)
     - 핵심 내용: 내부 회의록에서 참석자, 배경, 논의사항, 결정사항, 액션아이템, 다음 단계, Contacts 업데이트 후보, 후속 미팅 제안을 JSON으로 추출하도록 요청합니다.
  4. 제안서 초안 생성 프롬프트
     - 위치: [after_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/after_agent.py)
     - 핵심 내용: 미팅 배경과 결정사항을 바탕으로 `소개`, `현황 분석`, `솔루션 제안`, `구현 계획`, `예상 효과`, `투자 및 조건` 구조의 마크다운 제안서 초안을 생성하도록 요청합니다.
  5. 리서치 초안 생성 프롬프트
     - 위치: [after_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/after_agent.py)
     - 핵심 내용: 미팅 내용과 회사 맥락을 바탕으로 `시장 분석`, `경쟁사 분석`, `기술 트렌드`, `규제 환경`, `기회 요인`, `리스크 요인`, `제안` 구조의 리서치 초안을 생성하도록 요청합니다.

## 5. 주요 기능 설명
- 미팅 전 브리핑 자동화
  Google Calendar 일정, 참석자, Contacts, 웹 검색, Gmail/Trello의 이전 맥락을 모아 Slack에서 바로 읽을 수 있는 미팅 브리핑을 생성합니다.
- 미팅 후 회의록 및 후속 정리
  transcript를 기반으로 클라이언트용/내부용 회의록을 생성하고, 결정사항과 액션아이템을 추출해 Slack 결과 카드로 보여줍니다.
- 실행 가능한 후속 처리 연결
  액션아이템을 Trello 체크리스트로 반영하고, Slack 요약 초안, Contacts 업데이트 후보, 후속 미팅 초안, 제안서/리서치 초안을 생성합니다.

## 6. 시연 링크 / 실행 방법
- URL : [직접 입력]
- 실행 방법 (링크가 없는 경우 간단히 기술)
  1. `.env`를 설정하고 `python3 -m src.app`으로 Slack 앱을 실행합니다.
  2. Slack에서 `@hackathon_meetingagent 오늘미팅 브리핑해줘`로 브리핑을 확인합니다.
  3. `/meetagain create 내일 오후 5:30 카카오 미팅 with macmihwan@gmail.com about poc 제안`으로 미팅을 생성합니다.
  4. `@hackathon_meetingagent 방금 미팅 결과 보여줘`로 회의 결과 요약을 확인하고, Trello 반영 여부를 이어서 확인합니다.

## 7. 아쉬운 점 / 개선 여지
- 현재 구현은 실제 Slack/Calendar/Trello 연동이 되지만, 일부 경로는 여전히 fallback 처리와 혼합되어 있습니다.
- Google Drive 저장은 최신 `gws` CLI 문법 대응 과정에 있어 일부 경로에서 로컬 캐시 fallback을 사용합니다.
- 자연어 미팅 생성은 지원하지만 slash command에 비해 안정성이 아직 낮습니다.
- Google Meet transcript 자동 수집은 완전한 실시간 연동보다 통제된 입력/샘플 기반 검증 비중이 큽니다.
- 업체별 브리핑 품질은 편차가 있으며, 현재는 카카오 시나리오처럼 특정 데모 케이스를 우선 보강한 상태입니다.

## 8. 기대 효과
- 미팅 준비, 회의록 작성, 액션아이템 추적, 후속 제안까지 이어지는 반복 업무를 하나의 Slack 중심 흐름으로 묶어 업무 전환 비용을 줄일 수 있습니다.
- 미팅 직후 실행력이 가장 중요한 구간에서 회의록, 액션아이템, Trello 반영, 후속 초안 생성이 자동으로 이어져 후속 속도를 높일 수 있습니다.
- 개인 또는 소규모 팀도 대기업 수준의 미팅 운영 체계를 가볍게 도입할 수 있어 영업, 제휴, 사업개발 생산성 향상에 직접적인 도움이 됩니다.
