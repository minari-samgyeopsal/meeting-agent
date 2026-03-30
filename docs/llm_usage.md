# Meetagain LLM Usage 정리

이 문서는 현재 코드 기준으로 **LLM(Anthropic)** 이 어디에 사용되는지, 어떤 입력/출력을 다루는지, 실패 시 어떻게 fallback 되는지, 그리고 운영 관점에서 어떤 리스크가 있는지를 정리한 문서입니다.

기준 파일:
- [src/app.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/app.py)
- [src/agents/before_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/before_agent.py)
- [src/agents/during_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/during_agent.py)
- [src/agents/after_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/after_agent.py)
- [src/utils/config.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/utils/config.py)

## 공통 설정

- LLM 공급자: `Anthropic`
- 기본 모델 설정: `Config.ANTHROPIC_MODEL`
- 기본값:
  - `claude-sonnet-4-6`
- API 키 설정:
  - `ANTHROPIC_API_KEY`

코드 기준 LLM 클라이언트 초기화:
- `Anthropic()` 직접 생성
- 또는 agent init 시 `self.claude_client = Anthropic() if Config.ANTHROPIC_API_KEY else None`

## 전체 사용처 요약

현재 LLM은 크게 6군데에 사용됩니다.

1. Slack 자연어 intent 라우팅
2. DM 잡담/자유대화 fallback 응답
3. 미팅 전 브리핑 생성
4. transcript/회의록 구조화
5. 미팅 후 AI review 생성
6. 제안서/리서치 초안 생성

## 1. Slack 자연어 intent 라우팅

위치:
- [src/app.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/app.py)
- 함수: `_route_with_llm()`

역할:
- 사용자의 자유 자연어 메시지를 액션으로 분류
- 현재 지원 액션:
  - `create_meeting`
  - `before`
  - `bundle`
  - `status`
  - `doctor`
  - `agenda`
  - `help`
  - `none`

입력:
- Slack 메시지 원문
- 오늘 날짜
- 타임존
- 액션 스키마 설명

출력:
- JSON
- 예:
```json
{"action":"create_meeting","title":"카카오 미팅","date":"2026-03-27","time":"17:30","duration_minutes":60,"agenda":"poc 제안"}
```

후속 처리:
- `_dispatch_routed_intent()` 에서 실제 액션 실행

실패 시 fallback:
- JSON 파싱 실패 / 모델 호출 실패 / API 실패 시 `None`
- 그러면 기존 규칙 기반 파서나 일반 fallback 로직으로 넘어감

특징:
- 현재는 완전 자유대화형 엔진이 아니라,
  - 규칙 기반 파서
  - LLM 라우터
  - help/chat fallback
의 혼합 구조

운영 리스크:
- 잘못 분류되면 잘못된 액션 실행 가능
- 그러나 현재는 액션 종류가 제한적이라 비교적 통제 가능

## 2. DM 잡담/자유대화 fallback 응답

위치:
- [src/app.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/app.py)
- 함수: `_chat_fallback_reply()`

역할:
- DM에서 사용자가 애매한 문장이나 잡담을 보냈을 때
- 명령어 help만 내보내지 않고 짧은 대화형 응답 제공

입력:
- 사용자 자유 메시지

출력:
- 1~2문장 정도의 짧은 응답
- “미팅 생성, 브리핑, 회의 결과 정리, transcript 파일 처리 중 하나를 도와드릴 수 있다”는 식의 안내

실패 시 fallback:
- LLM 호출 실패 시 정적 안내문 반환

운영 리스크:
- 비용은 작지만 빈번한 DM 잡담이 많아지면 누적 호출 증가 가능

권장:
- 운영 환경에선 짧은 잡담은 규칙 기반으로 우선 처리하고
- 정말 애매한 경우에만 LLM fallback 을 쓰는 현재 방식이 적절함

## 3. 미팅 전 브리핑 생성

위치:
- [src/agents/before_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/before_agent.py)
- 함수: `_generate_briefing()`

역할:
- 미팅 전 수집한 정보로 브리핑 텍스트 생성
- 수집 정보:
  - 회사 정보
  - 인물 정보
  - 서비스 연결점
  - 이전 맥락
  - 기존 어젠다

입력:
- `meeting`
- `_collect_briefing_data()` 결과

