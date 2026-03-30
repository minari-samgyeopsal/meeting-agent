import unittest

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.agents.before_agent import BeforeAgent
from src.models.contact import Company, Person
from src.models.meeting import Meeting


class _DateTimeModule:
    @staticmethod
    def now():
        return __import__("datetime").datetime.now()


class DummySlackService:
    def create_draft(self, channel, text):
        return {"channel": channel, "text": text}


class DummyDriveService:
    def __init__(self):
        self.saved = []
        self.artifacts = []
        self.states = []
        self.state = {}

    def save_generated_draft(self, meeting_id, draft_type, content):
        self.saved.append((meeting_id, draft_type, content))
        return True

    def append_meeting_artifact(self, meeting_id, artifact_type, path):
        self.artifacts.append((meeting_id, artifact_type, path))
        return True

    def update_meeting_state(self, meeting_id, patch):
        self.states.append((meeting_id, patch))
        return True

    def load_meeting_state(self, meeting_id):
        return self.state


class BeforeAgentUnitTest(unittest.TestCase):
    def setUp(self):
        self.agent = BeforeAgent.__new__(BeforeAgent)

    def test_extract_existing_agenda_from_bullets(self):
        meeting = Meeting(
            id="1",
            title="카카오 미팅",
            start_time=_DateTimeModule.now(),
            end_time=_DateTimeModule.now(),
            organizer_email="owner@parametacorp.com",
            attendees=["owner@parametacorp.com", "user@kakao.com"],
            description="- 서비스 소개\n- 다음 단계 협의",
        )

        agenda = self.agent._extract_existing_agenda(meeting)

        self.assertIn("- 서비스 소개", agenda)
        self.assertIn("- 다음 단계 협의", agenda)

    def test_infer_company_name_from_external_email(self):
        self.assertEqual(
            self.agent._infer_company_name_from_email("user@kakao.com"),
            "kakao",
        )

    def test_infer_company_name_from_internal_email_returns_none(self):
        self.assertIsNone(
            self.agent._infer_company_name_from_email("user@parametacorp.com")
        )

    def test_format_people_includes_company_and_notes(self):
        rendered = self.agent._format_people(
            {
                "user@kakao.com": Person(
                    name="김민환",
                    company="kakao",
                    notes="숫자 근거 중시",
                )
            }
        )

        self.assertIn("김민환", rendered)
        self.assertIn("회사: kakao", rendered)
        self.assertIn("참고: 숫자 근거 중시", rendered)

    def test_format_companies_includes_news(self):
        rendered = self.agent._format_companies(
            {
                "kakao": Company(
                    name="kakao",
                    description="플랫폼 기업",
                    recent_news=[{"title": "신사업 발표", "url": "https://example.com"}],
                )
            }
        )

        self.assertIn("설명: 플랫폼 기업", rendered)
        self.assertIn("신사업 발표", rendered)

    def test_send_briefing_persists_draft_artifact(self):
        meeting = Meeting(
            id="m1",
            title="카카오 미팅",
            start_time=_DateTimeModule.now(),
            end_time=_DateTimeModule.now(),
            organizer_email="owner@parametacorp.com",
            attendees=["owner@parametacorp.com", "user@kakao.com"],
            is_external=True,
        )
        self.agent.slack_svc = DummySlackService()
        self.agent.drive_svc = DummyDriveService()

        async def fake_collect(_meeting):
            return {"companies": {}, "people": {}, "previous_context": {}, "existing_agenda": "없음"}

        async def fake_generate(_meeting, _data):
            return "briefing text"

        self.agent._collect_briefing_data = fake_collect
        self.agent._generate_briefing = fake_generate

        result = __import__("asyncio").run(self.agent.send_briefing(meeting))

        self.assertTrue(result)
        self.assertEqual(self.agent.drive_svc.saved[0][1], "before_briefing")
        self.assertEqual(self.agent.drive_svc.artifacts[0][1], "before_briefing")

    def test_build_meeting_from_state_restores_meeting(self):
        meeting = self.agent._build_meeting_from_state(
            {
                "meeting_id": "m1",
                "title": "카카오 미팅",
                "start_time": "2026-03-25T15:00:00",
                "end_time": "2026-03-25T16:00:00",
                "organizer_email": "owner@parametacorp.com",
                "attendees": ["owner@parametacorp.com", "user@kakao.com"],
                "description": "서비스 소개",
                "calendar_url": "dry-run://calendar-event",
            }
        )

        self.assertIsNotNone(meeting)
        self.assertEqual(meeting.id, "m1")
        self.assertEqual(meeting.title, "카카오 미팅")
        self.assertEqual(meeting.attendees[-1], "user@kakao.com")

    def test_build_template_agenda_for_client(self):
        agenda = self.agent._build_template_agenda("client")

        self.assertIn("상호 소개 및 미팅 목표 정렬", agenda)
        self.assertIn("다음 단계 및 일정 협의", agenda)

    def test_infer_template_prefers_review_keyword(self):
        template = self.agent._infer_template(
            "주간 서비스 리뷰",
            ["owner@parametacorp.com", "user@kakao.com"],
        )

        self.assertEqual(template, "review")

    def test_infer_template_uses_client_for_external_meeting(self):
        template = self.agent._infer_template(
            "카카오 협의",
            ["owner@parametacorp.com", "user@kakao.com"],
        )

        self.assertEqual(template, "client")

    def test_infer_template_uses_internal_for_internal_meeting(self):
        template = self.agent._infer_template(
            "주간 싱크",
            ["owner@parametacorp.com", "teammate@iconloop.com"],
        )

        self.assertEqual(template, "internal")

    def test_resolve_agenda_combines_template_and_custom_notes(self):
        agenda = self.agent._resolve_agenda("추가 요청사항", "review")

        self.assertIn("목표 대비 결과 리뷰", agenda)
        self.assertIn("추가 메모:", agenda)
        self.assertIn("추가 요청사항", agenda)

    def test_count_agenda_items_ignores_additional_note_header(self):
        count = self.agent._count_agenda_items(
            "- 목표 리뷰\n- 액션 정리\n\n추가 메모:\n예산 확인"
        )

        self.assertEqual(count, 3)

    def test_rerun_briefing_from_state_uses_restored_meeting(self):
        self.agent.drive_svc = DummyDriveService()
        self.agent.drive_svc.state = {
            "meeting_id": "m1",
            "title": "카카오 미팅",
            "start_time": "2026-03-25T15:00:00",
            "end_time": "2026-03-25T16:00:00",
            "organizer_email": "owner@parametacorp.com",
            "attendees": ["owner@parametacorp.com", "user@kakao.com"],
            "description": "서비스 소개",
            "calendar_url": "dry-run://calendar-event",
        }

        captured = {}

        async def fake_send_briefing(meeting):
            captured["meeting_id"] = meeting.id
            captured["title"] = meeting.title
            return True

        self.agent.send_briefing = fake_send_briefing

        result = __import__("asyncio").run(self.agent.rerun_briefing_from_state("m1"))

        self.assertTrue(result)
        self.assertEqual(captured["meeting_id"], "m1")
        self.assertEqual(captured["title"], "카카오 미팅")


if __name__ == "__main__":
    unittest.main()
