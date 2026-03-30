"""
After Agent - 미팅 후 후속 처리 에이전트

역할: 미팅 후 처리 (FR-A01~A13)

주요 기능:
- FR-A01~A03: 회의록 파싱·완성 (2가지 버전)
- FR-A04: Slack Draft 생성 (확인 후 수동 발송)
- FR-A05~A06: Trello 체크리스트·카드 관리
- FR-A07~A08: 제안서·리서치 초안 생성 (Claude 기반)
- FR-A09~A13: 담당자 멘션·알림·리마인더

내부 미팅 패키지 구성:
1. 회의록 (클라이언트용 + 내부용)
2. 액션 아이템 목록
3. AI 검토의견 (맥락·배경 기반)
4. 의사결정사항

Trello 리스트:
- Leads / Contact/Meeting / Proposal / Negotiation (On MoU) / 수주 / Drop / 대기

사용법:
    agent = AfterAgent()
    await agent.process_meeting(meeting_id)
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any, List, Optional, Dict, Tuple
from anthropic import Anthropic

from src.models.contact import Company, Person
from src.models.meeting import Meeting
from src.models.action_item import ActionItem
from src.services.calendar_service import CalendarService
from src.services.drive_service import DriveService
from src.services.gmail_service import GmailService
from src.services.slack_service import SlackService
from src.services.trello_service import TrelloService
from src.utils.config import Config
from src.utils.logger import get_logger
from src.utils.helpers import extract_domain

logger = get_logger(__name__)


class AfterAgent:
    """미팅 후 후속 처리 에이전트"""
    
    # Trello 리스트 정의 (7개)
    TRELLO_LISTS = {
        "leads": "Leads",
        "contact": "Contact/Meeting",
        "proposal": "Proposal",
        "negotiation": "Negotiation (On MoU)",
        "closed": "수주",
        "drop": "Drop",
        "pending": "대기",
    }
    
    def __init__(self):
        """초기화"""
        self.calendar_svc = CalendarService()
        self.drive_svc = DriveService()
        self.gmail_svc = GmailService()
        self.slack_svc = SlackService()
        self.trello_svc = TrelloService()
        self.claude_client = Anthropic() if Config.ANTHROPIC_API_KEY else None
        logger.info("AfterAgent initialized (Phase 2 - Full Implementation)")
    
    async def process_meeting(self, meeting_id: str) -> bool:
        """
        미팅 후 완전한 후속 처리 (FR-A01~A13)
        
        워크플로우:
        1. 회의록 로드 및 파싱 (FR-A01)
        2. 클라이언트용·내부용 회의록 완성 (FR-A02~A03)
        3. 액션 아이템 + 결정사항 추출
        4. AI 검토의견 생성
        5. Slack Draft 생성 (FR-A04)
        6. Trello 업데이트 (FR-A05~A06)
        7. 초안 생성 (제안서·리서치) (FR-A07~A08)
        8. 담당자 알림 (FR-A09~A13)
        
        Args:
            meeting_id: Calendar 이벤트 ID
        
        Returns:
            성공 여부
        """
        try:
            logger.info(f"=== After Agent Started for Meeting: {meeting_id} ===")
            
            # Step 1: 회의록 로드
            meeting_notes = await self._load_meeting_notes(meeting_id)
            if not meeting_notes:
                logger.error(f"No meeting notes found for {meeting_id}")
                return False
            
            # Step 2~3: 회의록 파싱 및 완성
            parsed_data = await self._parse_meeting_notes(meeting_notes, meeting_id)
            parsed_data = self._enrich_parsed_data_with_state(meeting_id, parsed_data)
            
            # Step 4: AI 검토의견 생성
            ai_review = await self._generate_ai_review(meeting_id, parsed_data)
            
            # Step 5: Slack Draft 생성
            await self._create_slack_draft(meeting_id, parsed_data, ai_review)
            
            # Step 6: Trello 업데이트
            await self._update_trello(meeting_id, parsed_data)
            
            # Step 7: 초안 생성
            await self._create_drafts(meeting_id, parsed_data)
            
            # Step 8: 담당자 알림
            await self._notify_assignees(meeting_id, parsed_data)

            # Step 9: Contacts 업데이트/후속 미팅 초안 보관
            await self._prepare_follow_up_assets(meeting_id, parsed_data)

            final_state = self.drive_svc.load_meeting_state(meeting_id) or {}
            final_artifacts = final_state.get("artifacts", []) or []
            company_contact_paths = [
                item.get("path")
                for item in final_artifacts
                if item.get("type") == "company_contact" and item.get("path")
            ]
            person_contact_paths = [
                item.get("path")
                for item in final_artifacts
                if item.get("type") == "person_contact" and item.get("path")
            ]

            self.drive_svc.update_meeting_state(
                meeting_id,
                {
                    "meeting_id": meeting_id,
                    "phase": "after",
                    "after_completed": True,
                    "action_item_count": len(parsed_data.get("action_items", [])),
                    "decision_count": len(parsed_data.get("decisions", [])),
                    "has_follow_up_meeting": bool(
                        (parsed_data.get("follow_up_meeting") or {}).get("needed")
                    ),
                    "contact_update_count": len(parsed_data.get("contact_updates", [])),
                    "contact_document_count": len(company_contact_paths) + len(person_contact_paths),
                    "company_contact": company_contact_paths[0] if company_contact_paths else None,
                    "person_contact": person_contact_paths[0] if person_contact_paths else None,
                    "person_contacts": person_contact_paths,
                },
            )
            
            logger.info(f"=== After Agent Completed for Meeting: {meeting_id} ===")
            return True
        
        except Exception as e:
            logger.error(f"Error processing meeting: {e}")
            return False
    
    async def _load_meeting_notes(self, meeting_id: str) -> Optional[str]:
        """
        회의록 로드 (During Agent에서 생성된 파일)
        
        경로 가정: Drive/회의록/[날짜] 업체명_회의록.md
        
        Args:
            meeting_id: Calendar 이벤트 ID
        
        Returns:
            회의록 텍스트 또는 None
        """
        try:
            logger.info(f"Loading meeting notes for {meeting_id}")
            notes = self.drive_svc.load_meeting_notes(meeting_id, version="internal")
            if not notes:
                logger.warning(f"Meeting notes not found in Drive for {meeting_id}")
                return None

            return notes
        
        except Exception as e:
            logger.error(f"Error loading meeting notes: {e}")
            return None
    
    async def _parse_meeting_notes(self, notes: str, meeting_id: str) -> Dict:
        """
        회의록 파싱 (FR-A01)
        
        Claude를 사용하여:
        - 결정사항 추출
        - 액션 아이템 추출 (담당자, 기한, 설명)
        - 참석자 확인
        
        Args:
            notes: 회의록 텍스트
            meeting_id: Calendar 이벤트 ID
        
        Returns:
            파싱된 데이터 딕셔너리
        """
        try:
            logger.info(f"Parsing meeting notes for {meeting_id}")
            if Config.DRY_RUN:
                return self._build_dry_run_parsed_data(notes)
            
            prompt = f"""