출력:
- Slack에 보여줄 브리핑 텍스트

실패 시 fallback:
- DRY_RUN이면 데모용 또는 짧은 템플릿형 브리핑
- live에서도 LLM 실패 시 템플릿형 브리핑으로 fallback 가능

중요한 전제:
- [company_knowledge.md](/Users/minhwankim/workspace/260325_Clade_Meetagain/company_knowledge.md) 가 있으면 품질이 크게 좋아짐
- 이 파일이 없으면 브리핑은 가능해도 자사 관점 연결점이 약해짐

운영 리스크:
- 웹 검색, 인물정보, 회사정보 품질에 따라 결과 편차 큼
- 회사별 특화가 없으면 일반적이고 약한 브리핑이 나올 수 있음

비용:
- 미팅 수만큼 1회 호출
- 보통 부담은 중간 수준

## 4. transcript / 회의록 구조화

위치:
- [src/agents/during_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/during_agent.py)
- `messages.create()` 호출 지점

역할:
- transcript 텍스트를 받아
- 회의록 구조로 정리
- 주요 결론, 액션아이템, 다음 단계 등을 추출

입력:
- transcript 원문
- 미팅 메타데이터

출력:
- 클라이언트용 회의록
- 내부용 회의록
- 상태 업데이트용 구조화 결과

실패 시 fallback:
- 구조화 실패 시 rule-based / section-based fallback 사용
- transcript 본문에서 `어젠다`, `주요 결론`, `To Do`, `다음 단계`를 직접 읽는 경로 존재

현재 상태:
- transcript만 있으면 큰 흐름은 잘 도는 편
- 다만 화자명이 `화자 1`, `참석자 1` 식이면 사람 이름 매핑은 불완전할 수 있음

운영 리스크:
- transcript 품질에 강하게 의존
- 화자 라벨이 불명확하면 액션아이템 담당자 품질 저하

비용:
- transcript 길이가 길수록 비용 증가
- 전체 파이프라인에서 비용 영향이 비교적 큰 편

## 5. 미팅 후 AI review 생성

위치:
- [src/agents/after_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/after_agent.py)
- 함수: `_generate_ai_review()`

역할:
- 미팅 후 전략적 검토의견 생성
- 포함 내용:
  - 결과 평가
  - 전략적 기회
  - 리스크
  - 다음 단계 추천
  - 담당자 팁

입력:
- `company_knowledge`
- 업체 정보
- 최근 이메일
- 결정사항 / 액션아이템 요약

출력:
- Slack draft 등에 포함될 AI review 텍스트

실패 시 fallback:
- `"검토의견 생성 실패로 기본 후속 정리만 제공됩니다."`

운영 리스크:
- 품질은 좋지만 필수 기능은 아님
- 비용/지연이 있을 수 있어, 필요하면 옵션화 가능

권장:
- 운영 MVP에서는 유지 가능
- 다만 응답 속도가 중요하면 비동기 후속 생성으로 분리하는 것도 고려 가능

## 6. 제안서 초안 생성

위치:
- [src/agents/after_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/after_agent.py)
- 함수: `_create_proposal_draft()`

트리거:
- `_needs_proposal_draft()` 가 참일 때
- 키워드 예:
  - `제안서`
  - `proposal`
  - `견적`
  - `제안`
  - `poc 제안`

역할:
- 회의 내용 기반 제안서 초안 생성

입력:
- parsed_data
- 회의 배경
- 결정사항
- 액션아이템
- company_knowledge

출력:
- `GeneratedDrafts/<meeting_id>_proposal.md`

실패 시 fallback:
- 기본 제안서 초안 문구 생성

운영 리스크:
- 꽤 유용하지만 토큰 비용이 큼
- 모든 미팅마다 돌리는 것보다
  - 제안성 미팅
  - 키워드 기반
  - 사용자가 요청한 경우
에만 생성하는 현재 방식이 적절함

## 7. 리서치 초안 생성

위치:
- [src/agents/after_agent.py](/Users/minhwankim/workspace/260325_Clade_Meetagain/src/agents/after_agent.py)
- 함수: `_create_research_draft()`

트리거:
- `_needs_research_draft()` 가 참일 때
- 키워드 예:
  - `리서치`
  - `research`
  - `조사`
  - `시장 분석`
  - `경쟁사 분석`

