import unittest

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.agents.during_agent import DuringAgent


class DummyDriveService:
    def __init__(self):
        self.saved_transcripts = []
        self.artifacts = []
        self.states = []
        self.state = {}

    def save_meeting_transcript(self, meeting_id, content):
        self.saved_transcripts.append((meeting_id, content))
        return True

    def append_meeting_artifact(self, meeting_id, artifact_type, path):
        self.artifacts.append((meeting_id, artifact_type, path))
        return True

    def update_meeting_state(self, meeting_id, patch):
        self.states.append((meeting_id, patch))
        return True

    def load_meeting_state(self, meeting_id):
        return self.state


class DuringAgentUnitTest(unittest.TestCase):
    def test_process_meeting_persists_local_transcript(self):
        agent = DuringAgent.__new__(DuringAgent)
        agent.drive_svc = DummyDriveService()

        async def fake_generate_meeting_notes(meeting_id, transcript):
            return True

        agent.generate_meeting_notes = fake_generate_meeting_notes

        result = __import__("asyncio").run(
            agent.process_meeting("m1", transcript_text="회의 transcript")
        )

        self.assertTrue(result)
        self.assertEqual(agent.drive_svc.saved_transcripts[0], ("m1", "회의 transcript"))
        self.assertEqual(agent.drive_svc.artifacts[0][1], "transcript")

    def test_process_meeting_builds_fallback_transcript_in_dry_run(self):
        from src.utils.config import Config

        original = Config.DRY_RUN
        Config.DRY_RUN = True
        try:
            agent = DuringAgent.__new__(DuringAgent)
            agent.drive_svc = DummyDriveService()
            agent.drive_svc.state = {
                "title": "데모 미팅",
                "latest_agenda": "- 서비스 소개\n- 다음 단계 협의",
            }

            async def fake_collect_transcript(meeting_id):
                return None

            async def fake_generate_meeting_notes(meeting_id, transcript):
                return "DRY_RUN fallback transcript" in transcript

            agent.collect_transcript = fake_collect_transcript
            agent.generate_meeting_notes = fake_generate_meeting_notes

            result = __import__("asyncio").run(agent.process_meeting("m1"))

            self.assertTrue(result)
            self.assertEqual(agent.drive_svc.saved_transcripts[0][0], "m1")
            self.assertIn("데모 미팅", agent.drive_svc.saved_transcripts[0][1])
        finally:
            Config.DRY_RUN = original

    def test_extract_registered_agenda_from_state(self):
        agent = DuringAgent.__new__(DuringAgent)

        agenda = agent._extract_registered_agenda(
            {
                "latest_agenda": "- 서비스 소개\n- 다음 단계 협의\n",
            }
        )

        self.assertEqual(agenda, ["서비스 소개", "다음 단계 협의"])

    def test_normalize_agenda_status_uses_registered_agenda(self):
        agent = DuringAgent.__new__(DuringAgent)

        normalized = agent._normalize_agenda_status(
            {
                "agenda": [],
                "agenda_status": [{"item": "서비스 소개", "status": "논의됨"}],
            },
            ["서비스 소개", "다음 단계 협의"],
        )

        self.assertEqual(normalized["agenda"], ["서비스 소개", "다음 단계 협의"])
        self.assertEqual(normalized["agenda_status"][0]["status"], "논의됨")
        self.assertEqual(normalized["agenda_status"][1]["status"], "미논의")

    def test_generate_meeting_notes_updates_agenda_counts(self):
        agent = DuringAgent.__new__(DuringAgent)
        agent.drive_svc = DummyDriveService()
        agent.drive_svc.state = {"latest_agenda": "- 서비스 소개\n- 다음 단계 협의"}

        async def fake_structure(transcript, registered_agenda=None):
            return {
                "meeting_title": "테스트 미팅",
                "attendees": ["user@kakao.com"],
                "agenda": registered_agenda or [],
                "summary": transcript,
                "discussion_points": [transcript],
                "decisions": ["결론"],
                "action_items": [],
                "next_steps": [],
                "internal_notes": [],
                "agenda_status": [{"item": item, "status": "논의됨"} for item in (registered_agenda or [])],
            }

        agent._structure_transcript = fake_structure
        agent._render_client_notes = lambda structured: "client notes"
        agent._render_internal_notes = lambda structured: "internal notes"
        agent.drive_svc.save_meeting_notes = lambda meeting_id, client_notes, internal_notes: True

        result = __import__("asyncio").run(agent.generate_meeting_notes("m1", "회의 transcript"))

        self.assertTrue(result)
        last_patch = agent.drive_svc.states[-1][1]
        self.assertEqual(last_patch["registered_agenda_count"], 2)
        self.assertEqual(last_patch["agenda_status_count"], 2)

    def test_build_dry_run_structure_uses_demo_kakao_content(self):
        agent = DuringAgent.__new__(DuringAgent)

        structured = agent._build_dry_run_structure(
            "카카오 DID 미팅 transcript",
            ["파라메타 DID 솔루션 소개", "카카오 내부 인증 시스템 현황 파악", "파일럿 도입 범위 협의"],
        )

        self.assertEqual(structured["meeting_title"], "카카오 미팅")
        self.assertIn("1단계 파일럿: 카카오 사내 임직원 인증 모듈 (500명)", structured["decisions"])
        self.assertEqual(structured["action_items"][0]["assignee"], "류혁곤")
        self.assertEqual(structured["action_items"][1]["assignee"], "김민환")
        self.assertTrue(all(item["status"] == "논의됨" for item in structured["agenda_status"]))


if __name__ == "__main__":
    unittest.main()
