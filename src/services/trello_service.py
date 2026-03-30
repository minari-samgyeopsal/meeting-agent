"""
트렐로 서비스 (Trello API 기반)

사용 가능한 메서드:
- get_board: 보드 조회
- find_company_card: 업체 카드 찾기 (FR-A05)
- create_company_card: 업체 카드 생성 (FR-A06)
- add_checklist_item: 체크리스트 항목 추가 (FR-A05)
- get_card_context: 카드 컨텍스트 조회 (FR-B06-2)
"""

from trello import TrelloClient
from trello.board import Board
from trello.card import Card
from typing import Optional, List, Dict
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TrelloService:
    """Trello 카드 및 체크리스트 관리"""
    
    def __init__(self):
        if (not Config.TRELLO_API_KEY or not Config.TRELLO_API_TOKEN) and not Config.DRY_RUN_TRELLO:
            raise ValueError("TRELLO_API_KEY or TRELLO_API_TOKEN not set")

        self.client = None
        if Config.TRELLO_API_KEY and Config.TRELLO_API_TOKEN:
            self.client = TrelloClient(
                api_key=Config.TRELLO_API_KEY,
                token=Config.TRELLO_API_TOKEN,
            )

        self.board = None
        if self.client:
            self._init_board()
    
    def _init_board(self):
        """보드 초기화"""
        try:
            self.board = self.client.get_board(Config.TRELLO_BOARD_ID)
            logger.info(f"Trello board loaded: {self.board.name}")
        except Exception as e:
            logger.error(f"Error loading Trello board: {e}")
    
    def find_company_card(self, company_name: str) -> Optional[Card]:
        """
        업체 카드 찾기 (FR-B06-2, FR-A05)
        
        Args:
            company_name: 업체명
        
        Returns:
            Card 객체 또는 None
        """
        try:
            if Config.DRY_RUN_TRELLO and not self.board:
                return None

            if not self.board:
                logger.error("Trello board not initialized")
                return None
            
            for card in self.board.all_cards():
                if card.name == company_name:
                    logger.debug(f"Company card found: {company_name}")
                    return card
            
            logger.debug(f"Company card not found: {company_name}")
            return None
        
        except Exception as e:
            logger.error(f"Error finding company card: {e}")
            return None
    
    def create_company_card(self, company_name: str, list_name: str = "Contact/Meeting") -> Optional[Card]:
        """
        업체 카드 생성 (FR-A06)
        
        Args:
            company_name: 업체명 (카드명)
            list_name: 리스트명 (기본: "Contact/Meeting")
        
        Returns:
            생성된 Card 객체 또는 None
        """
        try:
            if Config.DRY_RUN_TRELLO:
                logger.info(f"[DRY RUN] Would create card: {company_name} in {list_name}")
                return _DummyCard(company_name)
            
            if not self.board:
                logger.error("Trello board not initialized")
                return None
            
            # 리스트 찾기
            target_list = None
            for list_obj in self.board.list_lists():
                if list_obj.name == list_name:
                    target_list = list_obj
                    break
            
            if not target_list:
                logger.error(f"List not found: {list_name}")
                return None
            
            # 카드 생성
            card = target_list.add_card(company_name)
            logger.info(f"Company card created: {company_name} ({card.id})")
            return card
        
        except Exception as e:
            logger.error(f"Error creating company card: {e}")
            return None
    
    def add_checklist_item(self, card: Card, title: str, description: str = "") -> bool:
        """
        체크리스트 항목 추가 (FR-A05)
        
        Args:
            card: Trello Card 객체
            title: 항목 제목
            description: 상세 설명
        
        Returns:
            성공 여부
        """
        try:
            if Config.DRY_RUN_TRELLO:
                logger.info(f"[DRY RUN] Would add checklist item: {title}")
                return True
            
            # Checklist 찾기 또는 생성
            checklist = None
            for cl in card.checklists:
                if cl.name == "Action Items":
                    checklist = cl
                    break
            
            if not checklist:
                checklist = card.add_checklist("Action Items", [])
            
            # 항목 추가
            checklist.add_checklist_item(title)
            
            logger.info(f"Checklist item added to {card.name}: {title}")
            return True
        
        except Exception as e:
            logger.error(f"Error adding checklist item: {e}")
            return False
    
    def get_card_context(self, card: Card, limit_comments: int = 3) -> Dict:
        """
        카드 컨텍스트 조회 (미완료 체크리스트 + 최근 코멘트)
        
        Args:
            card: Trello Card 객체
            limit_comments: 최근 코멘트 개수
        
        Returns:
            컨텍스트 딕셔너리
        """
        try:
            # 미완료 항목
            incomplete_items = []
            for checklist in card.checklists:
                for item in checklist.items:
                    if not item.get("state") == "complete":
                        incomplete_items.append(item.get("name"))
            
            # 최근 코멘트
            recent_comments = []
            for comment in card.comments[-limit_comments:]:
                recent_comments.append({
                    "author": comment.get("memberCreator", {}).get("fullName"),
                    "text": comment.get("data", {}).get("text"),
                })
            
            context = {
                "card_name": card.name,
                "incomplete_items": incomplete_items,
                "recent_comments": recent_comments,
                "url": card.url,
            }
            
            logger.debug(f"Card context retrieved: {card.name}")
            return context
        
        except Exception as e:
            logger.error(f"Error getting card context: {e}")
            return {}


class _DummyChecklist:
    def __init__(self):
        self.name = "Action Items"
        self.items = []

    def add_checklist_item(self, title, due=None):
        self.items.append({"name": title, "state": "incomplete"})


class _DummyCard:
    def __init__(self, name: str):
        self.name = name
        self.id = f"dry-run-{name}"
        self.url = "dry-run://trello-card"
        self.checklists = [_DummyChecklist()]
        self.comments = []
