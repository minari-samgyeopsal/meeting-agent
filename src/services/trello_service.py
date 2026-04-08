"""
트렐로 서비스 (Trello API 기반)

사용 가능한 메서드:
- get_board: 보드 조회
- find_company_card: 업체 카드 찾기 (FR-A05)
- create_company_card: 업체 카드 생성 (FR-A06)
- add_checklist_item: 체크리스트 항목 추가 (FR-A05)
- get_card_context: 카드 컨텍스트 조회 (FR-B06-2)
- list_cards_by_board_scope: 카드 후보 조회
- recommend_card_from_message: 메시지 기반 추천 카드 선정
- build_archive_registration_preview: dry-run 등록 preview 생성
- register_archive_entry: 채널 메시지를 카드 코멘트/체크리스트로 등록
"""

from trello import TrelloClient
from trello.board import Board
from trello.card import Card
from typing import Optional, List, Dict
import re
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TrelloService:
    """Trello 카드 및 체크리스트 관리"""
    
    def __init__(self):
        if (not Config.TRELLO_API_KEY or not Config.TRELLO_API_TOKEN) and not (Config.DRY_RUN or Config.DRY_RUN_TRELLO):
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
            if Config.DRY_RUN or Config.DRY_RUN_TRELLO:
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
            if Config.DRY_RUN or Config.DRY_RUN_TRELLO:
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

    def list_cards_by_board_scope(self, message: str = "", board_scope: Optional[str] = None) -> List[Dict]:
        """추천용 카드 목록 조회"""
        try:
            if Config.DRY_RUN or Config.DRY_RUN_TRELLO or not self.board:
                return self._dummy_card_candidates(message)

            candidates = []
            for card in self.board.all_cards():
                candidates.append(
                    {
                        "board": board_scope or self.board.name,
                        "card_id": getattr(card, "id", ""),
                        "card_name": getattr(card, "name", ""),
                        "url": getattr(card, "url", ""),
                    }
                )
            return candidates
        except Exception as e:
            logger.error(f"Error listing Trello cards: {e}")
            return self._dummy_card_candidates(message)

    def recommend_card_from_message(self, message: str, cards: List[Dict]) -> Dict:
        """메시지와 카드명 간 가중치 기반 추천"""
        if not cards:
            return {
                "board": "사용자 선택",
                "card_id": "",
                "card_name": "직접 선택 필요",
                "score": 0,
                "url": "",
            }

        message_tokens = self._tokenize(message)
        compact_message = re.sub(r"\s+", "", message.lower())
        best = None
        best_score = -1
        for card in cards:
            name = card.get("card_name", "")
            board = card.get("board", "")
            name_tokens = self._tokenize(name)
            compact_name = re.sub(r"\s+", "", name.lower())
            score = len(message_tokens & name_tokens) * 2
            if name and name in message:
                score += 4
            elif compact_name and compact_name in compact_message:
                score += 3
            elif any(token and token in compact_message for token in compact_name.split("/") if len(token) >= 2):
                score += 1

            if any(keyword in message for keyword in ["프로젝트", "개발", "기술", "배포", "로드맵"]) and "프로젝트" in board:
                score += 2
            if any(keyword in message for keyword in ["거래처", "파트너", "고객", "미팅", "세일즈", "영업"]) and "세일즈" in board:
                score += 2
            if any(keyword in message for keyword in ["법률", "리스크", "검토", "계약", "제안"]) and "세일즈" in board:
                score += 1
            if score > best_score:
                best = card
                best_score = score

        if not best:
            return {
                "board": "사용자 선택",
                "card_id": "",
                "card_name": "직접 선택 필요",
                "score": 0,
                "url": "",
            }

        enriched = dict(best)
        enriched["score"] = best_score
        return enriched

    def build_archive_registration_preview(
        self,
        message_text: str,
        recommendation: Dict,
        action_items: List[Dict],
        event: Optional[Dict] = None,
    ) -> Dict:
        """실제 write 없이 등록 예정 payload 생성"""
        event = event or {}
        candidate_cards = self.list_cards_by_board_scope(message=message_text)
        return {
            "message_text": message_text,
            "channel": event.get("channel"),
            "message_ts": event.get("ts"),
            "card_url": recommendation.get("url") or "dry-run://trello-card",
            "card_name": recommendation.get("card_name"),
            "board": recommendation.get("board"),
            "action_items": action_items[:3],
            "candidate_cards": candidate_cards[:5],
        }

    def register_archive_entry(self, payload: Dict) -> Dict:
        """채널 모니터 payload를 Trello 코멘트/체크리스트로 등록"""
        recommendation = payload.get("recommendation") or {}
        preview = payload.get("preview") or {}
        event_meta = payload.get("event_meta") or {}
        action_items = preview.get("action_items") or []
        card = self._resolve_card_for_archive(recommendation, preview)
        if not card:
            return {
                "ok": False,
                "message": "등록할 Trello 카드를 찾지 못했습니다.",
                "card_url": recommendation.get("url") or preview.get("card_url") or "",
            }

        comment_text = self._build_archive_comment(preview, recommendation, event_meta)
        checklist_name = self._build_archive_checklist_name(recommendation, event_meta)
        try:
            self._add_comment_to_card(card, comment_text)
            for item in action_items[:3]:
                self._add_checklist_item_with_name(card, checklist_name, self._format_action_item(item))
            return {
                "ok": True,
                "message": "Trello 카드에 코멘트와 체크리스트를 등록했습니다.",
                "card_name": getattr(card, "name", recommendation.get("card_name", "")),
                "card_url": getattr(card, "url", preview.get("card_url") or ""),
                "action_item_count": len(action_items[:3]),
            }
        except Exception as e:
            logger.error(f"Error registering archive entry: {e}")
            return {
                "ok": False,
                "message": f"Trello 등록 중 오류가 발생했습니다: {e}",
                "card_url": getattr(card, "url", preview.get("card_url") or ""),
            }

    @staticmethod
    def _tokenize(text: str) -> set:
        return {token for token in re.split(r"[^0-9A-Za-z가-힣]+", (text or "").lower()) if len(token) >= 2}

    @staticmethod
    def _dummy_card_candidates(message: str = "") -> List[Dict]:
        pool = [
            {"board": "세일즈 파이프라인", "card_id": "dry-mirae", "card_name": "미래에셋증권", "url": "dry-run://mirae"},
            {"board": "세일즈 파이프라인", "card_id": "dry-kakao", "card_name": "카카오", "url": "dry-run://kakao"},
            {"board": "세일즈 파이프라인", "card_id": "dry-naver", "card_name": "네이버", "url": "dry-run://naver"},
            {"board": "프로젝트 모니터", "card_id": "dry-web3", "card_name": "Web3 인증 프로젝트", "url": "dry-run://web3"},
            {"board": "프로젝트 모니터", "card_id": "dry-agent", "card_name": "에이전트 운영 개선", "url": "dry-run://agent"},
        ]
        if not message:
            return pool
        boosted = sorted(
            pool,
            key=lambda item: (item["card_name"] in message, item["board"] in message),
            reverse=True,
        )
        return boosted

    def _resolve_card_for_archive(self, recommendation: Dict, preview: Dict):
        card_id = recommendation.get("card_id")
        card_name = recommendation.get("card_name")
        card_url = recommendation.get("url") or preview.get("card_url")
        if (
            Config.DRY_RUN
            or Config.DRY_RUN_TRELLO
            or str(card_id).startswith("dry-")
            or str(card_url).startswith("dry-run://")
        ):
            return _DummyCard(card_name or "dry-run-card", url=card_url)

        if not self.board:
            return None
        for card in self.board.all_cards():
            if card_id and getattr(card, "id", "") == card_id:
                return card
            if card_name and getattr(card, "name", "") == card_name:
                return card
        return None

    def _add_comment_to_card(self, card, comment_text: str) -> None:
        if Config.DRY_RUN or Config.DRY_RUN_TRELLO:
            logger.info(f"[DRY RUN] Would add comment to {getattr(card, 'name', 'unknown')}")
        if hasattr(card, "comment"):
            card.comment(comment_text)
            return
        if hasattr(card, "comments") and isinstance(card.comments, list):
            card.comments.append({"data": {"text": comment_text}, "memberCreator": {"fullName": "Meetagain"}})
            return
        raise AttributeError("Card object does not support comments")

    def _add_checklist_item_with_name(self, card, checklist_name: str, title: str) -> None:
        if Config.DRY_RUN or Config.DRY_RUN_TRELLO:
            logger.info(f"[DRY RUN] Would add checklist item: {title}")
        checklist = None
        for cl in getattr(card, "checklists", []):
            if getattr(cl, "name", "") == checklist_name:
                checklist = cl
                break
        if not checklist:
            if hasattr(card, "add_checklist"):
                checklist = card.add_checklist(checklist_name, [])
            else:
                checklist = _DummyChecklist(name=checklist_name)
                card.checklists.append(checklist)
        checklist.add_checklist_item(title)

    @staticmethod
    def _format_action_item(item: Dict) -> str:
        if not isinstance(item, dict):
            return str(item)
        task = (item.get("task") or "").strip()
        deadline = (item.get("deadline") or "").strip()
        return f"{task} — {deadline}" if deadline else task

    def _build_archive_comment(self, preview: Dict, recommendation: Dict, event_meta: Dict) -> str:
        lines = [
            f"📋 [{recommendation.get('card_name', '아카이빙')} 채널 아카이빙]",
            f"채널: {event_meta.get('channel_name', preview.get('channel', 'unknown'))}  |  작성자: {event_meta.get('author', '알 수 없음')}  |  {event_meta.get('event_ts', preview.get('message_ts', ''))}",
            "──────────────────────────────────",
            (preview.get("message_text") or "").strip(),
        ]
        if preview.get("action_items"):
            lines.append("")
            lines.append("⚡ 액션아이템")
            for item in preview.get("action_items", [])[:3]:
                lines.append(f"• {self._format_action_item(item)}")
        if event_meta.get("slack_link"):
            lines.extend(["──────────────────────────────────", f"🔗 Slack 원문 링크: {event_meta['slack_link']}"])
        return "\n".join(lines)

    @staticmethod
    def _build_archive_checklist_name(recommendation: Dict, event_meta: Dict) -> str:
        source = recommendation.get("card_name") or "Slack 아카이빙"
        timestamp = event_meta.get("event_ts", "")
        return f"⚡ 액션아이템 (출처: {source} {timestamp})".strip()


class _DummyChecklist:
    def __init__(self, name: str = "Action Items"):
        self.name = name
        self.items = []

    def add_checklist_item(self, title, due=None):
        self.items.append({"name": title, "state": "incomplete"})


class _DummyCard:
    def __init__(self, name: str, url: Optional[str] = None):
        self.name = name
        self.id = f"dry-run-{name}"
        self.url = url or "dry-run://trello-card"
        self.checklists = [_DummyChecklist()]
        self.comments = []

    def add_checklist(self, name, items):
        checklist = _DummyChecklist(name=name)
        self.checklists.append(checklist)
        return checklist

    def comment(self, text):
        self.comments.append({"data": {"text": text}, "memberCreator": {"fullName": "Meetagain"}})
