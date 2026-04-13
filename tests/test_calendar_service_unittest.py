import unittest
from datetime import datetime
from unittest.mock import patch

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.services.calendar_service import CalendarService
from src.utils.config import Config


class CalendarServiceUnitTest(unittest.TestCase):
    def test_get_upcoming_meetings_uses_events_list_params_in_live_mode(self):
        original = Config.DRY_RUN
        original_calendar = Config.DRY_RUN_CALENDAR
        Config.DRY_RUN = False
        Config.DRY_RUN_CALENDAR = False
        try:
            service = CalendarService()

            class Completed:
                returncode = 0
                stderr = ""
                stdout = '{"items":[]}'

            with patch("src.services.calendar_service.subprocess.run", return_value=Completed()) as mocked_run:
                meetings = service.get_upcoming_meetings(hours=24)

            self.assertEqual(meetings, [])
            args, kwargs = mocked_run.call_args
            cmd = args[0]
            self.assertIn("events", cmd)
            self.assertIn("list", cmd)
            self.assertIn("--params", cmd)
            self.assertIn("calendarId", cmd[-1])
        finally:
            Config.DRY_RUN = original
            Config.DRY_RUN_CALENDAR = original_calendar

    def test_create_meeting_returns_dummy_meeting_in_dry_run(self):
        original = Config.DRY_RUN
        original_calendar = Config.DRY_RUN_CALENDAR
        Config.DRY_RUN = True
        Config.DRY_RUN_CALENDAR = True
        try:
            service = CalendarService()
            meeting = service.create_meeting(
                title="카카오 미팅",
                start_time=datetime(2026, 3, 30, 15, 0, 0),
                end_time=datetime(2026, 3, 30, 16, 0, 0),
                attendees=["user@kakao.com"],
                description="서비스 소개",
            )

            self.assertIsNotNone(meeting)
            self.assertTrue(meeting.id.startswith("dry-run-"))
            self.assertEqual(meeting.title, "카카오 미팅")
            self.assertEqual(meeting.calendar_url, "dry-run://calendar-event")
        finally:
            Config.DRY_RUN = original
            Config.DRY_RUN_CALENDAR = original_calendar

    def test_get_upcoming_meetings_returns_demo_meeting_in_dry_run(self):
        original = Config.DRY_RUN
        original_calendar = Config.DRY_RUN_CALENDAR
        Config.DRY_RUN = True
        Config.DRY_RUN_CALENDAR = True
        try:
            service = CalendarService()
            meetings = service.get_upcoming_meetings(hours=24)

            self.assertTrue(meetings)
            self.assertTrue(any(meeting.is_external for meeting in meetings))
            self.assertTrue(any(meeting.id.startswith("dry-run-") for meeting in meetings))
        finally:
            Config.DRY_RUN = original
            Config.DRY_RUN_CALENDAR = original_calendar

    def test_create_draft_meeting_returns_false_when_date_is_undecided(self):
        service = CalendarService.__new__(CalendarService)
        service.create_meeting = lambda *args, **kwargs: None

        result = service.create_draft_meeting(
            title="후속 미팅",
            suggested_date="미정",
            attendees=["user@kakao.com"],
            agenda=["레퍼런스 리뷰"],
        )

        self.assertFalse(result)

    def test_create_draft_meeting_builds_default_time_window(self):
        service = CalendarService.__new__(CalendarService)
        captured = {}

        def fake_create_meeting(title, start_time, end_time, attendees, description=""):
            captured["title"] = title
            captured["start_time"] = start_time
            captured["end_time"] = end_time
            captured["attendees"] = attendees
            captured["description"] = description
            return object()

        service.create_meeting = fake_create_meeting

        result = service.create_draft_meeting(
            title="카카오 후속 미팅",
            suggested_date="2026-03-30",
            attendees=["user@kakao.com"],
            agenda=["레퍼런스 공유", "일정 확인"],
            notes="다음 단계 논의",
        )

        self.assertTrue(result)
        self.assertEqual(captured["title"], "카카오 후속 미팅")
        self.assertEqual(captured["start_time"].hour, 10)
        self.assertEqual(captured["end_time"].hour, 11)
        self.assertIn("- 레퍼런스 공유", captured["description"])
        self.assertIn("메모: 다음 단계 논의", captured["description"])

    def test_create_meeting_uses_events_insert_in_live_mode(self):
        original = Config.DRY_RUN
        original_calendar = Config.DRY_RUN_CALENDAR
        Config.DRY_RUN = False
        Config.DRY_RUN_CALENDAR = False
        try:
            service = CalendarService()

            class Completed:
                returncode = 0
                stderr = ""
                stdout = (
                    '{"id":"evt-1","summary":"카카오 미팅","start":{"dateTime":"2026-03-30T15:00:00"},'
                    '"end":{"dateTime":"2026-03-30T16:00:00"},"organizer":{"email":"owner@parametacorp.com"}}'
                )

            with patch("src.services.calendar_service.subprocess.run", return_value=Completed()) as mocked_run:
                meeting = service.create_meeting(
                    title="카카오 미팅",
                    start_time=datetime(2026, 3, 30, 15, 0, 0),
                    end_time=datetime(2026, 3, 30, 16, 0, 0),
                    attendees=["user@kakao.com"],
                    description="서비스 소개",
                )

            self.assertIsNotNone(meeting)
            args, kwargs = mocked_run.call_args
            cmd = args[0]
            self.assertIn("events", cmd)
            self.assertIn("insert", cmd)
            self.assertIn("--json", cmd)
            self.assertIn("--params", cmd)
        finally:
            Config.DRY_RUN = original
            Config.DRY_RUN_CALENDAR = original_calendar

    def test_looks_external_meeting_uses_company_name_in_title_when_attendees_missing(self):
        service = CalendarService()

        self.assertTrue(service._looks_external_meeting("삼성전자 POC 제안 미팅", []))
        self.assertTrue(service._looks_external_meeting("LG전자 미팅", []))
        self.assertFalse(service._looks_external_meeting("슈퍼사이클 BIZ 미팅", ["cwkwak@parametacorp.com"]))
        self.assertFalse(service._looks_external_meeting("집", []))


if __name__ == "__main__":
    unittest.main()
