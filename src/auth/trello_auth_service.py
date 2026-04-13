"""
Trello 사용자 승인 토큰 관리
"""

from typing import Dict, Optional
from urllib.parse import urlencode

import requests

from src.auth.token_store import TokenStore
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TrelloAuthService:
    AUTHORIZE_ENDPOINT = "https://trello.com/1/authorize"
    MEMBER_ENDPOINT = "https://api.trello.com/1/members/me"

    def __init__(self, owner_id: Optional[str] = None, token_store: Optional[TokenStore] = None):
        self.owner_id = owner_id or Config.TRELLO_OAUTH_OWNER
        self.token_store = token_store or TokenStore()

    def is_enabled(self) -> bool:
        return Config.ENABLE_TRELLO_OAUTH

    def is_configured(self) -> bool:
        return bool(Config.TRELLO_OAUTH_APP_KEY)

    def get_token_record(self) -> Optional[Dict]:
        return self.token_store.get_token("trello", self.owner_id)

    def get_token(self) -> Optional[str]:
        record = self.get_token_record() or {}
        return record.get("token")

    def build_authorization_url(self) -> str:
        query = urlencode(
            {
                "key": Config.TRELLO_OAUTH_APP_KEY,
                "name": Config.TRELLO_OAUTH_APP_NAME,
                "scope": Config.TRELLO_OAUTH_SCOPE,
                "expiration": Config.TRELLO_OAUTH_EXPIRATION,
                "response_type": "token",
                "return_url": Config.TRELLO_OAUTH_RETURN_URL,
            }
        )
        return f"{self.AUTHORIZE_ENDPOINT}?{query}"

    def connect_token(self, token: str) -> Dict:
        member = self._fetch_member(token)
        record = {
            "token": token,
            "member_id": member.get("id", ""),
            "member_username": member.get("username", ""),
            "member_full_name": member.get("fullName", ""),
            "scope": [item.strip() for item in Config.TRELLO_OAUTH_SCOPE.split(",") if item.strip()],
            "metadata": {"url": member.get("url", "")},
        }
        return self.token_store.save_token("trello", self.owner_id, record)

    def get_status(self) -> Dict:
        record = self.get_token_record() or {}
        connected = bool(record.get("token"))
        return {
            "enabled": self.is_enabled(),
            "configured": self.is_configured(),
            "connected": connected,
            "owner_id": self.owner_id,
            "member_id": record.get("member_id"),
            "member_username": record.get("member_username"),
            "member_full_name": record.get("member_full_name"),
            "scopes": record.get("scope", []),
        }

    def _fetch_member(self, token: str) -> Dict:
        response = requests.get(
            self.MEMBER_ENDPOINT,
            params={"key": Config.TRELLO_OAUTH_APP_KEY, "token": token},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