다음 회의록을 분석하고 구조화해주세요:

회의록:
{notes}

다음 항목을 JSON 형식으로 추출해주세요:
1. 참석자 목록 (attendees: [])
2. 미팅 주제 (topic: string)
3. 배경 정보 (background: string)
4. 주요 논의사항 (discussion_points: [])
5. 결정사항 (decisions: [])
6. 액션 아이템 (action_items: [
     {{
       "title": "작업 제목",
       "assignee": "담당자명 또는 '미정'",
       "due_date": "2026-04-30 또는 '미정'",
       "description": "상세 설명"
     }}
   ])
7. 다음 단계 (next_steps: [])
8. Contacts 업데이트 후보 (contact_updates: [
     {{
       "name": "인물명",
       "company": "회사명 또는 미정",
       "role": "직책 또는 미정",
       "notes": "새로 알게 된 정보 요약"
     }}
   ])
9. 후속 미팅 제안 (follow_up_meeting: {{
     "needed": true,
     "title": "다음 미팅 제목",
     "suggested_date": "YYYY-MM-DD 또는 '미정'",
     "agenda": ["어젠다"],
     "notes": "제안 이유"
   }})

JSON만 반환해주세요.
"""
            
            response = self.claude_client.messages.create(
                model=Config.ANTHROPIC_MODEL,
                max_tokens=3000,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
            
            import json
            parsed_text = response.content[0].text
            
            # JSON 추출 (마크다운 코드블록 제거)
            if "```json" in parsed_text:
                parsed_text = parsed_text.split("```json")[1].split("```")[0]
            elif "```" in parsed_text:
                parsed_text = parsed_text.split("```")[1].split("```")[0]
            
            data = json.loads(parsed_text)
            logger.info(f"Parsed data: {len(data.get('action_items', []))} action items found")
            
            return data
        
        except Exception as e:
            logger.error(f"Error parsing meeting notes: {e}")
            return self._build_structured_fallback_parsed_data(notes)
    
    async def _generate_ai_review(self, meeting_id: str, parsed_data: Dict) -> str:
        """
        AI 검토의견 생성 (FR-A13 확장)
        
        맥락 정보:
        - 기존 업체 미팅 히스토리
        - 파라메타 서비스 정보
        - 현재 미팅 결과
        
        생성 내용:
        - 전략적 어드바이스
        - 리스크 플래그
        - 다음 단계 추천
        
        Args:
            meeting_id: Calendar 이벤트 ID
            parsed_data: 파싱된 회의록
        
        Returns:
            AI 검토의견 텍스트
        """
        try:
            logger.info(f"Generating AI review for {meeting_id}")
            if Config.DRY_RUN:
                return "DRY RUN 검토의견: 다음 단계와 리스크를 확인하세요."
            
            # company_knowledge 로드 (파라메타 정보)
            company_knowledge = self.drive_svc.load_company_knowledge() or ""
            
            # 업체 정보 조회 (첫 참석자 기준)
            attendees = parsed_data.get("attendees", [])
            company_name = self._infer_company_name(parsed_data)
            
            company_info = self.drive_svc.load_company_contact(company_name) or {}
            
            # Gmail에서 최근 이메일 조회 (커뮤니케이션 히스토리)
            recent_emails = []
            attendee_email = self._extract_attendee_email(attendees)
            if attendee_email:
                recent_emails = self.gmail_svc.get_recent_emails(attendee_email, days=180, limit=5)
            
            prompt = f"""
다음 정보를 종합하여 전략적 검토의견을 작성해주세요:

**파라메타 정보:**
{company_knowledge}

**업체 정보:**
{company_info}

**현재 미팅 결과:**
- 주제: {parsed_data.get('topic', 'N/A')}
- 배경: {parsed_data.get('background', 'N/A')}
- 결정사항: {', '.join(parsed_data.get('decisions', []))}
- 액션아이템: {len(parsed_data.get('action_items', []))}개

**검토의견 작성 내용:**
1. 미팅 결과 평가 (긍정적/부정적 신호)
2. 파라메타 관점에서의 전략적 기회
3. 예상 리스크 또는 주의사항
4. 다음 단계 추천 (구체적)
5. 담당자를 위한 팁

