import unittest

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.agents.before_agent import BeforeAgent
from src.agents.during_agent import DuringAgent
from src.agents.after_agent import AfterAgent
from src.models.meeting import Meeting
from src.utils.config import Config


class AgentsDryRunUnitTest(unittest.TestCase):
    def test_before_agent_returns_template_briefing_without_anthropic(self):
        original_dry_run = Config.DRY_RUN
        original_key = Config.ANTHROPIC_API_KEY
        try:
            Config.DRY_RUN = True
            Config.ANTHROPIC_API_KEY = ""
            agent = BeforeAgent.__new__(BeforeAgent)
            agent.claude_client = None
            meeting = Meeting(
                id="m1",
                title="카카오 미팅",
                start_time=__import__("datetime").datetime.now(),
                end_time=__import__("datetime").datetime.now(),
                organizer_email="owner@parametacorp.com",
                attendees=["owner@parametacorp.com", "user@kakao.com"],
            )

            briefing = __import__("asyncio").run(
                agent._generate_briefing(meeting, {"companies": {}, "people": {}, "existing_agenda": "없음"})
            )

            self.assertIn("DRY RUN 브리핑", briefing)
        finally:
            Config.DRY_RUN = original_dry_run
            Config.ANTHROPIC_API_KEY = original_key

    def test_during_agent_returns_template_structure_without_anthropic(self):
        original_dry_run = Config.DRY_RUN
        original_key = Config.ANTHROPIC_API_KEY
        try:
            Config.DRY_RUN = True
            Config.ANTHROPIC_API_KEY = ""
            agent = DuringAgent.__new__(DuringAgent)
            agent.claude_client = None

            structured = __import__("asyncio").run(agent._structure_transcript("회의 transcript"))

            self.assertEqual(structured["meeting_title"], "DRY RUN 미팅")
            self.assertEqual(len(structured["action_items"]), 1)
        finally:
            Config.DRY_RUN = original_dry_run
            Config.ANTHROPIC_API_KEY = original_key

    def test_after_agent_returns_template_parse_without_anthropic(self):
        original_dry_run = Config.DRY_RUN
        original_key = Config.ANTHROPIC_API_KEY
        try:
            Config.DRY_RUN = True
            Config.ANTHROPIC_API_KEY = ""
            agent = AfterAgent.__new__(AfterAgent)
            agent.claude_client = None

            parsed = __import__("asyncio").run(agent._parse_meeting_notes("회의록", "m1"))

            self.assertEqual(parsed["topic"], "kakao dry-run meeting")
            self.assertTrue(parsed["follow_up_meeting"]["needed"])
        finally:
            Config.DRY_RUN = original_dry_run
            Config.ANTHROPIC_API_KEY = original_key

    def test_after_agent_dry_run_parse_reflects_proposal_and_research_keywords(self):
        original_dry_run = Config.DRY_RUN
        original_key = Config.ANTHROPIC_API_KEY
        try:
            Config.DRY_RUN = True
            Config.ANTHROPIC_API_KEY = ""
            agent = AfterAgent.__new__(AfterAgent)
            agent.claude_client = None

            parsed = __import__("asyncio").run(
                agent._parse_meeting_notes("고객사 제안서와 시장 분석 리서치가 필요합니다", "m1")
            )

            titles = [item["title"] for item in parsed["action_items"]]
            self.assertIn("제안서 초안 작성", titles)
            self.assertIn("시장 분석 리서치", titles)
        finally:
            Config.DRY_RUN = original_dry_run
            Config.ANTHROPIC_API_KEY = original_key


if __name__ == "__main__":
    unittest.main()
