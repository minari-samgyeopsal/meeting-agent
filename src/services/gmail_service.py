"""
Gmail 서비스 (gws CLI 기반)

사용 가능한 메서드:
- search_emails: Gmail에서 이메일 검색 (FR-B06-2)
- get_recent_emails: 최근 이메일 조회 (FR-B06-2)
"""

import json
import subprocess
from typing import List, Dict

import requests

from src.auth.google_auth_service import GoogleAuthService
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class GmailService:
    """Gmail 조작"""
    
    def __init__(self):
        self.cmd_prefix = [Config.gws_bin(), "gmail"]
        self.google_auth_svc = GoogleAuthService()
    
    def search_emails(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        Gmail에서 이메일 검색 (FR-B06-2)
        
        Args:
            query: 검색 쿼리 (예: "from:john@acme.com")
            max_results: 최대 결과 개수
        
        Returns:
            이메일 메타데이터 리스트
        """
        try:
            oauth_emails = self._search_emails_via_google_oauth(query, max_results)
            if oauth_emails is not None:
                return oauth_emails

            cmd = self.cmd_prefix + [
                "users",
                "messages",
                "list",
                "--params",
                json.dumps(
                    {
                        "userId": "me",
                        "q": query,
                        "maxResults": max_results,
                    },
                    ensure_ascii=False,
                ),
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, env=Config.build_subprocess_env())
            
            if result.returncode != 0:
                logger.warning(f"Gmail search failed: {result.stderr}")
                return []
            
            payload = json.loads(result.stdout)
            emails = payload.get("messages", []) if isinstance(payload, dict) else payload
            logger.debug(f"Found {len(emails)} emails for query: {query}")
            return emails
        
        except Exception as e:
            logger.error(f"Error searching emails: {e}")
            return []

    def _search_emails_via_google_oauth(self, query: str, max_results: int) -> List[Dict]:
        try:
            access_token = self.google_auth_svc.get_valid_access_token()
            if not access_token:
                return None

            response = requests.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"q": query, "maxResults": max_results},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            emails = payload.get("messages", []) if isinstance(payload, dict) else []
            logger.debug(f"Found {len(emails)} emails for query via Google OAuth: {query}")
            return emails
        except Exception as e:
            logger.warning(f"Gmail OAuth search failed, falling back to gws: {e}")
            return None
    
    def get_recent_emails(self, sender_email: str, days: int = 90, limit: int = 3) -> List[Dict]:
        """
        특정 발신자로부터 최근 이메일 조회 (FR-B06-2)
        
        Args:
            sender_email: 발신자 이메일
            days: 조회 기간 (일)
            limit: 최대 개수
        
        Returns:
            이메일 메타데이터 리스트
        """
        try:
            # 기본 쿼리
            query = f"from:{sender_email}"
            
            # 기간 추가
            if days > 0:
                from datetime import datetime, timedelta
                since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                query += f" after:{since_date}"
            
            emails = self.search_emails(query, max_results=limit)
            logger.info(f"Got {len(emails)} recent emails from {sender_email}")
            return emails
        
        except Exception as e:
            logger.error(f"Error getting recent emails: {e}")
            return []
