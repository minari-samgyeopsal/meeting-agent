"""
Slack 서비스 (Slack MCP 기반)

사용 가능한 메서드:
- send_message: 메시지 발송 (FR-B07, FR-A04)
- send_dm: DM 발송
- create_draft: Draft 생성 (FR-B07, FR-A04)
- get_user_id: 사용자 ID 조회
- post_thread_reply: 스레드에 답장 (FR-B08)
- build_archive_confirmation_blocks: 채널 모니터 확인용 Block Kit 생성
- build_archive_card_selection_blocks: 카드 후보 선택 UI 생성
- build_archive_registration_result_message: 등록 결과 메시지 생성
- build_channel_monitor_review_queue_message: 일일 리뷰 큐 요약 메시지 생성
- get_message_permalink: Slack 원문 링크 조회
"""

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import Optional, Dict, List
import json
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SlackService:
    """Slack 메시지 발송 및 관리"""
    
    def __init__(self):
        if not Config.SLACK_BOT_TOKEN and not Config.DRY_RUN:
            raise ValueError("SLACK_BOT_TOKEN not set")

        self.client = WebClient(token=Config.SLACK_BOT_TOKEN) if Config.SLACK_BOT_TOKEN else None
    
    def send_message(self, channel: str, text: str, blocks: Optional[List[Dict]] = None,
                    thread_ts: Optional[str] = None) -> Optional[str]:
        """
        채널에 메시지 발송 (FR-B07, FR-A04)
        
        Args:
            channel: 채널명 또는 ID
            text: 메시지 텍스트
            blocks: 블록 형식 메시지 (옵션)
            thread_ts: 스레드 타임스탐프 (옵션)
        
        Returns:
            메시지 타임스탐프 또는 None
        """
        try:
            if Config.DRY_RUN:
                logger.info(f"[DRY RUN] Would send to {channel}: {text[:50]}")
                return "dry-run-ts"
            
            response = self.client.chat_postMessage(
                channel=channel,
                text=text,
                blocks=blocks,
                thread_ts=thread_ts,
            )
            
            logger.info(f"Message sent to {channel}")
            return response.get("ts")
        
        except SlackApiError as e:
            logger.error(f"Slack API error: {e.response['error']}")
            return None
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None
    
    def send_dm(self, user_email: str, text: str, blocks: Optional[List[Dict]] = None) -> Optional[str]:
        """
        사용자에게 DM 발송
        
        Args:
            user_email: 사용자 이메일
            text: 메시지 텍스트
            blocks: 블록 형식 메시지
        
        Returns:
            메시지 타임스탐프 또는 None
        """
        try:
            # 사용자 ID 조회
            if Config.DRY_RUN:
                logger.info(f"[DRY RUN] Would send DM to {user_email}: {text[:50]}")
                return "dry-run-dm-ts"

            user_id = self.get_user_id(user_email)
            if not user_id:
                logger.warning(f"Could not find user ID for {user_email}")
                return None
            
            # DM 채널 열기
            response = self.client.conversations_open(users=[user_id])
            channel_id = response.get("channel", {}).get("id")
            
            if not channel_id:
                logger.error(f"Failed to open DM channel with {user_email}")
                return None
            
            # 메시지 발송
            return self.send_message(channel_id, text, blocks)
        
        except Exception as e:
            logger.error(f"Error sending DM to {user_email}: {e}")
            return None
    
    def create_draft(self, channel: str, text: str, blocks: Optional[List[Dict]] = None) -> Optional[str]:
        """
        Draft 메시지 생성 (자동 발송하지 않음)
        
        Args:
            channel: 채널명 또는 ID
            text: 메시지 텍스트
            blocks: 블록 형식 메시지
        
        Returns:
            Draft 내용 (사용자가 확인 후 발송)
        """
        try:
            # Draft 생성은 실제 Slack API에서 지원하지 않으므로
            # 따로 저장하거나 로깅해서 사용자에게 제시
            logger.info(f"Draft created for {channel}")
            return f"Draft for {channel}:\n{text}"
        
        except Exception as e:
            logger.error(f"Error creating draft: {e}")
            return None
    
    def get_user_id(self, email: str) -> Optional[str]:
        """
        이메일로 사용자 ID 조회
        
        Args:
            email: 이메일 주소
        
        Returns:
            Slack 사용자 ID 또는 None
        """
        try:
            if Config.DRY_RUN:
                local_part = email.split("@", 1)[0].upper() if "@" in email else "DRYRUN"
                return f"DRYRUN_{local_part}"

            if not self.client:
                return None

            response = self.client.users_lookupByEmail(email=email)
            return response.get("user", {}).get("id")
        
        except SlackApiError as e:
            if e.response['error'] != "users_not_found":
                logger.warning(f"Could not find user with email {email}")
            return None
        except Exception as e:
            logger.error(f"Error looking up user: {e}")
            return None

    def get_message_permalink(self, channel: str, message_ts: str) -> str:
        """Slack 원문 permalink 조회"""
        try:
            if not channel or not message_ts:
                return ""
            if Config.DRY_RUN:
                return f"https://slack.local/archives/{channel}/p{message_ts.replace('.', '')}"
            if not self.client:
                return ""
            response = self.client.chat_getPermalink(channel=channel, message_ts=message_ts)
            return response.get("permalink", "")
        except Exception as e:
            logger.error(f"Error getting Slack permalink: {e}")
            return ""

    def fetch_conversation_history(
        self,
        channel: str,
        oldest_ts: str,
        latest_ts: str,
        limit: int = 200,
    ) -> List[Dict]:
        """지정 시간 창의 채널 메시지 조회"""
        try:
            if Config.DRY_RUN:
                logger.info(
                    f"[DRY RUN] Would fetch history: channel={channel} oldest={oldest_ts} latest={latest_ts} limit={limit}"
                )
                return []
            if not self.client:
                return []
            response = self.client.conversations_history(
                channel=channel,
                oldest=oldest_ts,
                latest=latest_ts,
                inclusive=False,
                limit=limit,
            )
            return response.get("messages", []) or []
        except Exception as e:
            logger.error(f"Error fetching conversation history for {channel}: {e}")
            return []
    
    def post_thread_reply(self, channel: str, thread_ts: str, text: str,
                         blocks: Optional[List[Dict]] = None) -> Optional[str]:
        """
        스레드에 답장 (FR-B08)
        
        Args:
            channel: 채널명 또는 ID
            thread_ts: 부모 메시지 타임스탐프
            text: 메시지 텍스트
            blocks: 블록 형식 메시지
        
        Returns:
            메시지 타임스탐프 또는 None
        """
        return self.send_message(channel, text, blocks, thread_ts=thread_ts)
    
    def react_with_emoji(self, channel: str, timestamp: str, emoji: str) -> bool:
        """
        이모지로 반응
        
        Args:
            channel: 채널명 또는 ID
            timestamp: 메시지 타임스탐프
            emoji: 이모지명 (콜론 제외)
        
        Returns:
            성공 여부
        """
        try:
            if Config.DRY_RUN:
                logger.info(f"[DRY RUN] Would react with :{emoji}:")
                return True
            
            self.client.reactions_add(
                channel=channel,
                timestamp=timestamp,
                name=emoji,
            )
            
            logger.debug(f"Reacted with :{emoji}:")
            return True
        
        except Exception as e:
            logger.error(f"Error reacting with emoji: {e}")
            return False

    def build_archive_confirmation_blocks(
        self,
        event: Dict,
        recommendation: Dict,
        action_items: List[Dict],
        preview: Dict,
        event_meta: Optional[Dict] = None,
    ) -> Dict:
        """채널 모니터 확인용 Block Kit payload 생성"""
        event_meta = event_meta or {}
        event_title = (event.get("text") or "").strip().splitlines()[0][:80] or "Slack 메시지"
        channel_name = event_meta.get("channel_name") or event.get("channel_name") or f"#{event.get('channel', 'unknown')}"
        author = event_meta.get("author") or (
            ((event.get("user_profile") or {}).get("real_name"))
            or ((event.get("user_profile") or {}).get("display_name"))
            or event.get("user")
            or "알 수 없음"
        )
        event_ts = event_meta.get("event_ts") or event.get("ts") or ""
        action_lines = (
            "\n".join(f"• {item['task']} — {item['deadline']}" for item in action_items[:3])
            if action_items
            else "• 추출된 액션아이템이 없습니다."
        )
        archive_how = (
            f"원문은 카드 코멘트로 저장되고, 액션아이템 {len(action_items[:3])}개는 체크리스트에 들어갑니다."
            if action_items
            else "원문은 카드 코멘트로 저장되고, 별도 체크리스트는 추가되지 않습니다."
        )
        preview_text = (preview.get("message_text") or "").strip()
        preview_lines = [line.strip() for line in preview_text.splitlines() if line.strip()]
        preview_excerpt = "\n".join(f"> {line}" for line in preview_lines[:5]) if preview_lines else "> 원문 없음"
        recommendation_label = (
            f"{recommendation.get('board', '사용자 선택')} › {recommendation.get('card_name', '사용자 선택 필요')}"
        )
        button_value = json.dumps(
            {
                "recommendation": recommendation,
                "preview": preview,
                "event_meta": event_meta,
            },
            ensure_ascii=False,
        )
        text = (
            "🤖 Meetagain 아카이빙 제안\n\n"
            f"📋 추천 카드: {recommendation_label}\n"
            f"✍️ 원작성자: {author} | {channel_name} | {event_ts}\n\n"
            "⚡ 핵심 액션아이템\n"
            f"{action_lines}"
        )
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*🤖 Meetagain 아카이빙 제안*"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*📋 추천 카드:* {recommendation_label}\n"
                        f"*✍️ 원작성자:* {author}  |  {channel_name}  |  {event_ts}\n"
                        f"*📝 메시지:* {event_title}\n"
                        f"*📥 Trello 저장 방식:* {archive_how}"
                    ),
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*⚡ 핵심 액션아이템*\n{action_lines}"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*📦 Trello에 이렇게 저장됩니다*\n"
                        "아래 원문이 카드 코멘트 본문으로 들어갑니다.\n"
                        f"{preview_excerpt}"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "등록"},
                        "style": "primary",
                        "action_id": "archive_register",
                        "value": button_value,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "카드 변경"},
                        "action_id": "archive_change_card",
                        "value": button_value,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "건너뜀"},
                        "action_id": "archive_skip",
                        "value": button_value,
                    },
                ],
            },
        ]
        return {"text": text, "blocks": blocks}

    def build_archive_card_selection_blocks(
        self,
        recommendation: Dict,
        preview: Dict,
        event_meta: Optional[Dict] = None,
    ) -> Dict:
        """카드 후보 선택용 Block Kit payload 생성"""
        event_meta = event_meta or {}
        candidates = preview.get("candidate_cards") or []
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "*🔄 카드 변경 후보*"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"현재 추천: {recommendation.get('board', '사용자 선택')} › {recommendation.get('card_name', '미정')}"
                    ),
                },
            },
        ]
        if candidates:
            options = []
            for card in candidates[:10]:
                options.append(
                    {
                        "text": {
                            "type": "plain_text",
                            "text": f"{card.get('board', '보드')} › {card.get('card_name', '이름 없음')}"[:75],
                        },
                        "value": json.dumps(
                            {
                                "recommendation": card,
                                "preview": preview,
                                "event_meta": event_meta,
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join(
                            f"• {card.get('board', '보드')} › {card.get('card_name', '이름 없음')}"
                            for card in candidates[:5]
                        ),
                    },
                    "accessory": {
                        "type": "static_select",
                        "action_id": "archive_select_card",
                        "placeholder": {"type": "plain_text", "text": "등록할 카드를 선택하세요"},
                        "options": options,
                    },
                }
            )
        return {"text": "추천 카드 변경", "blocks": blocks}

    def build_archive_registration_result_message(self, result: Dict) -> Dict:
        """등록 결과 메시지 생성"""
        if result.get("ok"):
            text = (
                "✅ Trello 등록 완료\n"
                f"- 카드: {result.get('card_name', '알 수 없음')}\n"
                f"- 액션아이템: {result.get('action_item_count', 0)}개\n"
                f"- 링크: {result.get('card_url', '링크 없음')}"
            )
        else:
            text = f"❌ Trello 등록 실패\n- 사유: {result.get('message', '알 수 없는 오류')}"
        return {"text": text, "replace_original": False, "response_type": "ephemeral"}

    def build_channel_monitor_review_queue_message(self, report: Dict) -> Dict:
        """일일 채널 모니터 리뷰 요약 메시지 생성"""
        channels = report.get("channels", []) or []
        proposals = report.get("proposals", []) or []
        review_candidates = report.get("review_candidates", []) or []
        window_start = self._format_datetime_label(report.get("window_start", ""))
        window_end = self._format_datetime_label(report.get("window_end", ""))

        summary_text = (
            "📥 Meetagain 일일 정리 후보\n"
            f"- 확인 기간: {window_start} ~ {window_end}\n"
            f"- 확인한 채널: {', '.join(channels) or '없음'}\n"
            f"- 바로 정리할 항목: {report.get('proposal_count', 0)}건\n"
            f"- 한 번 더 볼 항목: {report.get('review_candidate_count', 0)}건"
        )

        blocks: List[Dict] = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*📥 Meetagain 일일 정리 후보*"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*확인 기간:* {window_start} ~ {window_end}\n"
                        f"*확인한 채널:* {', '.join(channels) or '없음'}\n"
                        f"*읽은 메시지:* {report.get('scanned_count', 0)}건\n"
                        f"*바로 정리할 항목:* {report.get('proposal_count', 0)}건\n"
                        f"*한 번 더 볼 항목:* {report.get('review_candidate_count', 0)}건"
                    ),
                },
            },
        ]

        if proposals:
            proposal_lines = []
            for item in proposals[:5]:
                headline = self._clean_review_headline((item.get("text", "") or "").splitlines()[-1] or "정리 후보")
                proposal_lines.append(
                    f"• [{item.get('channel', '')}] {headline}"
                )
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*바로 정리해도 될 항목*\n" + "\n".join(proposal_lines),
                    },
                }
            )

        if review_candidates:
            review_lines = []
            for item in review_candidates[:10]:
                reasons = self._humanize_review_reasons(item.get("reasons", []))
                link_text = f" <{item.get('slack_link')}|원문 보기>" if item.get("slack_link") else ""
                review_lines.append(
                    f"• [{item.get('channel', '')}] {item.get('headline', '')}{link_text}\n"
                    f"  살펴볼 이유: {reasons}"
                )
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*한 번 더 보면 좋을 항목*\n" + "\n".join(review_lines),
                    },
                }
            )
        else:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "이번 기간에는 추가로 살펴볼 항목이 없습니다."},
                }
            )

        return {"text": summary_text, "blocks": blocks}

    @staticmethod
    def _format_datetime_label(value: str) -> str:
        try:
            if not value:
                return ""
            return value.replace("T", " ")[:16]
        except Exception:
            return value

    @staticmethod
    def _clean_review_headline(value: str) -> str:
        cleaned = (value or "").replace("🤖 Meetagain 아카이빙 제안", "").strip()
        return cleaned or "정리 후보"

    @staticmethod
    def _humanize_review_reasons(reasons: List[str]) -> str:
        reason_map = {
            "회의/후속 키워드": "미팅 후속 논의일 가능성이 있습니다",
            "외부 협업/법률 맥락": "외부 파트너나 검토 이슈가 포함돼 있습니다",
            "bullet 형식": "정리 메모 형태로 작성돼 있습니다",
            "의사결정/후속 표현": "결정이나 다음 단계가 언급됐습니다",
            "구체 실행/리스크 키워드": "실행 과제나 리스크 검토가 보입니다",
        }
        readable = [reason_map.get(reason, reason) for reason in reasons[:3]]
        return ", ".join(readable) or "내용을 한 번 더 확인해보면 좋습니다"
