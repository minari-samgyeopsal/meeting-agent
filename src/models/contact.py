"""
연락처 데이터 모델

업체(Company)와 인물(Person) 정보를 구조화합니다.
Drive Contacts/Companies/*.md, Contacts/People/*.md와 대응됩니다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Company:
    """업체 정보"""
    
    name: str                      # 업체명
    domain: Optional[str] = None   # 웹사이트 도메인
    
    # 연락처
    main_email: Optional[str] = None  # 대표 이메일
    main_phone: Optional[str] = None  # 대표 전화
    
    # 소개
    description: str = ""          # 업체 소개
    industry: Optional[str] = None  # 산업
    size: Optional[str] = None      # 규모 (직원 수 등)
    
    # 뉴스 & 정보
    recent_news: List[dict] = field(default_factory=list)  # [{"title": "", "url": "", "date": ""}]
    last_news_search_at: Optional[datetime] = None  # 마지막 뉴스 검색 시간
    
    # 파라메타와의 관계
    service_touchpoints: List[str] = field(default_factory=list)  # 우리 서비스 연결점
    key_contact: Optional[str] = None  # 주요 연락처 (인물명)
    
    # 미팅 히스토리
    last_meeting_date: Optional[datetime] = None  # 마지막 미팅 날짜
    meeting_history_count: int = 0  # 미팅 횟수
    
    # 추적
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def needs_news_search(self, days: int = 7) -> bool:
        """뉴스 검색이 필요한지 판단 (기본 7일)"""
        if self.last_news_search_at is None:
            return True
        
        from datetime import timedelta
        return datetime.now() - self.last_news_search_at > timedelta(days=days)
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "name": self.name,
            "domain": self.domain,
            "main_email": self.main_email,
            "main_phone": self.main_phone,
            "description": self.description,
            "industry": self.industry,
            "size": self.size,
            "recent_news": self.recent_news,
            "service_touchpoints": self.service_touchpoints,
            "key_contact": self.key_contact,
            "last_meeting_date": self.last_meeting_date.isoformat() if self.last_meeting_date else None,
            "meeting_history_count": self.meeting_history_count,
        }


@dataclass
class Person:
    """인물 정보"""
    
    name: str                      # 이름
    title: Optional[str] = None    # 직책
    company: Optional[str] = None  # 소속 업체명
    
    # 연락처
    email: Optional[str] = None    # 이메일
    phone: Optional[str] = None    # 전화
    linkedin_url: Optional[str] = None  # LinkedIn 프로필
    
    # 공개 정보
    bio: str = ""                  # 간단 소개
    sns_profiles: List[dict] = field(default_factory=list)  # [{"platform": "", "url": ""}]
    
    # 인상·성향
    notes: str = ""                # 개인 노트 (성향, 관심사 등)
    
    # 미팅 히스토리
    last_meeting_date: Optional[datetime] = None
    meeting_history_count: int = 0
    
    # 추적
    is_internal: bool = False      # 내부 직원 여부
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "name": self.name,
            "title": self.title,
            "company": self.company,
            "email": self.email,
            "phone": self.phone,
            "linkedin_url": self.linkedin_url,
            "bio": self.bio,
            "sns_profiles": self.sns_profiles,
            "notes": self.notes,
            "last_meeting_date": self.last_meeting_date.isoformat() if self.last_meeting_date else None,
            "meeting_history_count": self.meeting_history_count,
            "is_internal": self.is_internal,
        }
