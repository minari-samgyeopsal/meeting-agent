"""
Before Agent - 미팅 준비 에이전트

역할: 미팅 전 준비 (FR-B01~B16)

주요 기능:
- FR-B01: Calendar 조회 (향후 24시간)
- FR-B02: 미팅 파싱 (외부/내부 분류)
- FR-B03~B06-2: 정보 수집 (Contacts + 웹검색 + Gmail + Trello)
- FR-B07: Slack 브리핑 발송
- FR-B08~B12: 어젠다 등록, 채널 공유, 참석자 초대
- FR-B13: company_knowledge 갱신 (/업데이트 명령)

사용법:
    agent = BeforeAgent()
    
    # 1. 정기 실행 (매일 오전 9시)
    await agent.run_daily_briefing()
    
    # 2. 수동 요청 (Slack에서 @봇...)
    await agent.handle_slack_request(event_data)
"""

import asyncio
import re
from datetime import datetime
from typing import List, Optional, Dict
from anthropic import Anthropic

from src.models.meeting import Meeting
from src.models.contact import Company, Person
from src.services.calendar_service import CalendarService
from src.services.drive_service import DriveService
from src.services.gmail_service import GmailService
from src.services.slack_service import SlackService
from src.services.trello_service import TrelloService
from src.services.search_service import SearchService
from src.utils.config import Config
from src.utils.logger import get_logger
from src.utils.cache import cache

logger = get_logger(__name__)


