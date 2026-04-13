import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.auth.google_auth_service import GoogleAuthService
from src.auth.token_store import TokenStore
from src.services.calendar_service import CalendarService
from src.services.drive_service import DriveService
from src.services.gmail_service import GmailService
from src.utils.config import Config


class GoogleAuthUnitTest(unittest.TestCase):
    def test_token_store_save_and_get(self):
        with tempfile.TemporaryDirectory(prefix="meetagain-oauth-") as temp_dir:
            store = TokenStore(str(Path(temp_dir) / "tokens.json"))
            store.save_token(
                "google",
                "default",
                {"access_token": "abc", "refresh_token": "ref", "expires_at": "2026-04-09T10:00:00+00:00"},
            )
            record = store.get_token("google", "default")
        self.assertEqual(record["access_token"], "abc")
        self.assertEqual(record["refresh_token"], "ref")

    def test_google_auth_service_builds_authorization_url(self):
        original_client_id = Config.GOOGLE_OAUTH_CLIENT_ID
        original_client_secret = Config.GOOGLE_OAUTH_CLIENT_SECRET
        original_redirect_uri = Config.GOOGLE_OAUTH_REDIRECT_URI
        original_scopes = Config.GOOGLE_OAUTH_SCOPES
        try:
            Config.GOOGLE_OAUTH_CLIENT_ID = "client-id"
            Config.GOOGLE_OAUTH_CLIENT_SECRET = "secret"
            Config.GOOGLE_OAUTH_REDIRECT_URI = "http://127.0.0.1:8787/oauth/google/callback"
            Config.GOOGLE_OAUTH_SCOPES = ["openid", "email", "https://www.googleapis.com/auth/calendar"]
            url = GoogleAuthService().build_authorization_url(state="fixed-state")
        finally:
            Config.GOOGLE_OAUTH_CLIENT_ID = original_client_id
            Config.GOOGLE_OAUTH_CLIENT_SECRET = original_client_secret
            Config.GOOGLE_OAUTH_REDIRECT_URI = original_redirect_uri
            Config.GOOGLE_OAUTH_SCOPES = original_scopes

        self.assertIn("client_id=client-id", url)
        self.assertIn("fixed-state", url)
        self.assertIn("calendar", url)

    def test_calendar_service_uses_google_oauth_before_gws(self):
        original_dry_run = Config.DRY_RUN
        original_dry_run_calendar = Config.DRY_RUN_CALENDAR
        original_google_oauth = Config.ENABLE_GOOGLE_OAUTH
        try:
            Config.DRY_RUN = False
            Config.DRY_RUN_CALENDAR = False
            Config.ENABLE_GOOGLE_OAUTH = True
            service = CalendarService()

            class Response:
                text = '{"items":[]}'

                def raise_for_status(self):
                    return None

                def json(self):
                    return {"items": []}

            with patch.object(service.google_auth_svc, "get_valid_access_token", return_value="oauth-token"), patch(
                "src.services.calendar_service.requests.request", return_value=Response()
            ) as mocked_request, patch("src.services.calendar_service.subprocess.run") as mocked_run:
                meetings = service.get_upcoming_meetings(hours=24)

            self.assertEqual(meetings, [])
            mocked_request.assert_called_once()
            mocked_run.assert_not_called()
        finally:
            Config.DRY_RUN = original_dry_run
            Config.DRY_RUN_CALENDAR = original_dry_run_calendar
            Config.ENABLE_GOOGLE_OAUTH = original_google_oauth

    def test_calendar_service_creates_meeting_via_google_oauth(self):
        original_dry_run = Config.DRY_RUN
        original_dry_run_calendar = Config.DRY_RUN_CALENDAR
        original_google_oauth = Config.ENABLE_GOOGLE_OAUTH
        try:
            Config.DRY_RUN = False
            Config.DRY_RUN_CALENDAR = False
            Config.ENABLE_GOOGLE_OAUTH = True
            service = CalendarService()

            class Response:
                text = (
                    '{"id":"evt-1","summary":"카카오 미팅","start":{"dateTime":"2026-03-30T15:00:00+09:00"},'
                    '"end":{"dateTime":"2026-03-30T16:00:00+09:00"},"organizer":{"email":"owner@parametacorp.com"}}'
                )

                def raise_for_status(self):
                    return None

                def json(self):
                    return {
                        "id": "evt-1",
                        "summary": "카카오 미팅",
                        "start": {"dateTime": "2026-03-30T15:00:00+09:00"},
                        "end": {"dateTime": "2026-03-30T16:00:00+09:00"},
                        "organizer": {"email": "owner@parametacorp.com"},
                    }

            with patch.object(service.google_auth_svc, "get_valid_access_token", return_value="oauth-token"), patch(
                "src.services.calendar_service.requests.request", return_value=Response()
            ) as mocked_request, patch("src.services.calendar_service.subprocess.run") as mocked_run:
                meeting = service.create_meeting(
                    title="카카오 미팅",
                    start_time=datetime(2026, 3, 30, 15, 0, 0),
                    end_time=datetime(2026, 3, 30, 16, 0, 0),
                    attendees=["user@kakao.com"],
                    description="서비스 소개",
                )

            self.assertIsNotNone(meeting)
            self.assertEqual(meeting.id, "evt-1")
            mocked_request.assert_called_once()
            mocked_run.assert_not_called()
        finally:
            Config.DRY_RUN = original_dry_run
            Config.DRY_RUN_CALENDAR = original_dry_run_calendar
            Config.ENABLE_GOOGLE_OAUTH = original_google_oauth

    def test_gmail_service_uses_google_oauth_before_gws(self):
        original_google_oauth = Config.ENABLE_GOOGLE_OAUTH
        try:
            Config.ENABLE_GOOGLE_OAUTH = True
            service = GmailService()

            class Response:
                text = '{"messages":[{"id":"m1","threadId":"t1"}]}'

                def raise_for_status(self):
                    return None

                def json(self):
                    return {"messages": [{"id": "m1", "threadId": "t1"}]}

            with patch.object(service.google_auth_svc, "get_valid_access_token", return_value="oauth-token"), patch(
                "src.services.gmail_service.requests.get", return_value=Response()
            ) as mocked_get, patch("src.services.gmail_service.subprocess.run") as mocked_run:
                emails = service.search_emails("from:user@kakao.com", max_results=3)

            self.assertEqual(len(emails), 1)
            mocked_get.assert_called_once()
            mocked_run.assert_not_called()
        finally:
            Config.ENABLE_GOOGLE_OAUTH = original_google_oauth

    def test_drive_service_reads_file_via_google_oauth_before_gws(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        try:
            Config.DRY_RUN = False
            with tempfile.TemporaryDirectory(prefix="meetagain-drive-oauth-") as temp_dir:
                Config.CACHE_DIR = temp_dir
                service = DriveService()

                class Response:
                    text = "hello from drive"

                    def raise_for_status(self):
                        return None

                with patch.object(service, "_find_drive_file_id_via_google_oauth", return_value="file-1"), patch.object(
                    service.google_auth_svc, "get_valid_access_token", return_value="oauth-token"
                ), patch("src.services.drive_service.requests.request", return_value=Response()) as mocked_request, patch(
                    "src.services.drive_service.subprocess.run"
                ) as mocked_run:
                    content = service.load_text_file("Contacts/Companies/카카오.md")

                self.assertEqual(content, "hello from drive")
                mocked_request.assert_called_once()
                mocked_run.assert_not_called()
        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir

    def test_drive_service_writes_file_via_google_oauth_before_gws(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        try:
            Config.DRY_RUN = False
            with tempfile.TemporaryDirectory(prefix="meetagain-drive-oauth-") as temp_dir:
                Config.CACHE_DIR = temp_dir
                service = DriveService()

                class Response:
                    text = '{"id":"file-1"}'

                    def raise_for_status(self):
                        return None

                    def json(self):
                        return {"id": "file-1"}

                with patch.object(service, "_find_drive_file_id_via_google_oauth", return_value=None), patch.object(
                    service.google_auth_svc, "get_valid_access_token", return_value="oauth-token"
                ), patch("src.services.drive_service.requests.request", return_value=Response()) as mocked_request, patch(
                    "src.services.drive_service.subprocess.run"
                ) as mocked_run:
                    ok = service.save_company_knowledge("# oauth knowledge")

                self.assertTrue(ok)
                mocked_request.assert_called_once()
                mocked_run.assert_not_called()
        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir


if __name__ == "__main__":
    unittest.main()