한국어로 작성해주세요. 전문적이면서도 실용적인 톤으로.
"""
            
            response = self.claude_client.messages.create(
                model=Config.ANTHROPIC_MODEL,
                max_tokens=2000,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
            
            review = response.content[0].text
            logger.info("AI review generated successfully")
            return review
        
        except Exception as e:
            logger.error(f"Error generating AI review: {e}")
            return "검토의견 생성 실패로 기본 후속 정리만 제공됩니다."
    
    async def _create_slack_draft(self, meeting_id: str, parsed_data: Dict, ai_review: str) -> bool:
        """
        Slack Draft 생성 (FR-A04)
        
        내용:
        - 결정사항 요약
        - 액션 아이템 목록
        - AI 검토의견
        
        Args:
            meeting_id: Calendar 이벤트 ID
            parsed_data: 파싱된 데이터
            ai_review: AI 검토의견
        
        Returns:
            성공 여부
        """
        try:
            logger.info(f"Creating Slack draft for {meeting_id}")
            
            # Draft 내용 구성
            draft_text = f"""
**📋 미팅 후속 사항**

**결정사항:**
"""
            
            for decision in parsed_data.get("decisions", []):
                draft_text += f"\n✓ {decision}"
            
            draft_text += "\n\n**액션 아이템:**\n"
            
            for idx, item in enumerate(parsed_data.get("action_items", []), 1):
                assignee = self._build_assignee_reference(item)
                due_date = item.get("due_date", "미정")
                draft_text += f"\n{idx}. [{assignee}] {item.get('title', '')}\n   기한: {due_date}"
            
            draft_text += f"\n\n**📊 AI 검토의견:**\n{ai_review}"
            
            # Draft 생성 (자동 발송 아님)
            draft = self.slack_svc.create_draft(
                channel="meetagain",  # 실제 채널명은 config에서
                text=draft_text,
            )

            if draft:
                self.drive_svc.save_generated_draft(meeting_id, "slack_summary", draft_text)
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "slack_summary",
                    f"{Config.GENERATED_DRAFTS_FOLDER}/{meeting_id}_slack_summary.md",
                )
            
            logger.info("Slack draft created successfully")
            return True
        
        except Exception as e:
            logger.error(f"Error creating Slack draft: {e}")
            return False
    
    async def _update_trello(self, meeting_id: str, parsed_data: Dict) -> bool:
        """
        Trello 업데이트 (FR-A05~A06)
        
        1. 업체 카드 찾기 또는 생성
        2. 액션 아이템을 체크리스트로 추가
        
        Args:
            meeting_id: Calendar 이벤트 ID
            parsed_data: 파싱된 데이터
        
        Returns:
            성공 여부
        """
        try:
            logger.info(f"Updating Trello for {meeting_id}")
            
            # 업체명 추출
            company_name = self._infer_company_name(parsed_data)
            
            # FR-A05: 기존 카드 찾기
            card = self.trello_svc.find_company_card(company_name)
            
            # FR-A06: 카드 없으면 생성
            if not card:
                card = self.trello_svc.create_company_card(
                    company_name,
                    list_name=self.TRELLO_LISTS["contact"],
                )
            
            if not card:
                logger.error(f"Failed to find/create card for {company_name}")
                return False
            
            # 액션 아이템을 체크리스트에 추가
            for item in parsed_data.get("action_items", []):
                assignee = item.get("assignee", "미정")
                due_date = item.get("due_date", "미정")
                
                # 체크리스트 항목: [담당자] 제목 (기한: 날짜)
                checklist_title = f"[{assignee}] {item.get('title')} (기한: {due_date})"
                
                self.trello_svc.add_checklist_item(
                    card,
                    checklist_title,
                    description=item.get("description", ""),
                )
            
            logger.info(f"Trello updated for {company_name}")
            return True
        
        except Exception as e:
            logger.error(f"Error updating Trello: {e}")
            return False
    
    async def _create_drafts(self, meeting_id: str, parsed_data: Dict) -> bool:
        """
        제안서·리서치 초안 생성 (FR-A07~A08)
        
        액션아이템에 다음이 포함된 경우:
        - "제안서" → 제안서 초안 생성
        - "리서치" → 리서치 초안 생성
        
        Args:
            meeting_id: Calendar 이벤트 ID
            parsed_data: 파싱된 데이터
        
        Returns:
            성공 여부
        """
        try:
            logger.info(f"Creating drafts for {meeting_id}")
            proposal_created = False
            research_created = False

            if self._needs_proposal_draft(parsed_data):
                proposal_created = await self._create_proposal_draft(meeting_id, parsed_data)

            if self._needs_research_draft(parsed_data):
                research_created = await self._create_research_draft(meeting_id, parsed_data)

            self.drive_svc.update_meeting_state(
                meeting_id,
                {
                    "meeting_id": meeting_id,
                    "proposal_draft_created": proposal_created,
                    "research_draft_created": research_created,
                },
            )
            
            logger.info("Drafts created successfully")
            return True
        
        except Exception as e:
            logger.error(f"Error creating drafts: {e}")
            return False
    
    async def _create_proposal_draft(self, meeting_id: str, parsed_data: Dict) -> bool:
        """제안서 초안 생성 (기존 커뮤니케이션 + 파라메타 정보 기반)"""
        try:
            logger.info("Creating proposal draft")
            if Config.DRY_RUN:
                proposal_text = "# DRY RUN 제안서 초안\n\n- 미팅 배경 기반 초안"
                saved = self.drive_svc.save_generated_draft(meeting_id, "proposal", proposal_text)
                if saved:
                    logger.info("Proposal draft created and saved")
                    self.drive_svc.append_meeting_artifact(
                        meeting_id,
                        "proposal",
                        f"{Config.GENERATED_DRAFTS_FOLDER}/{meeting_id}_proposal.md",
                    )
                return saved
            
            company_knowledge = self.drive_svc.load_company_knowledge() or ""
            attendees = parsed_data.get("attendees", [])
            
            # 최근 이메일 히스토리 로드
            recent_context = ""
            attendee_email = self._extract_attendee_email(attendees)
            if attendee_email:
                emails = self.gmail_svc.get_recent_emails(attendee_email, days=180, limit=5)
                recent_context = f"최근 {len(emails)}개의 통신 기록이 있습니다."
            
            prompt = f"""
