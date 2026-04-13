"""
Google OAuth 인증 및 토큰 갱신
"""

import secrets
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from src.auth.token_store import TokenStore
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class GoogleAuthService:
    AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

    def __init__(self, owner_id: Optional[str] = None, token_store: Optional[TokenStore] = None):
        self.owner_id = owner_id or Config.GOOGLE_OAUTH_OWNER
        self.token_store = token_store or TokenStore()

    def is_enabled(self) -> bool:
        return Config.ENABLE_GOOGLE_OAUTH

    def is_configured(self) -> bool:
        return bool(
            Config.GOOGLE_OAUTH_CLIENT_ID
            and Config.GOOGLE_OAUTH_CLIENT_SECRET
            and Config.GOOGLE_OAUTH_REDIRECT_URI
        )

    def get_token_record(self) -> Optional[Dict]:
        return self.token_store.get_token("google", self.owner_id)

    def build_authorization_url(self, state: Optional[str] = None) -> str:
        state = state or secrets.token_urlsafe(24)
        query = urlencode(
            {
                "client_id": Config.GOOGLE_OAUTH_CLIENT_ID,
                "redirect_uri": Config.GOOGLE_OAUTH_REDIRECT_URI,
                "response_type": "code",
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "scope": " ".join(Config.GOOGLE_OAUTH_SCOPES),
                "state": state,
            }
        )
        return f"{self.AUTH_ENDPOINT}?{query}"

    def exchange_code_for_token(self, code: str) -> Dict:
        response = requests.post(
            self.TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": Config.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": Config.GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": Config.GOOGLE_OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        record = self._build_record(payload, existing=self.get_token_record())
        return self.token_store.save_token("google", self.owner_id, record)

    def refresh_access_token(self, refresh_token: Optional[str] = None) -> Optional[Dict]:
        existing = self.get_token_record() or {}
        refresh_token = refresh_token or existing.get("refresh_token")
        if not refresh_token:
            return None

        response = requests.post(
            self.TOKEN_ENDPOINT,
            data={
                "refresh_token": refresh_token,
                "client_id": Config.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": Config.GOOGLE_OAUTH_CLIENT_SECRET,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        record = self._build_record(payload, existing=existing)
        return self.token_store.save_token("google", self.owner_id, record)

    def get_valid_access_token(self) -> Optional[str]:
        if not (self.is_enabled() and self.is_configured()):
            return None

        record = self.get_token_record()
        if not record:
            return None

        expires_at = self._parse_expires_at(record.get("expires_at"))
        if record.get("access_token") and expires_at and expires_at > datetime.now(timezone.utc) + timedelta(seconds=60):
            return record.get("access_token")

        try:
            refreshed = self.refresh_access_token(record.get("refresh_token"))
        except Exception as e:
            logger.error(f"Failed to refresh Google OAuth token: {e}")
            return None
        return (refreshed or {}).get("access_token")

    def get_status(self) -> Dict:
        record = self.get_token_record() or {}
        return {
            "enabled": self.is_enabled(),
            "configured": self.is_configured(),
            "connected": bool(record),
            "owner_id": self.owner_id,
            "expires_at": record.get("expires_at"),
            "scopes": record.get("scope", []),
            "email": (record.get("metadata") or {}).get("email"),
        }

    def run_local_login(self, open_browser: bool = True, timeout: int = 180) -> Dict:
        parsed = urlparse(Config.GOOGLE_OAUTH_REDIRECT_URI)
        if parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.port:
            raise ValueError("GOOGLE_OAUTH_REDIRECT_URI must use localhost or 127.0.0.1 with an explicit port")

        state = secrets.token_urlsafe(24)
        auth_url = self.build_authorization_url(state=state)
        callback_payload: Dict[str, str] = {}
        callback_event = threading.Event()

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = parse_qs(urlparse(self.path).query)
                callback_payload["code"] = (query.get("code") or [""])[0]
                callback_payload["state"] = (query.get("state") or [""])[0]
                callback_payload["error"] = (query.get("error") or [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h3>Google OAuth completed.</h3><p>Return to the terminal.</p></body></html>"
                )
                callback_event.set()

            def log_message(self, format, *args):
                return

        server = HTTPServer((parsed.hostname, parsed.port), CallbackHandler)
        server.timeout = 1

        def _serve():
            deadline = time.time() + timeout
            while time.time() < deadline and not callback_event.is_set():
                server.handle_request()

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()

        if open_browser:
            webbrowser.open(auth_url)

        logger.info(f"Open Google OAuth URL: {auth_url}")
        thread.join(timeout + 2)
        server.server_close()

        if callback_payload.get("error"):
            raise RuntimeError(f"Google OAuth error: {callback_payload['error']}")
        if callback_payload.get("state") != state:
            raise RuntimeError("Google OAuth state mismatch")
        if not callback_payload.get("code"):
            raise TimeoutError("Google OAuth callback timed out")

        record = self.exchange_code_for_token(callback_payload["code"])
        return {
            "ok": True,
            "owner_id": self.owner_id,
            "expires_at": record.get("expires_at"),
            "email": (record.get("metadata") or {}).get("email"),
        }

    def _build_record(self, payload: Dict, existing: Optional[Dict] = None) -> Dict:
        existing = existing or {}
        access_token = payload.get("access_token") or existing.get("access_token")
        refresh_token = payload.get("refresh_token") or existing.get("refresh_token")
        expires_in = int(payload.get("expires_in", 3600))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        metadata = dict(existing.get("metadata") or {})

        if access_token:
            userinfo = self._fetch_userinfo(access_token)
            if userinfo.get("email"):
                metadata["email"] = userinfo.get("email")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": payload.get("token_type") or existing.get("token_type") or "Bearer",
            "expires_at": expires_at.isoformat(),
            "scope": self._normalize_scopes(payload.get("scope") or existing.get("scope") or Config.GOOGLE_OAUTH_SCOPES),
            "metadata": metadata,
        }

    def _fetch_userinfo(self, access_token: str) -> Dict:
        try:
            response = requests.get(
                self.USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Failed to fetch Google userinfo: {e}")
            return {}

    @staticmethod
    def _normalize_scopes(scopes) -> list:
        if isinstance(scopes, list):
            return scopes
        if isinstance(scopes, str):
            return [item for item in scopes.split() if item]
        return []

    @staticmethod
    def _parse_expires_at(value: Optional[str]) -> Optional[datetime]:
        try:
            if not value:
                return None
            return datetime.fromisoformat(value)
        except Exception:
            return None

