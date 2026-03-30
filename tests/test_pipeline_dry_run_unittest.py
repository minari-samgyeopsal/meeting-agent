import shutil
import tempfile
import unittest

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.agents.after_agent import AfterAgent
from src.agents.during_agent import DuringAgent
from src.utils.config import Config


class PipelineDryRunUnitTest(unittest.TestCase):
    def test_during_and_after_pipeline_persists_outputs_without_external_keys(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-pipeline-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            during_agent = DuringAgent()
            after_agent = AfterAgent()

            meeting_id = "dry-run-meeting"
            transcript = "고객사와 제안서, 시장 분석 리서치, 후속 미팅 필요성을 논의했습니다."

            self.assertTrue(
                __import__("asyncio").run(
                    during_agent.process_meeting(meeting_id, transcript_text=transcript)
                )
            )
            self.assertTrue(__import__("asyncio").run(after_agent.process_meeting(meeting_id)))

            state = after_agent.drive_svc.load_meeting_state(meeting_id)
            self.assertTrue(state["transcript_collected"])
            self.assertTrue(state["notes_generated"])
            self.assertTrue(state["after_completed"])
            self.assertEqual(state["assignee_dm_count"], 3)
            self.assertEqual(state["reminder_count"], 3)
            self.assertEqual(state["contact_update_count"], 1)
            self.assertTrue(state["proposal_draft_created"])
            self.assertTrue(state["research_draft_created"])
            self.assertTrue(state["follow_up_draft_created"])
            self.assertTrue(state["follow_up_calendar_created"])

            artifact_types = {artifact["type"] for artifact in state.get("artifacts", [])}
            self.assertIn("meeting_note_internal", artifact_types)
            self.assertIn("slack_summary", artifact_types)
            self.assertIn("contact_updates", artifact_types)
            self.assertIn("follow_up_meeting", artifact_types)
            self.assertIn("proposal", artifact_types)
            self.assertIn("research", artifact_types)
            self.assertIn("reminder", artifact_types)

            internal_notes = after_agent.drive_svc.load_meeting_notes(meeting_id, version="internal")
            self.assertIn("DRY RUN", internal_notes)

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            Config.ANTHROPIC_API_KEY = original_anthropic
            Config.SLACK_BOT_TOKEN = original_slack
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