다음 정보를 기반으로 전문적인 제안서 초안을 작성해주세요.
기존 업체와의 커뮤니케이션 맥락 및 파라메타 정보를 반영하세요:

**파라메타 정보:**
{company_knowledge}

**기존 커뮤니케이션:**
{recent_context}

**미팅 배경:**
{parsed_data.get('background', '')}

**결정사항:**
{', '.join(parsed_data.get('decisions', []))}

**제안서 구성:**
1. 소개 (파라메타 소개 및 미팅 배경)
2. 현황 분석 (업체의 상황 및 문제점)
3. 솔루션 제안 (파라메타 서비스 포지셔닝)
4. 구현 계획 (일정 및 절차)
5. 예상 효과 (ROI 및 기대효과)
6. 투자 및 조건

마크다운 형식으로 작성해주세요.
"""
            
            response = self.claude_client.messages.create(
                model=Config.ANTHROPIC_MODEL,
                max_tokens=3000,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
            
            proposal_text = response.content[0].text
            
            saved = self.drive_svc.save_generated_draft(meeting_id, "proposal", proposal_text)
            if saved:
                logger.info("Proposal draft created and saved")
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "proposal",
                    f"{Config.GENERATED_DRAFTS_FOLDER}/{meeting_id}_proposal.md",
                )
            return saved
        
        except Exception as e:
            logger.error(f"Error creating proposal: {e}")
            proposal_text = "# 제안서 초안\n\n- 모델 호출 실패로 기본 초안을 생성했습니다.\n- 회의 배경과 결정사항을 기반으로 세부 내용을 보강해 주세요."
            saved = self.drive_svc.save_generated_draft(meeting_id, "proposal", proposal_text)
            if saved:
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "proposal",
                    f"{Config.GENERATED_DRAFTS_FOLDER}/{meeting_id}_proposal.md",
                )
            return saved
    
    async def _create_research_draft(self, meeting_id: str, parsed_data: Dict) -> bool:
        """리서치 초안 생성 (미팅 배경 + 파라메타 관점)"""
        try:
            logger.info("Creating research draft")
            if Config.DRY_RUN:
                research_text = "# DRY RUN 리서치 초안\n\n- 미팅 논의사항 기반 초안"
                saved = self.drive_svc.save_generated_draft(meeting_id, "research", research_text)
                if saved:
                    logger.info("Research draft created and saved")
                    self.drive_svc.append_meeting_artifact(
                        meeting_id,
                        "research",
                        f"{Config.GENERATED_DRAFTS_FOLDER}/{meeting_id}_research.md",
                    )
                return saved
            
            company_knowledge = self.drive_svc.load_company_knowledge() or ""
            
            prompt = f"""
다음 정보를 기반으로 리서치 초안을 작성해주세요:

**파라메타 정보:**
{company_knowledge}

**미팅 내용:**
- 주제: {parsed_data.get('topic', 'N/A')}
- 배경: {parsed_data.get('background', 'N/A')}
- 논의사항: {', '.join(parsed_data.get('discussion_points', []))}

**리서치 초안 구성:**
1. 대상 시장 분석
2. 경쟁사 분석
3. 기술 트렌드
4. 규제 환경
5. 기회 요인 (파라메타 관점)
6. 리스크 요인
7. 파라메타 제안 (전략적 기회)

마크다운 형식으로 작성해주세요.
"""
            
            response = self.claude_client.messages.create(
                model=Config.ANTHROPIC_MODEL,
                max_tokens=3000,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
            
            research_text = response.content[0].text
            
            saved = self.drive_svc.save_generated_draft(meeting_id, "research", research_text)
            if saved:
                logger.info("Research draft created and saved")
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "research",
                    f"{Config.GENERATED_DRAFTS_FOLDER}/{meeting_id}_research.md",
                )
            return saved
        
        except Exception as e:
            logger.error(f"Error creating research: {e}")
            research_text = "# 리서치 초안\n\n- 모델 호출 실패로 기본 초안을 생성했습니다.\n- 시장/경쟁사/규제 항목을 발표 전 보강해 주세요."
            saved = self.drive_svc.save_generated_draft(meeting_id, "research", research_text)
            if saved:
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "research",
                    f"{Config.GENERATED_DRAFTS_FOLDER}/{meeting_id}_research.md",
                )
            return saved
    
    async def _notify_assignees(self, meeting_id: str, parsed_data: Dict) -> bool:
        """
        담당자 알림 (FR-A09~A13)
        
        - 담당자 Slack DM 발송 (FR-A11)
        - 채널 공지 (FR-A09)
        - 기한 리마인더 설정 (FR-A12)
        - 담당자 Contacts 업데이트 (FR-A10)
        
        Args:
            meeting_id: Calendar 이벤트 ID
            parsed_data: 파싱된 데이터
        
        Returns:
            성공 여부
        """
        try:
            logger.info(f"Notifying assignees for {meeting_id}")
            
            action_items = parsed_data.get("action_items", [])
            dm_count = 0
            reminder_count = 0
            
            for item in action_items:
                assignee_name = item.get("assignee", "")
                
                if assignee_name == "미정":
                    continue
                
                # DM 발송 (FR-A11)
                dm_text = f"""
안녕하세요! 미팅 후속 액션이 있습니다.

**작업:** {item.get('title')}
**기한:** {item.get('due_date', '미정')}
**설명:** {item.get('description', 'N/A')}

