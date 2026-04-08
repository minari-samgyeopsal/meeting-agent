"""
Channel Monitor Agent - Slack 채널 아카이빙 제안 에이전트

역할:
- 채널 일반 메시지 감시
- 아카이빙 가치 판단
- Trello 카드 추천
- 액션아이템 추출
- Slack 확인용 Block Kit payload 생성
"""

import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from anthropic import Anthropic

from src.services.slack_service import SlackService
from src.services.trello_service import TrelloService
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ChannelMonitorAgent:
    """Slack 채널 메시지 기반 아카이빙 제안 에이전트"""

    ARCHIVE_KEYWORDS = [
        "미팅",
        "회의",
        "회의록",
        "정리",
        "결론",
        "결정",
        "의사결정",
        "파트너",
        "거래처",
        "법률",
        "리스크",
        "검토",
        "후속",
        "액션아이템",
        "다음 단계",
        "요청",
        "합의",
    ]

    ACTION_PATTERNS = [
        re.compile(r"(필요|요청|진행|검토|공유|발송|정리|조사|제작|준비|확인|만들|줘야)"),
        re.compile(r"(이번 주|다음 주|오늘|내일|전까지|까지|ASAP|긴급|우선)"),
    ]
    AUTO_ARCHIVE_THRESHOLD = 3
    REVIEW_CANDIDATE_THRESHOLD = 1

    def __init__(self):
        self.slack_svc = SlackService()
        self.trello_svc = TrelloService()
        self.claude_client = Anthropic() if Config.ANTHROPIC_API_KEY else None

    async def handle_channel_message(self, event: dict, client=None, say=None) -> Optional[Dict]:
        """채널 일반 메시지를 처리하고 확인용 payload를 반환"""
        if not self.should_process_event(event):
            return None

        text = (event.get("text") or "").strip()
        if not await self.should_archive(text):
            return None

        cards = self.trello_svc.list_cards_by_board_scope(message=text)
        recommendation = await self.recommend_trello_card(text, cards)
        action_items = await self.extract_action_items(text)
        preview = self.trello_svc.build_archive_registration_preview(
            message_text=text,
            recommendation=recommendation,
            action_items=action_items,
            event=event,
        )
        slack_link = event.get("permalink") or self.slack_svc.get_message_permalink(
            event.get("channel", ""),
            event.get("ts", ""),
        )
        event_meta = {
            "author": (
                ((event.get("user_profile") or {}).get("real_name"))
                or ((event.get("user_profile") or {}).get("display_name"))
                or event.get("user")
                or "알 수 없음"
            ),
            "channel_name": self._resolve_channel_label(event),
            "event_ts": event.get("ts") or "",
            "slack_link": slack_link,
        }
        payload = self.slack_svc.build_archive_confirmation_blocks(
            event=event,
            recommendation=recommendation,
            action_items=action_items,
            preview=preview,
            event_meta=event_meta,
        )
        payload["thread_ts"] = event.get("ts")
        return payload

    async def handle_archive_action(self, ack, body, client, respond=None) -> Dict:
        """확인 버튼 인터랙션 처리 - v1에서는 dry-run preview만 반환"""
        if ack:
            ack()

        action_payload = (body.get("actions") or [{}])[0]
        action = action_payload.get("action_id", "")
        raw_value = action_payload.get("value", "{}")
        if action == "archive_select_card":
            raw_value = ((action_payload.get("selected_option") or {}).get("value")) or raw_value
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            payload = {}

        if action == "archive_skip":
            response = {
                "text": "알겠습니다. 이번 메시지는 아카이빙하지 않겠습니다.",
                "replace_original": False,
                "response_type": "ephemeral",
            }
        elif action == "archive_change_card":
            response = self.slack_svc.build_archive_card_selection_blocks(
                recommendation=payload.get("recommendation") or {},
                preview=payload.get("preview") or {},
                event_meta=payload.get("event_meta") or {},
            )
            response["replace_original"] = False
            response["response_type"] = "ephemeral"
        else:
            result = self.trello_svc.register_archive_entry(payload)
            response = self.slack_svc.build_archive_registration_result_message(result)
        if respond:
            respond(response)
        return response

    @classmethod
    def should_process_event(cls, event: dict) -> bool:
        """채널 monitor 대상 이벤트만 통과"""
        if not Config.ENABLE_CHANNEL_MONITOR:
            return False
        if not Config.ENABLE_CHANNEL_MONITOR_REALTIME:
            return False

        subtype = event.get("subtype")
        if subtype in {"bot_message", "message_changed", "message_deleted"}:
            return False

        if event.get("bot_id"):
            return False

        if event.get("channel_type") != "im":
            return False

        if event.get("thread_ts") and event.get("thread_ts") != event.get("ts"):
            return False

        files = event.get("files") or []
        text = (event.get("text") or "").strip()
        if files and not text:
            return False

        if len(text) < Config.CHANNEL_MONITOR_MIN_TEXT_LENGTH:
            return False

        return True

    @staticmethod
    def build_daily_collection_window(
        reference: Optional[datetime] = None,
        batch_hour: Optional[int] = None,
    ) -> tuple:
        tz = ZoneInfo(Config.TIMEZONE)
        batch_hour = Config.CHANNEL_MONITOR_BATCH_HOUR if batch_hour is None else batch_hour
        now = reference.astimezone(tz) if reference else datetime.now(tz)
        cutoff = now.replace(hour=batch_hour, minute=0, second=0, microsecond=0)
        if now < cutoff:
            end = cutoff - timedelta(days=1)
        else:
            end = cutoff
        start = end - timedelta(days=1)
        return start, end

    async def run_daily_collection(
        self,
        channels: List[str],
        reference: Optional[datetime] = None,
    ) -> Dict:
        start, end = self.build_daily_collection_window(reference=reference)
        oldest_ts = f"{start.timestamp():.6f}"
        latest_ts = f"{end.timestamp():.6f}"
        proposals = []
        review_candidates = []
        scanned_count = 0

        for channel in channels:
            messages = self.slack_svc.fetch_conversation_history(channel, oldest_ts, latest_ts)
            for message in messages:
                scanned_count += 1
                event = {
                    "channel_type": "channel",
                    "channel": channel,
                    "channel_name": channel,
                    "user": message.get("user"),
                    "text": message.get("text", ""),
                    "ts": message.get("ts"),
                    "thread_ts": message.get("thread_ts"),
                    "subtype": message.get("subtype"),
                    "bot_id": message.get("bot_id"),
                }
                if not self._is_batch_candidate_event(event):
                    continue
                evaluation = self.evaluate_archive_candidate(event.get("text", ""))
                if evaluation["score"] >= self.REVIEW_CANDIDATE_THRESHOLD:
                    slack_link = self.slack_svc.get_message_permalink(channel, message.get("ts", ""))
                    review_candidates.append(
                        {
                            "channel": channel,
                            "ts": message.get("ts"),
                            "score": evaluation["score"],
                            "reasons": evaluation["reasons"],
                            "headline": (message.get("text", "") or "").splitlines()[0][:120],
                            "slack_link": slack_link,
                        }
                    )
                payload = await self.handle_batch_message(event)
                if payload:
                    proposals.append(
                        {
                            "channel": channel,
                            "ts": message.get("ts"),
                            "text": payload.get("text", ""),
                            "score": evaluation["score"],
                            "reasons": evaluation["reasons"],
                            "blocks": payload.get("blocks", []),
                            "thread_ts": payload.get("thread_ts"),
                        }
                    )

        return {
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "channels": channels,
            "scanned_count": scanned_count,
            "proposal_count": len(proposals),
            "proposals": proposals,
            "review_candidate_count": len(review_candidates),
            "review_candidates": sorted(review_candidates, key=lambda item: item["score"], reverse=True),
        }

    async def handle_batch_message(self, event: dict) -> Optional[Dict]:
        if not self._is_batch_candidate_event(event):
            return None

        text = (event.get("text") or "").strip()
        if not await self.should_archive(text):
            return None

        cards = self.trello_svc.list_cards_by_board_scope(message=text)
        recommendation = await self.recommend_trello_card(text, cards)
        action_items = await self.extract_action_items(text)
        preview = self.trello_svc.build_archive_registration_preview(
            message_text=text,
            recommendation=recommendation,
            action_items=action_items,
            event=event,
        )
        slack_link = event.get("permalink") or self.slack_svc.get_message_permalink(
            event.get("channel", ""),
            event.get("ts", ""),
        )
        event_meta = {
            "author": event.get("user") or "알 수 없음",
            "channel_name": self._resolve_channel_label(event),
            "event_ts": event.get("ts") or "",
            "slack_link": slack_link,
        }
        payload = self.slack_svc.build_archive_confirmation_blocks(
            event=event,
            recommendation=recommendation,
            action_items=action_items,
            preview=preview,
            event_meta=event_meta,
        )
        payload["thread_ts"] = event.get("ts")
        return payload

    @classmethod
    def _is_batch_candidate_event(cls, event: dict) -> bool:
        subtype = event.get("subtype")
        if subtype in {"bot_message", "message_changed", "message_deleted"}:
            return False
        if event.get("bot_id"):
            return False
        if event.get("thread_ts") and event.get("thread_ts") != event.get("ts"):
            return False
        files = event.get("files") or []
        text = (event.get("text") or "").strip()
        if files and not text:
            return False
        return len(text) >= Config.CHANNEL_MONITOR_MIN_TEXT_LENGTH

    @staticmethod
    def _resolve_channel_label(event: dict) -> str:
        channel_type = event.get("channel_type")
        if channel_type == "im":
            return "개인 DM"
        if channel_type == "group":
            return event.get("channel_name") or f"(private){event.get('channel', 'unknown')}"
        return event.get("channel_name") or f"#{event.get('channel', 'unknown')}"

    async def should_archive(self, message: str) -> bool:
        """1단계: 아카이빙 가치 판단"""
        normalized = " ".join((message or "").split())
        if not normalized:
            return False

        if Config.DRY_RUN or not self.claude_client:
            return self.evaluate_archive_candidate(normalized)["score"] >= self.AUTO_ARCHIVE_THRESHOLD

        try:
            response = self.claude_client.messages.create(
                model=Config.ANTHROPIC_MODEL,
                max_tokens=300,
                system=(
                    "당신은 Slack 메시지를 분석하여 비즈니스 아카이빙 가치 여부를 판단하는 AI입니다. "
                    "반드시 JSON만 반환하세요. 형식: "
                    '{"archive": true/false, "reason": "한국어 한 줄 이유"}'
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "아래 메시지가 아카이빙 가치가 있는지 판단하세요.\n"
                            "기준: 외부 미팅 정리, 의사결정, 외부 파트너 반응, 법률/리스크 검토 요청, "
                            "구체적 액션아이템 또는 후속 조치.\n\n"
                            f"메시지:\n{normalized}"
                        ),
                    }
                ],
            )
            text = self._extract_response_text(response)
            parsed = json.loads(text)
            if "archive" not in parsed:
                return self.evaluate_archive_candidate(normalized)["score"] >= self.AUTO_ARCHIVE_THRESHOLD
            return bool(parsed.get("archive"))
        except Exception as e:
            logger.warning(f"Archive judgement fell back to rules: {e}")
            return self.evaluate_archive_candidate(normalized)["score"] >= self.AUTO_ARCHIVE_THRESHOLD

    async def recommend_trello_card(self, message: str, cards: List[Dict]) -> Dict:
        """카드 추천"""
        return self.trello_svc.recommend_card_from_message(message, cards)

    async def extract_action_items(self, message: str) -> List[Dict]:
        """핵심 액션아이템 추출"""
        raw_message = (message or "").strip()
        normalized = " ".join(raw_message.split())
        if not raw_message:
            return []

        if Config.DRY_RUN or not self.claude_client:
            return self._rule_based_action_items(raw_message)

        try:
            response = self.claude_client.messages.create(
                model=Config.ANTHROPIC_MODEL,
                max_tokens=500,
                system=(
                    "당신은 Slack 메시지에서 핵심 액션아이템을 추출하는 AI입니다. "
                    "반드시 JSON만 반환하세요. 형식: "
                    '{"items":[{"task":"...", "deadline":"..."}]}'
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "메시지에서 핵심 액션아이템을 최대 3개까지 추출하세요. "
                            "각 항목은 해야 할 일(task)과 기한 또는 시급도(deadline)를 포함해야 합니다.\n\n"
                            f"메시지:\n{raw_message}"
                        ),
                    }
                ],
            )
            text = self._extract_response_text(response)
            parsed = json.loads(text)
            items = parsed.get("items") or []
            cleaned = []
            for item in items[:3]:
                task = (item.get("task") or "").strip()
                deadline = (item.get("deadline") or "").strip() or "추후 논의"
                if task:
                    cleaned.append({"task": task, "deadline": deadline})
            return cleaned or self._rule_based_action_items(raw_message)
        except Exception as e:
            logger.warning(f"Action item extraction fell back to rules: {e}")
            return self._rule_based_action_items(raw_message)

    def evaluate_archive_candidate(self, message: str) -> Dict:
        score = 0
        reasons = []
        lowered = message.lower()
        if any(keyword in message for keyword in self.ARCHIVE_KEYWORDS):
            score += 1
            reasons.append("회의/후속 키워드")
        if any(token in lowered for token in ["고객", "거래처", "파트너", "법무", "legal", "poc", "mou"]):
            score += 1
            reasons.append("외부 협업/법률 맥락")
        if any(marker in message for marker in ["•", "-", "1.", "2.", "3."]):
            score += 1
            reasons.append("bullet 형식")
        if any(token in lowered for token in ["합의", "결정", "추진", "검토 요청", "다음 단계"]):
            score += 1
            reasons.append("의사결정/후속 표현")
        if any(token in lowered for token in ["ui/ux", "uiux", "법률", "kyc", "vasp", "금토큰", "paxg"]):
            score += 1
            reasons.append("구체 실행/리스크 키워드")
        return {"score": score, "reasons": reasons}

    def _rule_based_action_items(self, message: str) -> List[Dict]:
        candidates: List[Dict] = []
        seen_tasks = set()
        lines = [
            line.strip("•- ").strip()
            for line in re.split(r"[\n\r]+", message)
            if line.strip()
        ]
        if len(lines) == 1:
            lines = [segment.strip() for segment in re.split(r"[.;]", message) if segment.strip()]

        prioritized_lines = sorted(lines, key=self._action_priority_score, reverse=True)

        for line in prioritized_lines:
            compact = line.replace(" ", "")
            if "미팅정리" in compact or "회의정리" in compact:
                continue
            if not any(pattern.search(line) for pattern in self.ACTION_PATTERNS):
                continue
            summary = self._summarize_action_line(line)
            deadline = "담당자 지정 필요"
            if any(token in compact for token in ["이번주", "금주"]):
                deadline = "이번 주 내"
            elif any(token in compact for token in ["다음주", "차주"]):
                deadline = "다음 주 내"
            elif any(token in compact for token in ["오늘", "금일"]):
                deadline = "오늘"
            elif "내일" in compact:
                deadline = "내일"
            elif "전" in line or "까지" in line:
                deadline = "기한 명시됨"
            if summary in seen_tasks:
                continue
            seen_tasks.add(summary)
            candidates.append({"task": summary, "deadline": deadline})
            if len(candidates) >= 3:
                break
        return candidates

    @staticmethod
    def _action_priority_score(line: str) -> int:
        compact = line.replace(" ", "").lower()
        score = 0
        if any(token in compact for token in ["ui/ux", "uiux", "dapp"]):
            score += 5
        if any(token in compact for token in ["법률검토", "legal", "vasp", "증권성", "kyc"]):
            score += 5
        if any(token in compact for token in ["paxg", "금토큰"]):
            score += 4
        if any(token in compact for token in ["조사", "검토", "제작", "발송", "공유", "준비", "요청", "필요", "만들어", "만들"]):
            score += 3
        if "합의" in compact:
            score -= 1
        if "미팅정리" in compact or "회의정리" in compact:
            score -= 5
        return score

    @staticmethod
    def _summarize_action_line(line: str) -> str:
        compact = line.replace(" ", "").lower()

        if any(token in compact for token in ["ui/ux", "uiux", "dappui", "dappui/ux"]) and any(
            token in compact for token in ["추가", "제작", "필요", "만들어", "만들"]
        ):
            if any(token in compact for token in ["미래에셋", "코빗"]):
                return "미래에셋 전용 dApp UI/UX 추가 제작"
            return "전용 dApp UI/UX 추가 제작"

        if any(token in compact for token in ["법률검토", "legal", "리스크"]) and any(
            token in compact for token in ["vasp", "증권성", "kyc", "phase", "프로젝트"]
        ):
            return "VASP·증권성·KYC 관련 법률 검토 요청"

        if any(token in compact for token in ["법률검토", "legal"]):
            return "법률 검토 요청"

        if any(token in compact for token in ["paxg", "금토큰"]) and any(
            token in compact for token in ["검토", "조사", "방안", "발행"]
        ):
            return "금토큰 발행 연계 방안 조사"

        if any(token in compact for token in ["제안서", "자료"]) and any(
            token in compact for token in ["발송", "공유", "전달"]
        ):
            return "제안서/자료 발송"

        if len(line) > 60:
            shortened = re.split(r"[,.()]", line)[0].strip()
            return shortened[:60].rstrip()

        return line.strip()

    @staticmethod
    def _extract_response_text(response) -> str:
        content = getattr(response, "content", None) or []
        if not content:
            return "{}"
        chunk = content[0]
        if isinstance(chunk, dict):
            return chunk.get("text", "{}")
        return getattr(chunk, "text", "{}")