역할:
- 회의 후 시장/경쟁/리서치 초안 생성

출력:
- `GeneratedDrafts/<meeting_id>_research.md`

실패 시 fallback:
- 기본 리서치 초안 문구 생성

운영 리스크:
- 비용이 큰 편
- 일반 미팅마다 돌릴 필요는 낮음

## 현재 LLM 미사용/부분사용 영역

다음은 아직 LLM보다 규칙/시스템 중심입니다.

- Google Calendar 생성
- Google Meet 링크 생성
- Trello 반영
- Drive 저장/읽기
- meeting state 관리
- transcript 파일 다운로드
- Slack 버튼 액션

즉 제품 전체가 LLM-only가 아니라
- 시스템 작업은 deterministic
- 텍스트 해석/생성만 LLM
구조입니다.

## 현재 fallback 철학

현재 구현은 “LLM이 실패해도 파이프라인이 완전히 멈추지 않게” 설계되어 있습니다.

대표 fallback:
- 자연어 intent 라우팅 실패
  - 규칙 기반 파서 또는 help/chat fallback
- 브리핑 생성 실패
  - 템플릿형 브리핑
- transcript 구조화 실패
  - section-based fallback
- AI review 실패
  - 기본 안내문
- proposal/research 실패
  - 기본 초안

이건 데모/초기 라이브에선 장점이 크지만,
운영 고도화 단계에서는 fallback 발생을 별도 로그/알림으로 추적하는 게 필요합니다.

## 비용 관점 정리

비용이 큰 순서로 보면 대체로 이렇습니다.

1. transcript 구조화
2. proposal 생성
3. research 생성
4. 브리핑 생성
5. AI review
6. intent router / DM fallback

즉 운영에서 비용 최적화를 하려면:
- transcript 구조화는 유지
- proposal/research는 조건부 유지
- intent router는 짧고 가볍게 유지
- 브리핑은 템플릿과 혼합
이 합리적입니다.

## 운영 관점에서 가장 중요한 전제

### 1. company_knowledge.md

위치:
- [company_knowledge.md](/Users/minhwankim/workspace/260325_Clade_Meetagain/company_knowledge.md)

이 파일은 사실상 다음 품질의 기반입니다.
- 브리핑
- AI review
- 제안서 초안

현재 이 파일이 비거나 없으면:
- 자사 관점 연결점이 약해짐
- 제안서/브리핑이 일반론적으로 흐름

즉 라이브 운영에서 가장 먼저 채워야 하는 지식 자산입니다.

### 2. transcript 품질

화자명이 실제 이름으로 되어 있지 않으면:
- 액션아이템 담당자
- 인물 업데이트
- Contacts 품질
이 떨어집니다.

가능하면 transcript 업로드 시:
- 미팅명
- 날짜
- 회사명
- 화자 매핑
을 함께 받는 것이 좋습니다.

## 현재 구조의 장단점

장점:
- 시스템 작업과 생성 작업이 분리되어 안정적
- LLM 실패 시도 fallback 경로가 많음
- 자연어 입력/브리핑/후속 정리에 모두 활용 가능

단점:
- 곳곳에 LLM이 흩어져 있어 비용 추적이 어렵다
- transcript 품질에 영향이 크다
- intent router와 규칙 기반 파서가 혼재되어 있어 해석 일관성이 완벽하진 않다

## 추천 운영 방향

### 지금 유지해도 좋은 사용처
- 브리핑 생성
- transcript 구조화
- AI review
- proposal/research 조건부 생성

### 추후 조정 권장
- DM 잡담 fallback
  - 비용 절감을 위해 더 단순화 가능
- intent router
  - 액션을 늘리기 전에 관측/로깅 보강 필요

### 가장 먼저 보강할 것
- `company_knowledge.md`
- transcript 업로드 시 미팅 매칭/확인 UX
- 화자 매핑 UX

## 한 줄 요약

현재 Meetagain에서 LLM은  
**자연어 해석 + 브리핑 생성 + transcript 구조화 + 검토의견 + 제안서/리서치 초안 생성**  
에 사용되고 있으며,
시스템 연동(Calendar/Drive/Trello/Slack 실행)은 규칙 기반/비LLM 방식으로 처리됩니다.
