import unittest
import tempfile
import shutil

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.services.drive_service import DriveService
from src.services.slack_service import SlackService
from src.services.trello_service import TrelloService
from src.utils.config import Config


class ServicesDryRunUnitTest(unittest.TestCase):
    def test_config_validate_skips_slack_and_trello_in_dry_run(self):
        original = Config.DRY_RUN
        original_slack = Config.SLACK_BOT_TOKEN
        original_secret = Config.SLACK_SIGNING_SECRET
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN
        original_anthropic = Config.ANTHROPIC_API_KEY
        try:
            Config.DRY_RUN = True
            Config.SLACK_BOT_TOKEN = ""
            Config.SLACK_SIGNING_SECRET = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""
            Config.ANTHROPIC_API_KEY = "test-key"

            self.assertTrue(
                Config.validate(
                    [
                        "SLACK_BOT_TOKEN",
                        "SLACK_SIGNING_SECRET",
                        "TRELLO_API_KEY",
                        "TRELLO_API_TOKEN",
                        "ANTHROPIC_API_KEY",
                    ]
                )
            )
        finally:
            Config.DRY_RUN = original
            Config.SLACK_BOT_TOKEN = original_slack
            Config.SLACK_SIGNING_SECRET = original_secret
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            Config.ANTHROPIC_API_KEY = original_anthropic

    def test_slack_service_allows_dry_run_without_token(self):
        original = Config.DRY_RUN
        original_slack = Config.SLACK_BOT_TOKEN
        try:
            Config.DRY_RUN = True
            Config.SLACK_BOT_TOKEN = ""
            service = SlackService()
            self.assertEqual(service.send_dm("user@example.com", "hello"), "dry-run-dm-ts")
            self.assertEqual(service.get_user_id("user@example.com"), "DRYRUN_USER")
        finally:
            Config.DRY_RUN = original
            Config.SLACK_BOT_TOKEN = original_slack

    def test_trello_service_returns_dummy_card_in_dry_run(self):
        original = Config.DRY_RUN
        original_key = Config.TRELLO_API_KEY
        original_token = Config.TRELLO_API_TOKEN
        try:
            Config.DRY_RUN = True
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""
            service = TrelloService()
            card = service.create_company_card("kakao")
            self.assertIsNotNone(card)
            self.assertEqual(card.name, "kakao")
            self.assertTrue(service.add_checklist_item(card, "follow up"))
        finally:
            Config.DRY_RUN = original
            Config.TRELLO_API_KEY = original_key
            Config.TRELLO_API_TOKEN = original_token

    def test_drive_service_persists_files_locally_in_dry_run(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        temp_dir = tempfile.mkdtemp(prefix="meetagain-drive-")
        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            service = DriveService()

            self.assertTrue(service.save_meeting_transcript("m1", "hello transcript"))
            self.assertEqual(service.load_meeting_transcript("m1"), "hello transcript")

            self.assertTrue(service.save_company_knowledge("# dry run knowledge"))
            self.assertIn("dry run knowledge", service.load_company_knowledge())

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
