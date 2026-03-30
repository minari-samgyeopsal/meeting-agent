import unittest

from src.utils.meeting_state import get_follow_up_needed, resolve_auto_rerun_stage


class MeetingStateUnitTest(unittest.TestCase):
    def test_get_follow_up_needed_prefers_new_flag(self):
        self.assertTrue(get_follow_up_needed({"follow_up_needed": True, "has_follow_up_meeting": False}))

    def test_resolve_auto_rerun_stage_returns_pipeline_without_transcript(self):
        self.assertEqual(resolve_auto_rerun_stage({}), "pipeline")

    def test_resolve_auto_rerun_stage_returns_during_with_transcript_only(self):
        self.assertEqual(resolve_auto_rerun_stage({"transcript_collected": True}), "during")

    def test_resolve_auto_rerun_stage_returns_after_when_slack_summary_missing(self):
        stage = resolve_auto_rerun_stage(
            {
                "notes_generated": True,
                "after_completed": True,
                "artifacts": [],
            }
        )
        self.assertEqual(stage, "after")


if __name__ == "__main__":
    unittest.main()
