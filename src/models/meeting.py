"""
미팅 데이터 모델

회의 정보를 구조화하여 에이전트 전체에서 일관되게 사용합니다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Meeting:
    """미팅 정보"""
    
    id: str              # Calendar Event ID
    title: str           # 미팅 제목
    start_time: datetime  # 시작 시간
    end_time: datetime    # 종료 시간
    
    organizer_email: str  # 주최자 이메일
    attendees: List[str] = field(default_factory=list)  # 참석자 이메일 목록
    
    description: str = ""  # 미팅 설명/어젠다
    location: str = ""     # 장소 또는 Meet URL
    
    is_external: bool = False  # 외부 미팅 여부
    is_google_meet: bool = False  # Google Meet 사용 여부
    
    # 추가 정보
    calendar_url: Optional[str] = None  # 캘린더 링크
    meet_url: Optional[str] = None      # Meet URL
    transcript_url: Optional[str] = None  # 회의록 (Drive 링크)
    
    # Before Agent 관련
    briefing_sent: bool = False  # 브리핑 발송 완료
    agenda_registered: bool = False  # 어젠다 등록 완료
    
    # During Agent 관련
    transcript_collected: bool = False  # Transcript 수집 완료
    notes_generated: bool = False  # 회의록 생성 완료
    
    # After Agent 관련
    items_extracted: bool = False  # 액션 아이템 추출 완료
    slack_notified: bool = False  # Slack 알림 완료
    
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """외부 미팅 여부 자동 판정"""
        # @parametacorp.com, @iconloop.com 외 도메인이 있으면 외부 미팅
        internal_domains = {"parametacorp.com", "iconloop.com"}
        
        for email in self.attendees:
            domain = email.split("@")[1]
            if domain not in internal_domains:
                self.is_external = True
                break
    
    def get_external_attendees(self) -> List[str]:
        """외부 참석자만 추출"""
        internal_domains = {"parametacorp.com", "iconloop.com"}
        return [
            email for email in self.attendees 
            if email.split("@")[1] not in internal_domains
        ]
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "id": self.id,
            "title": self.title,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "organizer_email": self.organizer_email,
            "attendees": self.attendees,
            "description": self.description,
            "location": self.location,
            "is_external": self.is_external,
            "is_google_meet": self.is_google_meet,
            "calendar_url": self.calendar_url,
            "meet_url": self.meet_url,
            "transcript_url": self.transcript_url,
            "briefing_sent": self.briefing_sent,
            "agenda_registered": self.agenda_registered,
            "transcript_collected": self.transcript_collected,
            "notes_generated": self.notes_generated,
            "items_extracted": self.items_extracted,
            "slack_notified": self.slack_notified,
        }
