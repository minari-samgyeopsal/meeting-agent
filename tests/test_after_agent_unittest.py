import unittest

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.agents.after_agent import AfterAgent


class DummySlackService:
    def __init__(self, user_id=None):
        self.user_id = user_id

    def get_user_id(self, email):
        return self.user_id


class DummyDriveService:
    def __init__(self):
        self.saved = []
        self.artifacts = []
        self.states = []

    def save_generated_draft(self, meeting_id, draft_type, content):
        self.saved.append((meeting_id, draft_type, content))
        return True

    def append_meeting_artifact(self, meeting_id, artifact_type, path):
        self.artifacts.append((meeting_id, artifact_type, path))
        return True

    def update_meeting_state(self, meeting_id, patch):
        self.states.append((meeting_id, patch))
        return True


class DummyCalendarService:
    def create_draft_meeting(self, title, suggested_date, attendees, agenda, notes=""):
        return True


class AfterAgentUnitTest(unittest.TestCase):
    def test_infer_company_name_prefers_topic(self):
        agent = AfterAgent.__new__(AfterAgent)
        parsed_data = {
            "topic": "kakao follow-up meeting",
            "attendees": ["user@kakao.com"],
        }

        self.assertEqual(agent._infer_company_name(parsed_data), "kakao")

    def test_infer_company_name_falls_back_to_external_domain(self):
        agent = AfterAgent.__new__(AfterAgent)
        parsed_data = {
            "topic": "",
            "attendees": ["internal@parametacorp.com", "user@kakao.com"],
        }

        self.assertEqual(agent._infer_company_name(parsed_data), "kakao")

    def test_build_assignee_reference_returns_slack_mention_when_found(self):
        agent = AfterAgent.__new__(AfterAgent)
        agent.slack_svc = DummySlackService(user_id="U123")

        reference = agent._build_assignee_reference(
            {
                "assignee": "홍길동",
                "assignee_email": "hong@parametacorp.com",
            }
        )

        self.assertEqual(reference, "<@U123>")

    def test_build_assignee_reference_returns_name_when_user_not_found(self):
        agent = AfterAgent.__new__(AfterAgent)
        agent.slack_svc = DummySlackService(user_id=None)

        reference = agent._build_assignee_reference(
            {
                "assignee": "홍길동",
                "assignee_email": "hong@parametacorp.com",
            }
        )

        self.assertEqual(reference, "홍길동")

    def test_schedule_reminder_saves_draft(self):
        agent = AfterAgent.__new__(AfterAgent)
        agent.drive_svc = DummyDriveService()

        result = __import__("asyncio").run(
            agent._schedule_reminder(
                "meeting-1",
                "hong@parametacorp.com",
                {
                    "title": "레퍼런스 전달",
                    "due_date": "2026-03-30",
                    "description": "고객사 전달용 문서 정리",
                },
            )
        )

        self.assertTrue(result)
        self.assertEqual(len(agent.drive_svc.saved), 1)
        self.assertEqual(agent.drive_svc.saved[0][0], "reminders")
        self.assertIn("레퍼런스 전달", agent.drive_svc.saved[0][2])

    def test_needs_proposal_draft_detects_decision_keyword(self):
        agent = AfterAgent.__new__(AfterAgent)

        self.assertTrue(
            agent._needs_proposal_draft(
                {
                    "action_items": [],
                    "decisions": ["다음 주까지 제안서 초안을 준비한다"],
                    "next_steps": [],
                    "discussion_points": [],
                }
            )
        )

    def test_needs_research_draft_detects_next_step_keyword(self):
        agent = AfterAgent.__new__(AfterAgent)

        self.assertTrue(
            agent._needs_research_draft(
                {
                    "action_items": [],
                    "decisions": [],
                    "next_steps": ["시장 분석 리서치를 먼저 진행한다"],
                    "discussion_points": [],
                }
            )
        )

    def test_prepare_follow_up_assets_updates_calendar_creation_state(self):
        agent = AfterAgent.__new__(AfterAgent)
        agent.drive_svc = DummyDriveService()
        agent.calendar_svc = DummyCalendarService()

        result = __import__("asyncio").run(
            agent._prepare_follow_up_assets(
                "meeting-1",
                {
                    "attendees": ["user@kakao.com"],
                    "contact_updates": [],
                    "follow_up_meeting": {
                        "needed": True,
                        "title": "카카오 후속 미팅",
                        "suggested_date": "2026-03-31",
                        "agenda": ["레퍼런스 리뷰"],
                        "notes": "다음 단계 확인",
                    },
                },
            )
        )

        self.assertTrue(result)
        self.assertTrue(agent.drive_svc.states[-1][1]["follow_up_calendar_created"])


if __name__ == "__main__":
    unittest.main()
