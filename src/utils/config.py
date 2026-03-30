"""
환경 설정 및 설정 값 로딩

.env 파일에서 설정을 읽어 Application 전체에서 사용합니다.
"""

import os
import json
import shutil
from typing import Optional
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()


class Config:
    """애플리케이션 설정"""
    
    # ============ Google Workspace ============
    GWS_CRED_FILE = os.getenv(
        "GWS_CRED_FILE",
        os.getenv("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE", "/path/to/credentials.json"),
    )
    GWS_BIN = os.getenv("GWS_BIN", shutil.which("gws") or "/Users/minhwankim/.npm-global/bin/gws")
    GWS_DOMAIN = os.getenv("GWS_DOMAIN", "parametacorp.com")
    
    # ============ Slack ============
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
    SLACK_APP_ID = os.getenv("SLACK_APP_ID", "")
    SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN", "")
    
    # ============ Claude API ============
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    
    # ============ Trello ============
    TRELLO_API_KEY = os.getenv("TRELLO_API_KEY", "")
    TRELLO_API_TOKEN = os.getenv("TRELLO_API_TOKEN", "")
    TRELLO_BOARD_ID = os.getenv("TRELLO_BOARD_ID", "69731ce5")
    
    # ============ Web Search ============
    SEARCH_RESULTS_COUNT = int(os.getenv("SEARCH_RESULTS_COUNT", "5"))
    
    # ============ Application ============
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    CACHE_DIR = os.getenv("CACHE_DIR", "./cache")
    DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
    DRY_RUN_CALENDAR = os.getenv("DRY_RUN_CALENDAR", os.getenv("DRY_RUN", "false")).lower() == "true"
    DRY_RUN_TRELLO = os.getenv("DRY_RUN_TRELLO", os.getenv("DRY_RUN", "false")).lower() == "true"
    ALLOW_TRANSCRIPT_FALLBACK = os.getenv("ALLOW_TRANSCRIPT_FALLBACK", "false").lower() == "true"
    
    # ============ Calendar Settings ============
    TIMEZONE = os.getenv("TIMEZONE", "Asia/Seoul")
    BRIEFING_HOUR = int(os.getenv("BRIEFING_HOUR", "9"))
    BRIEFING_MINUTE = int(os.getenv("BRIEFING_MINUTE", "0"))
    
    # ============ Contacts (Drive) ============
    CONTACTS_FOLDER = os.getenv("CONTACTS_FOLDER", "Contacts")
    COMPANY_KNOWLEDGE_FILE = os.getenv("COMPANY_KNOWLEDGE_FILE", "company_knowledge.md")
    MEETING_TRANSCRIPTS_FOLDER = os.getenv("MEETING_TRANSCRIPTS_FOLDER", "MeetingTranscripts")
    MEETING_NOTES_FOLDER = os.getenv("MEETING_NOTES_FOLDER", "MeetingNotes")
    GENERATED_DRAFTS_FOLDER = os.getenv("GENERATED_DRAFTS_FOLDER", "GeneratedDrafts")
    MEETING_STATE_FOLDER = os.getenv("MEETING_STATE_FOLDER", "MeetingState")
    
    # ============ Feature Flags ============
    ENABLE_AGENDA_AUTO_REGISTER = os.getenv("ENABLE_AGENDA_AUTO_REGISTER", "true").lower() == "true"
    ENABLE_CONTACT_AUTO_SAVE = os.getenv("ENABLE_CONTACT_AUTO_SAVE", "true").lower() == "true"
    ENABLE_CALENDAR_AGENDA_SYNC = os.getenv("ENABLE_CALENDAR_AGENDA_SYNC", "true").lower() == "true"
    
    # ============ 내부 도메인 ============
    INTERNAL_DOMAINS = {"parametacorp.com", "iconloop.com"}
    
    @classmethod
    def validate(cls, required_names=None) -> bool:
        """필수 설정 값 검증"""
        value_map = {
            "SLACK_BOT_TOKEN": cls.SLACK_BOT_TOKEN,
            "SLACK_SIGNING_SECRET": cls.SLACK_SIGNING_SECRET,
            "SLACK_APP_ID": cls.SLACK_APP_ID,
            "SLACK_APP_TOKEN": cls.SLACK_APP_TOKEN,
            "ANTHROPIC_API_KEY": cls.ANTHROPIC_API_KEY,
            "TRELLO_API_KEY": cls.TRELLO_API_KEY,
            "TRELLO_API_TOKEN": cls.TRELLO_API_TOKEN,
        }

        if required_names is None:
            required_names = [
                "SLACK_BOT_TOKEN",
                "SLACK_SIGNING_SECRET",
                "ANTHROPIC_API_KEY",
            ]

        optional_in_dry_run = {
            "ANTHROPIC_API_KEY",
            "SLACK_BOT_TOKEN",
            "SLACK_SIGNING_SECRET",
            "SLACK_APP_ID",
            "SLACK_APP_TOKEN",
            "TRELLO_API_KEY",
            "TRELLO_API_TOKEN",
        }

        missing = []
        for name in required_names:
            if cls.DRY_RUN and name in optional_in_dry_run:
                continue
            if not value_map.get(name):
                missing.append(name)

        if missing:
            print(f"❌ Missing required env vars: {', '.join(missing)}")
            return False

        return True
    
    @classmethod
    def is_internal_email(cls, email: str) -> bool:
        """내부 이메일 확인"""
        domain = email.split("@")[1] if "@" in email else ""
        return domain in cls.INTERNAL_DOMAINS
    
    @classmethod
    def ensure_cache_dir(cls):
        """캐시 디렉토리 생성"""
        os.makedirs(cls.CACHE_DIR, exist_ok=True)

    @classmethod
    def build_subprocess_env(cls):
        """subprocess 실행용 환경 변수 구성"""
        env = os.environ.copy()
        explicit_credentials = env.get("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE")
        candidate = explicit_credentials or cls.GWS_CRED_FILE
        default_config_dir = os.path.expanduser("~/.config/gws")
        default_authorized_user = os.path.join(default_config_dir, "credentials.json")

        if candidate and cls._looks_like_oauth_client_config(candidate):
            env.pop("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE", None)
            env.pop("GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND", None)
        elif candidate and os.path.abspath(candidate) == os.path.abspath(default_authorized_user):
            # gws 기본 인증 저장소는 자체적으로 읽게 두고, 잘못된 client secret override를 피한다.
            env.pop("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE", None)
            env.pop("GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND", None)
        elif candidate and candidate != "/path/to/credentials.json":
            env["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"] = candidate
            env["GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND"] = "file"
        else:
            env.pop("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE", None)
            env.pop("GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND", None)

        return env

    @classmethod
    def gws_bin(cls) -> str:
        """gws 실행 파일 경로 반환"""
        return cls.GWS_BIN

    @staticmethod
    def _looks_like_oauth_client_config(path: str) -> bool:
        """OAuth client config(client_secret.json)인지 대략 판별"""
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            return isinstance(data, dict) and ("installed" in data or "web" in data)
        except Exception:
            return False
