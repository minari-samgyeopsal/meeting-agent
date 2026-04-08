import unittest
from unittest.mock import patch

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.cli import _send_channel_monitor_review_queue


class CliUnitTest(unittest.TestCase):
    def test_send_channel_monitor_review_queue_uses_dm_when_email_given(self):
        report = {
            "window_start": "2026-04-04T17:00:00+09:00",
            "window_end": "2026-04-05T17:00:00+09:00",
            "channels": ["C_BIZ"],
            "scanned_count": 3,
            "proposal_count": 1,
            "review_candidate_count": 1,
            "proposals": [{"text": "후보", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "후보"}}]}],
            "review_candidates": [],
        }
        with patch("src.services.slack_service.SlackService.send_dm", return_value="1775.1") as send_dm, patch(
            "src.cli._resolve_dm_channel_id", return_value="D123"
        ), patch("src.services.slack_service.SlackService.send_message", return_value="1775.2") as send_message:
            message = _send_channel_monitor_review_queue(report, send_dm_email="me@example.com")
        send_dm.assert_called_once()
        send_message.assert_called_once()
        self.assertIn("dm=me@example.com", message)
        self.assertIn("1775.1", message)
        self.assertIn("actionable_items=1", message)

    def test_send_channel_monitor_review_queue_uses_channel_when_given(self):
        report = {
            "window_start": "2026-04-04T17:00:00+09:00",
            "window_end": "2026-04-05T17:00:00+09:00",
            "channels": ["C_BIZ"],
            "scanned_count": 3,
            "proposal_count": 1,
            "review_candidate_count": 1,
            "proposals": [{"text": "후보", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "후보"}}]}],
            "review_candidates": [],
        }
        with patch("src.services.slack_service.SlackService.send_message", return_value="1775.2") as send_message:
            message = _send_channel_monitor_review_queue(report, send_channel="D123")
        self.assertEqual(send_message.call_count, 2)
        self.assertIn("channel=D123", message)
        self.assertIn("1775.2", message)
        self.assertIn("actionable_items=1", message)


if __name__ == "__main__":
    unittest.main()