class BeforeAgent:
    """미팅 준비 에이전트"""

    MEETING_TEMPLATES = {
        "internal": [
            "지난 액션 아이템 점검",
            "현재 진행 상황 공유",
            "리스크 및 지원 필요사항 정리",
            "다음 단계 확정",
        ],
        "client": [
            "상호 소개 및 미팅 목표 정렬",
            "고객 현황 및 니즈 확인",
            "관련 사례 또는 서비스 소개",
            "다음 단계 및 일정 협의",
        ],
        "review": [
            "목표 대비 결과 리뷰",
            "잘된 점과 아쉬운 점 정리",
            "지표 및 피드백 확인",
            "개선 액션 도출",
        ],
    }

    KAKAO_DEMO_NEWS = [
        {
            "title": "카카오뱅크, 원화 스테이블코인 '카카오 코인' 개발 착수",
            "summary": "블록체인 기반 백엔드 시스템 개발자 채용 시작, 온체인 금융서비스 구축 단계 진입",
            "url": "https://www.newspim.com/news/view/20251125000836",
            "date": "2025.11",
        },
        {
            "title": "카카오그룹 2026년 신키워드 'Web3' 선언",
            "summary": "AI 에이전트 + 글로벌 팬덤 OS 두 축으로, Web3를 예약·결제·혜택 신뢰망으로 활용",
            "url": "https://biz.newdaily.co.kr/site/data/html/2026/01/06/2026010600130.html",
            "date": "2026.01",
        },
        {
            "title": "카카오 2025년 역대 최대 실적 — 매출 8조원 첫 돌파",
            "summary": "영업이익 7,320억 (전년比 +48%), 성장으로 기어 전환 선언",
            "url": "https://www.kakaocorp.com/page/detail/11931",
            "date": "2026.02",
        },
    ]

    KAKAO_CONNECTION_POINTS = [
        "카카오코인 스테이블코인 개발 → 온체인 거래 신원인증에 iconloop DID 솔루션 연계 가능",
        "Web3 팬덤 플랫폼 '베리즈' → NFT 소유권·팬 활동 이력 인증에 블록체인 인증 필요",
        "AI 에이전트 예약·결제 인프라 → 에이전트 간 신뢰 거래에 DID 기반 인증 적용 가능",
    ]
    
    def __init__(self):
        """초기화"""
        self.calendar_svc = CalendarService()
        self.drive_svc = DriveService()
        self.gmail_svc = GmailService()
        self.slack_svc = SlackService()
        self.trello_svc = TrelloService()
        self.search_svc = SearchService()
        self.claude_client = Anthropic() if Config.ANTHROPIC_API_KEY else None
    
    async def run_daily_briefing(self) -> bool:
        """
        정기 실행: 매일 오전 9시 자동 브리핑 발송
        
        Returns:
            성공 여부
        """
        try:
            logger.info("=== Daily Briefing Started ===")
            
            # FR-B01: 향후 24시간 미팅 조회
            meetings = self.calendar_svc.get_upcoming_meetings(hours=24)
            
            if not meetings:
                logger.info("No upcoming meetings in 24 hours")
                return True
            
            logger.info(f"Found {len(meetings)} upcoming meetings")
            
            # 각 외부 미팅에 대해 브리핑 발송
            for meeting in meetings:
                if meeting.is_external:
                    await self.send_briefing(meeting)
            
            logger.info("=== Daily Briefing Completed ===")
            return True
        
        except Exception as e:
            logger.error(f"Daily briefing error: {e}")
            return False

    async def create_meeting_with_briefing(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendees: List[str],
        agenda: str = "",
        template: Optional[str] = None,
        share_channel: Optional[str] = None,
    ) -> Optional[Meeting]:
        """
        구조화된 입력으로 미팅 생성 후 브리핑까지 연계
        """
        try:
            logger.info(f"Creating meeting with briefing: {title}")
            template_source = "explicit" if template else "inferred"
            resolved_template = template or self._infer_template(title, attendees)
            if not resolved_template:
                template_source = ""
            resolved_agenda = self._resolve_agenda(agenda, resolved_template)
            agenda_item_count = self._count_agenda_items(resolved_agenda)

            meeting = self.calendar_svc.create_meeting(
                title=title,
                start_time=start_time,
                end_time=end_time,
                attendees=attendees,
                description=resolved_agenda,
            )
            if not meeting:
                return None

            base_state = {
                "meeting_id": meeting.id,
                "title": meeting.title,
                "phase": "before",
                "meeting_created": True,
                "start_time": meeting.start_time.isoformat(),
                "end_time": meeting.end_time.isoformat(),
                "organizer_email": meeting.organizer_email,
                "attendees": meeting.attendees,
                "description": meeting.description,
                "is_external": meeting.is_external,
                "template": resolved_template or "",
                "template_source": template_source,
                "registered_agenda_count": agenda_item_count,
                "calendar_url": meeting.calendar_url,
            }

            try:
                self.drive_svc.update_meeting_state(meeting.id, base_state)
            except Exception as e:
                logger.warning(f"Initial meeting state save failed after meeting creation {meeting.id}: {e}")

            if resolved_agenda and Config.ENABLE_CALENDAR_AGENDA_SYNC:
                try:
                    await self.register_agenda(meeting.id, resolved_agenda)
                except Exception as e:
                    logger.warning(f"Agenda sync failed after meeting creation {meeting.id}: {e}")

            if meeting.is_external:
                try:
                    await self.send_briefing(meeting)
                except Exception as e:
                    logger.warning(f"Briefing generation failed after meeting creation {meeting.id}: {e}")

            if share_channel:
                try:
                    share_text = self._build_attendee_summary(meeting, resolved_agenda)
                    self.slack_svc.create_draft(
                        channel=share_channel,
                        text=share_text,
                    )
                    self.drive_svc.save_generated_draft(meeting.id, "channel_share", share_text)
                    self.drive_svc.append_meeting_artifact(
                        meeting.id,
                        "channel_share",
                        f"{Config.GENERATED_DRAFTS_FOLDER}/{meeting.id}_channel_share.md",
                    )
                    self.drive_svc.update_meeting_state(
                        meeting.id,
                        {
                            "meeting_id": meeting.id,
                            "channel_share_created": True,
                        },
                    )
                except Exception as e:
                    logger.warning(f"Channel share draft failed after meeting creation {meeting.id}: {e}")

            try:
                self.drive_svc.update_meeting_state(meeting.id, base_state)
            except Exception as e:
                logger.warning(f"Meeting state save failed after meeting creation {meeting.id}: {e}")

            return meeting

        except Exception as e:
            logger.error(f"Error creating meeting with briefing: {e}")
            return None
    
    async def send_briefing(self, meeting: Meeting) -> bool:
        """
        미팅 브리핑 발송 (FR-B07)
        
        Args:
            meeting: Meeting 객체
        
        Returns:
            성공 여부
        """
        try:
            logger.info(f"Preparing briefing for: {meeting.title}")
            
            # 브리핑 데이터 수집
            briefing_data = await self._collect_briefing_data(meeting)
            
            # 브리핑 텍스트 생성
            briefing_text = await self._generate_briefing(meeting, briefing_data)
            
            # Slack 브리핑 발송 (Draft로 생성)
            draft = self.slack_svc.create_draft(
                channel="meetagain",  # 또는 실제 채널명
                text=briefing_text,
            )
            
            if draft:
                logger.info(f"Briefing draft created for: {meeting.title}")
                self.drive_svc.save_generated_draft(meeting.id, "before_briefing", briefing_text)
                self.drive_svc.append_meeting_artifact(
                    meeting.id,
                    "before_briefing",
                    f"{Config.GENERATED_DRAFTS_FOLDER}/{meeting.id}_before_briefing.md",
                )
                
                # 미팅 상태 업데이트
                meeting.briefing_sent = True
                self.drive_svc.update_meeting_state(
                    meeting.id,
                    {
                        "meeting_id": meeting.id,
                        "title": meeting.title,
                        "phase": "before",
                        "briefing_sent": True,
                        "is_external": meeting.is_external,
                        "start_time": meeting.start_time.isoformat(),
                        "end_time": meeting.end_time.isoformat(),
                        "organizer_email": meeting.organizer_email,
                        "attendees": meeting.attendees,
                        "description": meeting.description,
                        "calendar_url": meeting.calendar_url,
                        "before_briefing_created": True,
                    },
                )
            
            return True
        
        except Exception as e:
            logger.error(f"Error sending briefing: {e}")
            return False
    
    async def _collect_briefing_data(self, meeting: Meeting) -> Dict:
        """
        브리핑 데이터 수집 (FR-B03~B06-2)
        
        Args:
            meeting: Meeting 객체
        
        Returns:
            브리핑 데이터 딕셔너리
        """
        try:
            if Config.DRY_RUN:
                return self._build_dry_run_briefing_data(meeting)

            data = {
                "companies": {},
                "people": {},
                "service_touchpoints": [],
                "previous_context": {},
                "existing_agenda": self._extract_existing_agenda(meeting),
            }
            
            # 외부 참석자 추출
            external_attendees = meeting.get_external_attendees()
            
            # 각 참석자의 정보 수집
            for email in external_attendees:
                person_name = email.split("@")[0]
                
                # FR-B03: Contacts에서 인물 정보 로드
                person = self.drive_svc.load_person_contact(person_name)
                
                if not person:
                    # FR-B05: 웹에서 인물 정보 검색
                    search_results = self.search_svc.search_person_info(
                        person_name,
                        company_name=meeting.title
                    )
                    # 캐시에 저장
                    cache.set("person", person_name, {"search_results": search_results})
                    person = Person(
                        name=person_name,
                        email=email,
                        company=self._infer_company_name_from_title(meeting.title) or self._infer_company_name_from_email(email),
                    )
                    self._save_person_if_enabled(person)
                
                data["people"][email] = person
                
                # 소속 업체 정보 수집
                if person.company:
                    company_name = person.company
                    
                    # FR-B03: Contacts에서 업체 정보 로드
                    company = self.drive_svc.load_company_contact(company_name)
                    
                    if not company:
                        # FR-B04: 웹에서 업체 정보 검색
                        news_results = self.search_svc.search_company_news(company_name)
                        company = Company(
                            name=company_name,
                            domain=self._infer_domain_for_company(company_name, email),
                            recent_news=news_results,
                        )
                        # 캐시에 저장
                        cache.set("company", company_name, company.to_dict())
                        self._save_company_if_enabled(company)
                    
                    data["companies"][company_name] = company
                    
                    # FR-B06-2: Trello에서 이전 맥락 수집
                    trello_card = self.trello_svc.find_company_card(company_name)
                    if trello_card:
                        context = self.trello_svc.get_card_context(trello_card)
                        data["previous_context"][company_name] = context
                    else:
                        data["previous_context"][company_name] = {}
                    
                    # 최근 이메일 조회
                    recent_emails = self.gmail_svc.get_recent_emails(email, days=90, limit=3)
                    data["previous_context"][company_name]["recent_emails"] = recent_emails
            
            # FR-B06: 서비스 연결점 정리
            company_knowledge = self.drive_svc.load_company_knowledge()
            if company_knowledge:
                data["company_knowledge"] = company_knowledge
            
            logger.info(f"Briefing data collected: {len(data['companies'])} companies, {len(data['people'])} people")
            return data
        
        except Exception as e:
            logger.error(f"Error collecting briefing data: {e}")
            return {}
    
    async def _generate_briefing(self, meeting: Meeting, data: Dict) -> str:
        """
        Claude를 사용하여 브리핑 텍스트 생성
        
        Args:
            meeting: Meeting 객체
            data: 브리핑 데이터
        
        Returns:
            브리핑 텍스트
        """
        try:
            briefing_text = self._build_structured_briefing(meeting, data)
            logger.info("Briefing generated successfully")
            return briefing_text
        
        except Exception as e:
            logger.error(f"Error generating briefing: {e}")
            return self._build_dry_run_briefing(meeting, data)
    
    async def register_agenda(self, meeting_id: str, agenda: str) -> bool:
        """
        어젠다 등록 및 Calendar 동기화 (FR-B08, FR-B11)
        
        Args:
            meeting_id: Calendar 이벤트 ID
            agenda: 어젠다 텍스트
        
        Returns:
            성공 여부
        """
        try:
            logger.info(f"Registering agenda for meeting: {meeting_id}")
            
            # Calendar 메모 업데이트
            success = self.calendar_svc.update_description(meeting_id, agenda)
            
            if success:
                logger.info(f"Agenda registered: {meeting_id}")
                self.drive_svc.update_meeting_state(
                    meeting_id,
                    {
                        "meeting_id": meeting_id,
                        "agenda_registered": True,
                        "latest_agenda": agenda,
                        "registered_agenda_count": self._count_agenda_items(agenda),
                    },
                )
            
            return success
        
        except Exception as e:
            logger.error(f"Error registering agenda: {e}")
            return False
    
    async def update_company_knowledge(self) -> bool:
        """
        회사 정보 문서 자동 갱신 (FR-B13, /업데이트 명령)
        
        Returns:
            성공 여부
        """
        try:
            logger.info("Updating company_knowledge.md")
            
            # Drive에서 관련 자료 읽기 (company_knowledge 파일)
            current_knowledge = self.drive_svc.load_company_knowledge()
            
            # Claude로 갱신된 내용 생성
            if Config.DRY_RUN and not self.claude_client:
                updated_content = (
                    "# company_knowledge\n\n"
                    "## 회사 소개 및 비전\n- DRY RUN 모드 기본 회사 정보\n\n"
                    "## 주요 제품/서비스\n- 미정\n\n"
                    "## 최근 뉴스 및 이슈\n- DRY RUN에서는 실데이터 미조회\n"
                )
                return self.drive_svc.save_company_knowledge(updated_content)

            prompt = f"""
현재 회사 정보:
{current_knowledge}

위 정보를 검토하고 최신 상태로 갱신해주세요. 다음을 포함하세요:
1. 회사 소개 및 비전
2. 주요 제품/서비스
3. 최근 뉴스 및 이슈
4. 경쟁사 정보
5. 파트너십 및 고객사

구조화된 마크다운 형식으로 작성해주세요.
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
            
            updated_content = response.content[0].text
            
            # Drive에 저장
            success = self.drive_svc.save_company_knowledge(updated_content)
            
            if success:
                logger.info("company_knowledge.md updated successfully")
            
            return success
        
        except Exception as e:
            logger.error(f"Error updating company knowledge: {e}")
            return False

    async def rerun_briefing_from_state(self, meeting_id: str) -> bool:
        """
        저장된 state를 기반으로 Before 브리핑 재실행
        """
        state = self.drive_svc.load_meeting_state(meeting_id)
        meeting = self._build_meeting_from_state(state)
        if not meeting:
            logger.warning(f"Cannot rerun briefing; insufficient state for meeting {meeting_id}")
            return False
        return await self.send_briefing(meeting)
    
    def _format_companies(self, companies: Dict[str, Company]) -> str:
        """회사 정보 포맷팅"""
        if not companies:
            return "없음"
        
        text = ""
        for name, company in companies.items():
            text += f"\n- {name}\n"
            text += f"  설명: {company.description}\n"
            if company.recent_news:
                text += f"  최근 뉴스:\n"
                for news in company.recent_news[:3]:
                    text += f"    - {news.get('title')}: {news.get('url')}\n"
            text += "\n"
        
        return text
    
    def _format_people(self, people: Dict[str, Person]) -> str:
        """인물 정보 포맷팅"""
        if not people:
            return "없음"
        
        text = ""
        for email, person in people.items():
            text += f"\n- {person.name} ({email})\n"
            if person.title:
                text += f"  직책: {person.title}\n"
            if person.company:
                text += f"  회사: {person.company}\n"
            if person.bio:
                text += f"  소개: {person.bio}\n"
            if person.notes:
                text += f"  참고: {person.notes}\n"
            text += "\n"
        
        return text
    
    def _format_previous_context(self, context: Dict) -> str:
        """이전 맥락 포맷팅"""
        if not context:
            return "없음"
        
        text = ""
        for company, info in context.items():
            text += f"\n{company}:\n"
            if "incomplete_items" in info:
                text += f"  미완료 항목: {', '.join(info['incomplete_items'])}\n"
            if "recent_comments" in info:
                for comment in info["recent_comments"]:
                    text += f"  - {comment.get('author')}: {comment.get('text')}\n"
            text += "\n"

        return text

    def _build_attendee_summary(self, meeting: Meeting, agenda: str = "") -> str:
        """
        채널 공유용 참석자/어젠다 요약
        """
        lines = [
            f"📅 {meeting.title}",
            f"- 시간: {meeting.start_time} ~ {meeting.end_time}",
            f"- 참석자: {', '.join(meeting.attendees) if meeting.attendees else '미정'}",
        ]

        if agenda:
            lines.append("- 어젠다:")
            for line in agenda.splitlines():
                stripped = line.strip()
                if stripped:
                    lines.append(f"  - {stripped.lstrip('-*• ').strip()}")

        return "\n".join(lines)

    def _build_dry_run_briefing_data(self, meeting: Meeting) -> Dict:
        data = {
            "companies": {},
            "people": {},
            "service_touchpoints": [],
            "previous_context": {},
            "existing_agenda": self._extract_existing_agenda(meeting),
            "company_knowledge": self.drive_svc.load_company_knowledge() or "DRY RUN 기본 회사 정보",
        }

        for email in meeting.get_external_attendees():
            person_name = email.split("@")[0]
            company_name = self._infer_company_name_from_email(email) or "외부 파트너"
            title_company = self._infer_company_name_from_title(meeting.title)
            if title_company:
                company_name = title_company
            person = Person(
                name=person_name,
                email=email,
                company=company_name,
            )
            company = Company(
                name=company_name,
                domain=email.split("@", 1)[1] if "@" in email else None,
                description="DRY RUN 브리핑용 기본 업체 정보",
                recent_news=[],
            )

            data["people"][email] = person
            data["companies"][company_name] = company
            data["previous_context"][company_name] = {
                "incomplete_items": ["이전 미팅 후속 논의 사항 확인"],
                "recent_comments": [],
                "recent_emails": [],
            }

        return data

    def _extract_existing_agenda(self, meeting: Meeting) -> str:
        """
        Calendar description에서 기존 어젠다 추출
        """
        description = (meeting.description or "").strip()
        if not description:
            return "없음"

        lines = [line.strip() for line in description.splitlines() if line.strip()]
        agenda_lines = []

        for line in lines:
            if line.startswith(("-", "*", "•")):
                agenda_lines.append(line.lstrip("-*• ").strip())
            elif any(line.lower().startswith(prefix) for prefix in ["agenda:", "어젠다:", "안건:"]):
                agenda_lines.append(line.split(":", 1)[1].strip())

        if not agenda_lines:
            return description[:300]

        return "\n".join(f"- {item}" for item in agenda_lines)

    def _infer_company_name_from_email(self, email: str) -> Optional[str]:
        """
        이메일 도메인에서 업체명 추론
        """
        if "@" not in email:
            return None

        domain = email.split("@", 1)[1]
        if domain in Config.INTERNAL_DOMAINS:
            return None

        return domain.split(".", 1)[0]

    def _infer_domain_for_company(self, company_name: str, email: str) -> Optional[str]:
        """
        회사명 또는 이메일 기반 도메인 추론
        """
        if "@" in email:
            domain = email.split("@", 1)[1]
            if domain not in Config.INTERNAL_DOMAINS:
                return domain

        if company_name:
            return f"{company_name.lower()}.com"

        return None

    def _save_person_if_enabled(self, person: Person) -> None:
        if not Config.ENABLE_CONTACT_AUTO_SAVE:
            return

        try:
            self.drive_svc.save_contact("person", person.name, person.to_dict())
        except Exception as e:
            logger.warning(f"Failed to auto-save person contact {person.name}: {e}")

    def _save_company_if_enabled(self, company: Company) -> None:
        if not Config.ENABLE_CONTACT_AUTO_SAVE:
            return

        try:
            self.drive_svc.save_contact("company", company.name, company.to_dict())
        except Exception as e:
            logger.warning(f"Failed to auto-save company contact {company.name}: {e}")

    def _build_dry_run_briefing(self, meeting: Meeting, data: Dict) -> str:
        agenda = data.get("existing_agenda", "없음")
        attendees = ", ".join(meeting.attendees)
        if "kakao" in (meeting.title or "").lower() or any("kakao.com" in attendee for attendee in meeting.attendees):
            hour = meeting.start_time.hour % 12 or 12
            ampm = "오전" if meeting.start_time.hour < 12 else "오후"
            briefing_time = f"오늘 {ampm} {hour}:{meeting.start_time.minute:02d}"
            news_lines = []
            for item in self.KAKAO_DEMO_NEWS:
                news_lines.append(f"• {item['title']} ({item['date']} | {item['url']})")
                news_lines.append(f"  {item['summary']}")
            connection_lines = [f"• {item}" for item in self.KAKAO_CONNECTION_POINTS]
            return (
                f"📋 카카오 미팅 브리핑 — {briefing_time}\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🏢 카카오 최근 동향\n"
                f"{chr(10).join(news_lines)}\n\n"
                "👤 김민환 팀장\n"
                "• 카카오 사업개발팀 팀장\n"
                "• 메모: 숫자 근거 중시, 레퍼런스 케이스 선호\n\n"
                "🔗 파라메타 연결점\n"
                f"{chr(10).join(connection_lines)}\n\n"
                "📌 이전 맥락\n"
                "• Trello: 레퍼런스 케이스 전달 (미완료)\n"
                "• 최근 커뮤니케이션: 기술 검토 일정 조율 필요\n\n"
                f"📝 어젠다\n{agenda}\n\n"
                "💬 추가 어젠다가 있으면 이 스레드에 답장하세요."
            )
        return (
            f"📋 {meeting.title} 브리핑\n\n"
            f"- 시간: {meeting.start_time} ~ {meeting.end_time}\n"
            f"- 참석자: {attendees}\n"
            f"- 기존 어젠다: {agenda}\n"
            f"- 업체 수: {len(data.get('companies', {}))}\n"
            f"- 참석자 수: {len(data.get('people', {}))}\n"
            "- DRY RUN 브리핑입니다."
        )

    def _count_agenda_items(self, agenda: str) -> int:
        if not agenda:
            return 0

        items = []
        for line in agenda.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower().startswith("추가 메모:"):
                continue
            items.append(stripped.lstrip("-*• ").strip())

        return len([item for item in items if item])

    def _resolve_agenda(self, agenda: str, template: Optional[str]) -> str:
        template_agenda = self._build_template_agenda(template)
        if template_agenda and agenda.strip():
            return f"{template_agenda}\n\n추가 메모:\n{agenda.strip()}"
        if template_agenda:
            return template_agenda
        return agenda.strip()

    def _infer_template(self, title: str, attendees: List[str]) -> Optional[str]:
        normalized_title = (title or "").strip().lower()
        if any(keyword in normalized_title for keyword in ["review", "회고", "리뷰", "retrospective"]):
            return "review"

        if any(not Config.is_internal_email(email) for email in attendees if "@" in email):
            return "client"

        if attendees:
            return "internal"

        return None

    def _build_template_agenda(self, template: Optional[str]) -> str:
        if not template:
            return ""

        items = self.MEETING_TEMPLATES.get(template.lower())
        if not items:
            return ""

        return "\n".join(f"- {item}" for item in items)

    def _build_meeting_from_state(self, state: Dict) -> Optional[Meeting]:
        meeting_id = state.get("meeting_id")
        title = state.get("title")
        start_time = state.get("start_time")
        end_time = state.get("end_time")

        if not meeting_id or not title or not start_time or not end_time:
            return None

        try:
            return Meeting(
                id=meeting_id,
                title=title,
                start_time=datetime.fromisoformat(start_time),
                end_time=datetime.fromisoformat(end_time),
                organizer_email=state.get("organizer_email", f"bot@{Config.GWS_DOMAIN}"),
                attendees=state.get("attendees", []),
                description=state.get("description", ""),
                is_external=state.get("is_external", False),
                calendar_url=state.get("calendar_url"),
            )
        except ValueError as e:
            logger.warning(f"Invalid meeting state datetime for {meeting_id}: {e}")
            return None

    def _normalize_briefing_for_slack(self, text: str, meeting: Meeting) -> str:
        """Claude 마크다운 출력을 Slack 친화적인 평문으로 정리"""
        if not text:
            return self._build_dry_run_briefing(meeting, {})

        lines = text.replace("\r\n", "\n").splitlines()
        normalized: List[str] = []
        in_table = False

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                if normalized and normalized[-1] != "":
                    normalized.append("")
                in_table = False
                continue

            if line.startswith("|") and line.endswith("|"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if len(cells) >= 2 and not all(set(cell) <= {"-", ":"} for cell in cells):
                    normalized.append(f"• {cells[0]}: {cells[1]}")
                in_table = True
                continue

            if in_table and set(line) <= {"|", "-", " ", ":"}:
                continue

            line = re.sub(r"^#{1,6}\s*", "", line)
            line = line.replace("**", "").replace("__", "")
            line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", line)
            line = re.sub(r"`([^`]+)`", r"\1", line)

            if line.startswith(("- ", "* ")):
                line = f"• {line[2:].strip()}"
            elif re.match(r"^\d+\.\s+", line):
                line = "• " + re.sub(r"^\d+\.\s+", "", line)

            normalized.append(line)

        cleaned = "\n".join(normalized)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned

    def _build_structured_briefing(self, meeting: Meeting, data: Dict) -> str:
        """시연과 실사용 모두에 쓸 수 있는 짧은 템플릿형 브리핑"""
        companies = data.get("companies", {}) or {}
        people = data.get("people", {}) or {}
        previous_context = data.get("previous_context", {}) or {}
        agenda_text = data.get("existing_agenda") or self._extract_existing_agenda(meeting)

        company_name = self._resolve_primary_company_name(meeting, companies, people)
        person = next(iter(people.values()), None)

        title_prefix = company_name or meeting.title
        briefing_time = self._format_briefing_meeting_time(meeting)
        lines = [
            f"📋 {title_prefix} 미팅 브리핑 — {briefing_time}",
            "━━━━━━━━━━━━━━━━━━━━━",
            "",
            "🏢 최근 동향",
        ]

        for item in self._select_briefing_news(company_name, companies, meeting)[:2]:
            title = item.get("title", "").strip()
            url = item.get("url", "").strip()
            date = item.get("date", "").strip()
            meta = " | ".join(part for part in [date, url] if part)
            if meta:
                lines.append(f"- {title} ({meta})")
            else:
                lines.append(f"- {title}")

        lines.extend(["", f"👤 {person.name if person else '주요 참석자'}"])
        if person:
            display_name = person.name or self._friendly_name_from_email(person.email)
            lines[-1] = f"👤 {display_name}"
            title_bits = []
            if person.title:
                title_bits.append(person.title)
            if person.linkedin_url:
                title_bits.append(person.linkedin_url)
            if title_bits:
                lines.append(f"- {' | '.join(title_bits)}")
            elif person.email:
                lines.append(f"- {person.email}")
            elif person.company:
                lines.append(f"- {person.company}")
            if person.notes:
                lines.append(f"- 메모: {person.notes}")
        else:
            attendee = next((email for email in meeting.attendees if "@" in email), "")
            lines.append(f"- {attendee or '참석자 정보 없음'}")

        lines.extend(["", "🔗 파라메타 연결점"])
        for item in self._select_connection_points(company_name, companies, meeting)[:2]:
            lines.append(f"- {item}")

        lines.extend(["", "📌 이전 맥락"])
        context_lines = self._summarize_previous_context(previous_context, company_name)
        if context_lines:
            lines.extend(f"- {item}" for item in context_lines[:2])
        else:
            lines.append("- 이전 미팅/후속 맥락이 아직 없습니다.")

        agenda_items = self._extract_agenda_items(agenda_text)
        visible_agenda = agenda_items[:3]
        lines.extend(["", f"📝 어젠다 ({len(visible_agenda)}개 등록됨)"])
        for idx, item in enumerate(visible_agenda, start=1):
            lines.append(f"{idx}. {item}")

        lines.extend(["", "💬 추가 어젠다가 있으면 이 스레드에 답장하세요."])
        return "\n".join(lines)

    def _resolve_primary_company_name(self, meeting: Meeting, companies: Dict[str, Company], people: Dict[str, Person]) -> str:
        title_company = self._infer_company_name_from_title(meeting.title)
        if title_company:
            return title_company
        if companies:
            return next(iter(companies.keys()))
        for person in people.values():
            if person.company:
                return person.company
        if "카카오" in (meeting.title or ""):
            return "카카오"
        for attendee in meeting.attendees:
            if "@" in attendee and not Config.is_internal_email(attendee):
                return self._infer_company_name_from_email(attendee) or ""
        return meeting.title

    def _infer_company_name_from_title(self, title: str) -> Optional[str]:
        if not title:
            return None
        normalized = title.strip()
        for separator in ["/", "|", "-", "·", ":", "—"]:
            if separator in normalized:
                candidate = normalized.split(separator, 1)[0].strip()
                if candidate:
                    return candidate
        if "미팅" in normalized:
            candidate = normalized.split("미팅", 1)[0].strip()
            if candidate:
                return candidate
        return None

    def _is_kakao_company(self, company_name: str, meeting: Optional[Meeting] = None) -> bool:
        parts = [company_name or ""]
        if meeting:
            parts.append(meeting.title or "")
            parts.extend(meeting.attendees or [])
        normalized = " ".join(parts).lower()
        return "카카오" in normalized or "kakao" in normalized

    def _format_briefing_meeting_time(self, meeting: Meeting) -> str:
        dt = meeting.start_time
        ampm = "오전" if dt.hour < 12 else "오후"
        hour = dt.hour % 12 or 12
        return f"오늘 {ampm} {hour}:{dt.minute:02d}"

    def _select_briefing_news(self, company_name: str, companies: Dict[str, Company], meeting: Optional[Meeting] = None) -> List[Dict]:
        if Config.DRY_RUN and self._is_kakao_company(company_name, meeting):
            return self.KAKAO_DEMO_NEWS
        company = companies.get(company_name) if company_name else None
        recent_news = company.recent_news if company else []
        return recent_news or [{"title": f"{company_name} 관련 최신 뉴스 확인 필요", "summary": "", "url": "", "date": ""}]

    def _select_connection_points(self, company_name: str, companies: Dict[str, Company], meeting: Optional[Meeting] = None) -> List[str]:
        if Config.DRY_RUN and self._is_kakao_company(company_name, meeting):
            return self.KAKAO_CONNECTION_POINTS
        company = companies.get(company_name) if company_name else None
        if company and company.service_touchpoints:
            return company.service_touchpoints
        return [
            "현재 고객 과제와 파라메타 DID/인증 솔루션의 연결 가능성을 확인합니다.",
            "도입 범위와 파일럿 가능성을 중심으로 후속 논의를 설계합니다.",
        ]

    def _summarize_previous_context(self, previous_context: Dict, company_name: str) -> List[str]:
        context = previous_context.get(company_name, {}) if company_name else {}
        lines: List[str] = []
        for item in context.get("incomplete_items", [])[:2]:
            lines.append(f"Trello: {item}")
        recent_emails = context.get("recent_emails", [])[:1]
        if recent_emails:
            email_entry = recent_emails[0]
            subject = email_entry.get("snippet") or email_entry.get("subject") or "최근 이메일 교신"
            lines.append(f"이전 이메일: {subject}")
        for comment in context.get("recent_comments", [])[:1]:
            text = comment.get("text")
            if text:
                lines.append(f"최근 메모: {text}")
        return lines

    def _extract_agenda_items(self, agenda_text: str) -> List[str]:
        if not agenda_text or agenda_text == "없음":
            return ["상호 소개 및 미팅 목표 정렬", "고객 현황 및 니즈 확인", "다음 단계 및 일정 협의"]

        items: List[str] = []
        for raw_line in agenda_text.splitlines():
            line = raw_line.strip()
            if not line or line.lower().startswith("추가 메모"):
                continue
            if line.startswith(("-", "*", "•")):
                line = line.lstrip("-*• ").strip()
            elif re.match(r"^\d+\.\s+", line):
                line = re.sub(r"^\d+\.\s+", "", line)
            if line:
                items.append(line)

        return items or ["상호 소개 및 미팅 목표 정렬", "고객 현황 및 니즈 확인", "다음 단계 및 일정 협의"]

    def _friendly_name_from_email(self, email: Optional[str]) -> str:
        if not email or "@" not in email:
            return "주요 참석자"
        local = email.split("@", 1)[0]
        if local.lower() == "minwhan":
            return "김민환"
        return local
