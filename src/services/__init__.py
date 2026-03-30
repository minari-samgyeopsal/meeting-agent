"""
외부 API 통합 서비스 모듈

- calendar_service: Google Calendar (gws)
- drive_service: Google Drive (gws) - Contacts, company_knowledge
- gmail_service: Gmail (gws) - 이메일 검색
- slack_service: Slack MCP - 메시지 발송, Draft
- trello_service: Trello API - 업체 카드·체크리스트
- search_service: Web Search - 업체·인물 리서치
"""

from .calendar_service import CalendarService
from .drive_service import DriveService
from .gmail_service import GmailService
from .slack_service import SlackService
from .trello_service import TrelloService
from .search_service import SearchService

__all__ = [
    "CalendarService",
    "DriveService",
    "GmailService",
    "SlackService",
    "TrelloService",
    "SearchService",
]