Trello에서도 확인할 수 있습니다.
"""
                
                # 담당자 이메일로 Slack DM 발송
                assignee_email = item.get("assignee_email") or f"{assignee_name}@parametacorp.com"
                self.slack_svc.send_dm(assignee_email, dm_text)
                dm_count += 1
                
                # 기한 리마인더 설정 (FR-A12)
                due_date_str = item.get("due_date", "")
                if due_date_str != "미정":
                    if await self._schedule_reminder(meeting_id, assignee_email, item):
                        reminder_count += 1

            self.drive_svc.update_meeting_state(
                meeting_id,
                {
                    "meeting_id": meeting_id,
                    "assignee_dm_count": dm_count,
                    "reminder_count": reminder_count,
                },
            )
            
            logger.info(f"Assignees notified for {meeting_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error notifying assignees: {e}")
            return False

    def _extract_attendee_email(self, attendees: List[Any]) -> Optional[str]:
        """참석자 목록에서 Gmail 조회에 사용할 이메일을 안전하게 추출한다."""
        for attendee in attendees:
            if isinstance(attendee, str):
                candidate = attendee.strip()
                if "@" in candidate:
                    return candidate
                continue

            if isinstance(attendee, dict):
                for key in ("email", "organizer_email"):
                    value = attendee.get(key)
                    if isinstance(value, str) and "@" in value:
                        return value.strip()

        return None
    
    async def _schedule_reminder(self, meeting_id: str, email: str, item: Dict) -> bool:
        """
        기한 리마인더 설정 (FR-A12)
        
        기한 전날 오전 9시에 reminder 발송
        
        Args:
            email: 담당자 이메일
            item: 액션 아이템
        
        Returns:
            성공 여부
        """
        try:
            due_date_str = item.get("due_date", "")
            
            # 기한 파싱
            from datetime import datetime
            try:
                due_date = datetime.fromisoformat(due_date_str)
                reminder_date = due_date - timedelta(days=1)
                reminder_date = reminder_date.replace(hour=9, minute=0)
                
                logger.info(f"Reminder scheduled for {email} at {reminder_date}")
                reminder_text = (
                    "# 액션 아이템 리마인더 초안\n\n"
                    f"- 수신자: {email}\n"
                    f"- 리마인더 시각: {reminder_date.isoformat()}\n"
                    f"- 작업: {item.get('title', '미정')}\n"
                    f"- 기한: {due_date_str}\n"
                    f"- 설명: {item.get('description', '')}\n"
                )
                draft_key = f"reminder_{email.split('@', 1)[0]}_{item.get('title', 'task')}"
                self.drive_svc.save_generated_draft("reminders", draft_key, reminder_text)
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "reminder",
                    f"{Config.GENERATED_DRAFTS_FOLDER}/reminders_{draft_key}.md",
                )
            
            except ValueError:
                logger.debug(f"Invalid due date format: {due_date_str}")
            
            return True
        
        except Exception as e:
            logger.error(f"Error scheduling reminder: {e}")
            return False

    async def _prepare_follow_up_assets(self, meeting_id: str, parsed_data: Dict) -> bool:
        """
        Contacts 업데이트 제안과 후속 미팅 초안을 저장
        """
        try:
            contact_updates = parsed_data.get("contact_updates", [])
            follow_up_meeting = parsed_data.get("follow_up_meeting") or {}
            follow_up_needed = bool(follow_up_meeting.get("needed"))
            follow_up_draft_created = False
            follow_up_calendar_created = False
            persisted_contact_artifacts = []

            if contact_updates:
                lines = ["# Contacts 업데이트 제안", ""]
                for item in contact_updates:
                    lines.append(f"- 이름: {item.get('name', '미정')}")
                    lines.append(f"  회사: {item.get('company', '미정')}")
                    lines.append(f"  직책: {item.get('role', '미정')}")
                    lines.append(f"  메모: {item.get('notes', '')}")
                    lines.append("")

                self.drive_svc.save_generated_draft(
                    meeting_id,
                    "contact_updates",
                    "\n".join(lines).strip(),
                )
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "contact_updates",
                    f"{Config.GENERATED_DRAFTS_FOLDER}/{meeting_id}_contact_updates.md",
                )
                persisted_contact_artifacts = self._persist_contact_documents(meeting_id, parsed_data)

            if follow_up_needed:
                agenda = follow_up_meeting.get("agenda", [])
                lines = [
                    "# 후속 미팅 제안 초안",
                    "",
                    f"제목: {follow_up_meeting.get('title', '미정')}",
                    f"추천 일정: {follow_up_meeting.get('suggested_date', '미정')}",
                    f"제안 이유: {follow_up_meeting.get('notes', '')}",
                    "",
                    "## 어젠다",
                ]
                if agenda:
                    lines.extend([f"- {agenda_item}" for agenda_item in agenda])
                else:
                    lines.append("- 미정")

                self.drive_svc.save_generated_draft(
                    meeting_id,
                    "follow_up_meeting",
                    "\n".join(lines),
                )
                follow_up_draft_created = True
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "follow_up_meeting",
                    f"{Config.GENERATED_DRAFTS_FOLDER}/{meeting_id}_follow_up_meeting.md",
                )

                attendees = parsed_data.get("attendees", [])
                external_attendees = [
                    attendee
                    for attendee in attendees
                    if extract_domain(attendee) not in Config.INTERNAL_DOMAINS
                ]
                follow_up_calendar_created = self.calendar_svc.create_draft_meeting(
                    title=follow_up_meeting.get("title", "후속 미팅"),
                    suggested_date=follow_up_meeting.get("suggested_date", "미정"),
                    attendees=external_attendees,
                    agenda=agenda,
                    notes=follow_up_meeting.get("notes", ""),
                )

            load_meeting_state = getattr(self.drive_svc, "load_meeting_state", None)
            current_state = load_meeting_state(meeting_id) if callable(load_meeting_state) else {}
            all_artifacts = current_state.get("artifacts", []) or []
            company_contact_paths = [
                item.get("path")
                for item in all_artifacts
                if item.get("type") == "company_contact" and item.get("path")
            ]
            person_contact_paths = [
                item.get("path")
                for item in all_artifacts
                if item.get("type") == "person_contact" and item.get("path")
            ]

            self.drive_svc.update_meeting_state(
                meeting_id,
                {
                    "meeting_id": meeting_id,
                    "contact_update_count": len(contact_updates),
                    "contact_document_count": len(company_contact_paths) + len(person_contact_paths),
                    "company_contact": company_contact_paths[0] if company_contact_paths else None,
                    "person_contact": person_contact_paths[0] if person_contact_paths else None,
                    "person_contacts": person_contact_paths,
                    "follow_up_needed": follow_up_needed,
                    "follow_up_draft_created": follow_up_draft_created,
                    "follow_up_calendar_created": follow_up_calendar_created,
                },
            )

            return True

        except Exception as e:
            logger.error(f"Error preparing follow-up assets: {e}")
            return False

    def _persist_contact_documents(self, meeting_id: str, parsed_data: Dict) -> List[Dict]:
        persisted = []
        company_name = self._infer_company_name(parsed_data)
        attendees = self._normalize_attendee_emails(parsed_data.get("attendees", []) or [])
        note_context = self._collect_contact_note_context(parsed_data)

        if company_name and company_name != "Unknown":
            company = self.drive_svc.load_company_contact(company_name) or Company(name=company_name)
            company.description = company.description or parsed_data.get("background", "")
            company.key_contact = (parsed_data.get("contact_updates") or [{}])[0].get("name") or company.key_contact
            company.meeting_history_count = max(company.meeting_history_count, 0) + 1
            company.last_meeting_date = datetime.now()
            company.main_email = company.main_email or next(
                (email for email in attendees if extract_domain(email) not in Config.INTERNAL_DOMAINS),
                None,
            )

            touchpoints = list(company.service_touchpoints or [])
            for line in parsed_data.get("decisions", []) + parsed_data.get("discussion_points", []) + parsed_data.get("next_steps", []):
                normalized = (line or "").strip()
                if normalized and normalized not in touchpoints:
                    touchpoints.append(normalized)
            company.service_touchpoints = touchpoints[:10]

            if self.drive_svc.save_contact("company", company.name, company.to_dict()):
                path = f"{Config.CONTACTS_FOLDER}/Companies/{company.name}.md"
                self.drive_svc.append_meeting_artifact(meeting_id, "company_contact", path)
                persisted.append({"type": "company_contact", "path": path})

        for item in parsed_data.get("contact_updates", []):
            person_name = (item.get("name") or "").strip()
            if not person_name or person_name == "미정":
                continue

            person = self.drive_svc.load_person_contact(person_name) or Person(name=person_name)
            person.company = item.get("company") or person.company or company_name
            person.title = item.get("role") or person.title
            person.notes = self._merge_contact_notes(person.notes, item.get("notes", ""), note_context)
            person.meeting_history_count = max(person.meeting_history_count, 0) + 1
            person.last_meeting_date = datetime.now()

            matched_email = next(
                (
                    email
                    for email in attendees
                    if person_name.replace(" ", "").lower() in email.split("@", 1)[0].replace(".", "").replace("_", "").lower()
                ),
                None,
            )
            if matched_email:
                person.email = person.email or matched_email

            if self.drive_svc.save_contact("person", person.name, person.to_dict()):
                path = f"{Config.CONTACTS_FOLDER}/People/{person.name}.md"
                self.drive_svc.append_meeting_artifact(meeting_id, "person_contact", path)
                persisted.append({"type": "person_contact", "path": path})

        return persisted

    def _collect_contact_note_context(self, parsed_data: Dict) -> str:
        chunks = []
        for key in ("decisions", "discussion_points", "next_steps"):
            chunks.extend(parsed_data.get(key, []))
        return "\n".join(chunk for chunk in chunks if chunk)

    def _merge_contact_notes(self, *parts: str) -> str:
        seen = set()
        lines = []
        for part in parts:
            if not part:
                continue
            for line in str(part).splitlines():
                normalized = line.strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                lines.append(normalized)
        return "\n".join(lines[:12])

    def _build_assignee_reference(self, item: Dict) -> str:
        assignee_name = item.get("assignee", "미정")
        assignee_email = item.get("assignee_email")

        if assignee_name == "미정":
            return assignee_name

        if not assignee_email:
            assignee_email = f"{assignee_name}@parametacorp.com"

        user_id = self.slack_svc.get_user_id(assignee_email)
        if user_id:
            return f"<@{user_id}>"

        return assignee_name

    def _needs_proposal_draft(self, parsed_data: Dict) -> bool:
        searchable_text = self._collect_draft_signal_text(parsed_data)
        proposal_keywords = ["제안서", "proposal", "견적", "제안", "제안안", "poc 제안"]
        return any(keyword in searchable_text for keyword in proposal_keywords)

    def _needs_research_draft(self, parsed_data: Dict) -> bool:
        searchable_text = self._collect_draft_signal_text(parsed_data)
        research_keywords = ["리서치", "research", "조사", "시장 분석", "경쟁사 분석", "벤치마크"]
        return any(keyword in searchable_text for keyword in research_keywords)

    def _collect_draft_signal_text(self, parsed_data: Dict) -> str:
        chunks = []

        for item in parsed_data.get("action_items", []):
            chunks.append(item.get("title", ""))
            chunks.append(item.get("description", ""))

        for key in ("decisions", "next_steps", "discussion_points"):
            chunks.extend(parsed_data.get(key, []))

        chunks.append(parsed_data.get("background", ""))
        chunks.append(parsed_data.get("topic", ""))

        return " ".join(chunk.lower() for chunk in chunks if chunk)

    def _infer_company_name(self, parsed_data: Dict) -> str:
        """
        파싱 결과에서 업체명 추론
        """
        meeting_title = (parsed_data.get("meeting_title") or "").strip()
        if meeting_title:
            title_company = self._extract_company_from_title(meeting_title)
            if title_company:
                return title_company

        topic = (parsed_data.get("topic") or "").strip()
        if topic:
            topic_company = self._extract_company_from_title(topic)
            if topic_company:
                return topic_company
            return topic.split()[0]

        attendees = self._normalize_attendee_emails(parsed_data.get("attendees", []) or [])
        for attendee in attendees:
            domain = extract_domain(attendee)
            if domain and domain not in Config.INTERNAL_DOMAINS:
                return domain.split(".")[0]

        return "Unknown"

    def _extract_company_from_title(self, title: str) -> str:
        normalized = (title or "").strip()
        if not normalized:
            return ""
        normalized = normalized.replace("브리핑", "").strip()
        for delimiter in (" 미팅", " 회의", " 일정", "/"):
            if delimiter in normalized:
                candidate = normalized.split(delimiter, 1)[0].strip()
                if candidate:
                    return candidate
        parts = normalized.split()
        return parts[0] if parts else ""

    def _enrich_parsed_data_with_state(self, meeting_id: str, parsed_data: Dict) -> Dict:
        current_state = self.drive_svc.load_meeting_state(meeting_id) or {}
        meeting_title = (current_state.get("title") or "").strip()
        if meeting_title:
            parsed_data.setdefault("meeting_title", meeting_title)
            parsed_data["topic"] = parsed_data.get("topic") or meeting_title

        attendees = current_state.get("attendees") or []
        if attendees and not parsed_data.get("attendees"):
            parsed_data["attendees"] = attendees

        company_name = self._infer_company_name(parsed_data)
        normalized_contact_updates = []
        for item in parsed_data.get("contact_updates", []):
            person = dict(item or {})
            if not person.get("company") or person.get("company") == "미정":
                person["company"] = company_name
            name = (person.get("name") or "").strip()
            if name.startswith("화자"):
                person["name"] = f"{company_name} 담당자"
                person["notes"] = person.get("notes") or f"{company_name} 측 참석자. 역할 추가 확인 필요"
            normalized_contact_updates.append(person)
        parsed_data["contact_updates"] = normalized_contact_updates

        normalized_actions = []
        for item in parsed_data.get("action_items", []):
            action_item = dict(item or {})
            assignee = (action_item.get("assignee") or "").strip()
            if assignee.startswith("화자"):
                action_item["assignee"] = f"{company_name} 담당자"
            normalized_actions.append(action_item)
        parsed_data["action_items"] = normalized_actions

        return parsed_data

    def _normalize_attendee_emails(self, attendees: List) -> List[str]:
        normalized = []
        for attendee in attendees or []:
            if isinstance(attendee, str):
                value = attendee.strip()
                if value:
                    normalized.append(value)
                continue

            if isinstance(attendee, dict):
                for key in ("email", "mail", "address"):
                    value = attendee.get(key)
                    if isinstance(value, str) and value.strip():
                        normalized.append(value.strip())
                        break

        return normalized

    def _build_dry_run_parsed_data(self, notes: str) -> Dict:
        snippet = notes.strip().splitlines()
        summary = snippet[0] if snippet else "DRY RUN 회의록"
        normalized_notes = notes.lower()
        decisions = ["1단계 파일럿: 카카오 사내 임직원 인증 모듈 (500명)"]
        next_steps = ["다음 미팅 일정 조율"]
        action_items = [
            {
                "title": "기술 연동 문서 발송",
                "assignee": "류혁곤",
                "due_date": "2026-03-30",
                "description": "카카오 기술 검토를 위한 연동 문서 공유",
                "assignee_email": "ryu.hyeokgon@parametacorp.com",
            },
            {
                "title": "내부 기술팀 검토 요청",
                "assignee": "김민환",
                "due_date": "2026-03-30",
                "description": "카카오 내부 기술팀 검토 요청",
                "assignee_email": "minwhan@kakao.com",
            }
        ]

        if "제안서" in normalized_notes or "proposal" in normalized_notes:
            decisions.append("제안서 초안 준비")
            next_steps.append("고객사 제안서 방향 정리")
            action_items.append(
                {
                    "title": "제안서 초안 작성",
                    "assignee": "홍길동",
                    "due_date": "2026-04-01",
                    "description": "미팅 내용을 반영한 DRY RUN 제안서 초안 작성",
                }
            )

        if any(keyword in normalized_notes for keyword in ["리서치", "research", "조사", "시장 분석"]):
            decisions.append("리서치 자료 정리")
            next_steps.append("시장 분석 리서치 진행")
            action_items.append(
                {
                    "title": "시장 분석 리서치",
                    "assignee": "홍길동",
                    "due_date": "2026-04-02",
                    "description": "관련 시장과 경쟁사 DRY RUN 조사",
                }
            )

        return {
            "attendees": ["ryu.hyeokgon@parametacorp.com", "minwhan@kakao.com"],
            "topic": "카카오 DID 솔루션 도입 논의",
            "background": summary,
            "discussion_points": [
                "카카오 인증 시스템 현황 공유",
                "파라메타 DID 솔루션 파일럿 범위 협의",
            ],
            "decisions": decisions,
            "action_items": action_items,
            "next_steps": next_steps,
            "contact_updates": [
                {
                    "name": "김민환",
                    "company": "kakao",
                    "role": "사업개발팀 팀장",
                    "notes": "숫자 근거와 레퍼런스 케이스를 중시",
                }
            ],
            "follow_up_meeting": {
                "needed": True,
                "title": "카카오 후속 미팅",
                "suggested_date": "2026-04-10",
                "agenda": ["파일럿 도입 범위 검토", "기술 연동 일정 확정"],
                "notes": "파일럿 범위 및 기술 검토 일정 논의",
            },
        }

    def _build_structured_fallback_parsed_data(self, notes: str) -> Dict:
        attendees_line = self._extract_single_line_section(notes, "참석:")
        attendees = self._parse_attendee_line(attendees_line)
        topic = self._extract_title_from_notes(notes)
        discussion_points = self._extract_section_items(notes, "## 주요 논의사항")
        decisions = self._extract_section_items(notes, "## 주요 결론")
        next_steps = self._extract_section_items(notes, "## 다음 단계")
        todo_lines = self._extract_section_items(notes, "## To Do")
        action_items = [item for item in (self._parse_action_item_line(line) for line in todo_lines) if item]
        contact_updates = self._extract_contact_updates_from_notes(notes, attendees)
        follow_up_needed = bool(next_steps or action_items)
        follow_up_title = f"{topic.split()[0] if topic else '후속'} 후속 미팅"

        return {
            "attendees": attendees,
            "topic": topic or "미팅 후속 논의",
            "background": notes.strip().splitlines()[0] if notes.strip() else "회의록",
            "discussion_points": discussion_points,
            "decisions": decisions,
            "action_items": action_items,
            "next_steps": next_steps,
            "contact_updates": contact_updates,
            "follow_up_meeting": {
                "needed": follow_up_needed,
                "title": follow_up_title,
                "suggested_date": "미정",
                "agenda": next_steps[:3] or [item.get("title", "후속 논의") for item in action_items[:3]],
                "notes": next_steps[0] if next_steps else "후속 액션 논의 필요",
            },
        }

    def _extract_single_line_section(self, text: str, prefix: str) -> str:
        for line in text.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()[len(prefix):].strip()
        return ""

    def _extract_title_from_notes(self, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip().replace("[클라이언트용]", "").replace("[내부용]", "").strip()
        return "미팅"

    def _extract_section_items(self, text: str, header: str) -> List[str]:
        if not text or header not in text:
            return []
        section = text.split(header, 1)[1]
        next_header = section.find("\n## ")
        if next_header != -1:
            section = section[:next_header]
        items = []
        for line in section.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                items.append(stripped[2:].strip())
        return items

    def _parse_attendee_line(self, line: str) -> List[str]:
        attendees = []
        for chunk in [part.strip() for part in line.split(",") if part.strip()]:
            email = None
            if "(" in chunk and ")" in chunk:
                paren = chunk.split("(", 1)[1].split(")", 1)[0]
                if "@" in paren:
                    email = paren
            if not email and "@" in chunk:
                email = chunk
            if email:
                attendees.append(email)
        return attendees

    def _parse_action_item_line(self, line: str) -> Optional[Dict]:
        text = (line or "").strip()
        if not text:
            return None

        assignee = "미정"
        title = text
        due_date = "미정"

        if text.startswith("[") and "]" in text:
            assignee, remainder = text[1:].split("]", 1)
            title = remainder.strip()

        if " / 기한: " in title:
            title, due_date = title.split(" / 기한: ", 1)
            title = title.strip()
            due_date = due_date.strip()

        return {
            "title": title,
            "assignee": assignee.strip(),
            "due_date": due_date,
            "description": title,
        }

    def _extract_contact_updates_from_notes(self, notes: str, attendees: List[str]) -> List[Dict]:
        people = []
        internal_memos = self._extract_section_items(notes, "## 내부 메모")
        inferred_company = self._infer_company_name({"topic": self._extract_title_from_notes(notes), "attendees": attendees})

        attendee_line = self._extract_single_line_section(notes, "참석:")
        people.extend(self._extract_people_from_attendee_line(attendee_line, inferred_company))

        for memo in internal_memos:
            parsed = self._parse_contact_update_from_memo(memo, inferred_company)
            if parsed:
                people.append(parsed)

        deduped = []
        seen = set()
        for person in people:
            key = (person.get("name"), person.get("company"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(person)
        return deduped

    def _extract_people_from_attendee_line(self, line: str, fallback_company: str) -> List[Dict]:
        people = []
        for chunk in [part.strip() for part in line.split(",") if part.strip()]:
            chunk = re.sub(r"\s+", " ", chunk)
            if not chunk:
                continue

            if "(" in chunk and ")" in chunk:
                name, paren = chunk.split("(", 1)
                company = paren.split(")", 1)[0].strip() or fallback_company
                name = name.strip()
            else:
                name = chunk
                company = fallback_company

            if not name:
                continue

            people.append(
                {
                    "name": name,
                    "company": company,
                    "role": "",
                    "notes": "",
                }
            )
        return people

    def _parse_contact_update_from_memo(self, memo: str, fallback_company: str) -> Optional[Dict]:
        text = (memo or "").strip()
        if not text:
            return None

        tagged = re.match(r"^\[(?P<tag>[^\]]+)\]\s*(?P<body>.+)$", text)
        body = tagged.group("body").strip() if tagged else text
        tag = tagged.group("tag").strip() if tagged else ""

        if tag and tag not in {"담당자", "인물", "회사"}:
            return None

        name_match = re.match(r"^(?P<name>[A-Za-z가-힣·\s]+?)(?:은|는|이|가)\s+(?P<rest>.+)$", body)
        if not name_match:
            return None

        name = name_match.group("name").strip()
        rest = name_match.group("rest").strip()
        if not name:
            return None

        role = ""
        role_match = re.search(r"([가-힣A-Za-z0-9/·\-\s]+?(팀장|리드|매니저|이사|대표|담당자|PM|PO|Head|Manager))", rest)
        if role_match:
            role = role_match.group(1).strip()

        company = fallback_company
        company_match = re.search(r"([가-힣A-Za-z0-9]+)\s+(사업개발팀|기술팀|파트너십팀|팀)", rest)
        if company_match:
            company = company_match.group(1).strip()

        return {
            "name": name,
            "company": company,
            "role": role,
            "notes": body,
        }
