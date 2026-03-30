"""
Slack 서비스 (Slack MCP 기반)

사용 가능한 메서드:
- send_message: 메시지 발송 (FR-B07, FR-A04)
- send_dm: DM 발송
- create_draft: Draft 생성 (FR-B07, FR-A04)
- get_user_id: 사용자 ID 조회
- post_thread_reply: 스레드에 답장 (FR-B08)
"""

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import Optional, Dict, List
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
