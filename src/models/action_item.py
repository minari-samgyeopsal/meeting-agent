"""
액션 아이템 모델

미팅 후 추출된 태스크를 구조화합니다.
Trello 체크리스트 및 Slack 알림에 사용됩니다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class ActionStatus(str, Enum):
    """액션 아이템 상태"""
    PENDING = "pending"      # 미처리
    IN_PROGRESS = "in_progress"  # 진행 중
    COMPLETED = "completed"  # 완료
    BLOCKED = "blocked"      # 차단됨
    CANCELLED = "cancelled"  # 취소


@dataclass
class ActionItem:
    """액션 아이템 (To-Do 항목)"""
    
    id: str                   # 고유 ID (Trello 체크리스트 ID)
    title: str                # 작업 제목
    
    # 소속
    meeting_id: str           # 출처 미팅 ID
    company_name: str         # 관련 업체명
    trello_card_id: Optional[str] = None  # Trello 카드 ID
    
    # 담당자
    assignee_email: Optional[str] = None  # 담당자 이메일
    assignee_name: Optional[str] = None   # 담당자 이름 (이메일 없을 시)
    
    # 상세
    description: str = ""     # 상세 설명
    due_date: Optional[datetime] = None  # 기한
    priority: str = "normal"  # 우선순위: high, normal, low
    
    # 분류
    category: str = "general"  # 분류: general, proposal, research, followup 등
    
    # 상태
    status: ActionStatus = ActionStatus.PENDING
    
    # 추적
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    def is_overdue(self) -> bool:
        """기한 초과 여부"""
        if self.due_date is None or self.status == ActionStatus.COMPLETED:
            return False
        return datetime.now() > self.due_date
    
    def days_until_due(self) -> Optional[int]:
        """기한까지 남은 일수"""
        if self.due_date is None:
            return None
        from datetime import datetime as dt
        delta = self.due_date - dt.now()
        return delta.days
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "id": self.id,
            "title": self.title,
            "meeting_id": self.meeting_id,
            "company_name": self.company_name,
            "trello_card_id": self.trello_card_id,
            "assignee_email": self.assignee_email,
            "assignee_name": self.assignee_name,
            "description": self.description,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "priority": self.priority,
            "category": self.category,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
