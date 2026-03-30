import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.cli import (
    _build_dashboard,
    _build_doctor_report,
    _export_ops_reports,
    _filter_meeting_states,
    _build_meeting_bundle,
    _build_smoke_transcript,
    _list_meeting_states,
    _render_demo_report,
    _render_demo_playbook,
    _render_doctor_report,
    _render_dashboard,
    _render_meeting_state_list,
    _render_ops_export_report,
    _render_bundle,
    _render_smoke_suite_report,
    _run_demo,
    _run_smoke_suite,
    _run_smoke_test,
)
from src.utils.config import Config


class CliUnitTest(unittest.TestCase):
    def test_build_smoke_transcript_reflects_agenda_and_follow_up_keywords(self):
        transcript = _build_smoke_transcript(
            "카카오 미팅",
            "- 서비스 소개\n- 다음 단계 협의",
        )

        self.assertIn("카카오 미팅", transcript)
        self.assertIn("서비스 소개", transcript)
        self.assertIn("제안서", transcript)
        self.assertIn("리서치", transcript)
        self.assertIn("후속 미팅", transcript)

    def test_run_smoke_test_prints_final_json_state_in_dry_run(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-cli-smoke-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            args = SimpleNamespace(
                title="카카오 미팅",
                start="2026-03-25T15:00:00",
                end="2026-03-25T16:00:00",
                attendee=["owner@parametacorp.com", "user@kakao.com"],
                agenda="- 서비스 소개\n- 다음 단계 협의",
                template="client",
                transcript_file=None,
                transcript_text=None,
                json=True,
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                success = __import__("asyncio").run(_run_smoke_test(args))

            self.assertTrue(success)

            payload = json.loads(buffer.getvalue())
            self.assertTrue(payload["meeting_created"])
            self.assertTrue(payload["transcript_collected"])
            self.assertTrue(payload["notes_generated"])
            self.assertTrue(payload["after_completed"])
            self.assertTrue(payload["proposal_draft_created"])
            self.assertTrue(payload["research_draft_created"])
            self.assertTrue(payload["follow_up_draft_created"])
            self.assertTrue(payload["follow_up_calendar_created"])

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            Config.ANTHROPIC_API_KEY = original_anthropic
            Config.SLACK_BOT_TOKEN = original_slack
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_build_meeting_bundle_collects_outputs_after_smoke_run(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-cli-bundle-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            args = SimpleNamespace(
                title="카카오 미팅",
                start="2026-03-25T15:00:00",
                end="2026-03-25T16:00:00",
                attendee=["owner@parametacorp.com", "user@kakao.com"],
                agenda="- 서비스 소개\n- 다음 단계 협의",
                template="client",
                transcript_file=None,
                transcript_text=None,
                json=True,
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                success = __import__("asyncio").run(_run_smoke_test(args))

            self.assertTrue(success)
            state = json.loads(buffer.getvalue())
            meeting_id = state["meeting_id"]

            bundle = _build_meeting_bundle(meeting_id)

            self.assertIsNotNone(bundle)
            self.assertIn("카카오 미팅", bundle["transcript"])
            self.assertIn("[클라이언트용]", bundle["notes"]["client"])
            self.assertIn("## 내부 메모", bundle["notes"]["internal"])
            artifact_types = {artifact["type"] for artifact in bundle["artifacts"]}
            self.assertIn("slack_summary", artifact_types)
            self.assertIn("proposal", artifact_types)
            self.assertIn("research", artifact_types)

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            Config.ANTHROPIC_API_KEY = original_anthropic
            Config.SLACK_BOT_TOKEN = original_slack
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_render_bundle_contains_sections(self):
        rendered = _render_bundle(
            {
                "meeting_id": "m1",
                "state": {"meeting_id": "m1", "phase": "after"},
                "transcript": "회의 transcript",
                "notes": {"client": "client notes", "internal": "internal notes"},
                "artifacts": [
                    {
                        "type": "slack_summary",
                        "path": "GeneratedDrafts/m1_slack_summary.md",
                        "content": "summary draft",
                    }
                ],
            },
            as_json=False,
        )

        self.assertIn("# Meeting Bundle: m1", rendered)
        self.assertIn("## Transcript", rendered)
        self.assertIn("## Client Notes", rendered)
        self.assertIn("## Internal Notes", rendered)
        self.assertIn("### [slack_summary] GeneratedDrafts/m1_slack_summary.md", rendered)

    def test_run_smoke_test_can_save_bundle_to_file(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-cli-save-bundle-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            save_path = os.path.join(temp_dir, "bundle.md")
            args = SimpleNamespace(
                title="카카오 미팅",
                start="2026-03-25T15:00:00",
                end="2026-03-25T16:00:00",
                attendee=["owner@parametacorp.com", "user@kakao.com"],
                agenda="- 서비스 소개\n- 다음 단계 협의",
                template="client",
                transcript_file=None,
                transcript_text=None,
                json=False,
                bundle=True,
                save_bundle=save_path,
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                success = __import__("asyncio").run(_run_smoke_test(args))

            self.assertTrue(success)
            self.assertTrue(os.path.exists(save_path))
            with open(save_path, encoding="utf-8") as file_obj:
                saved = file_obj.read()
            self.assertIn("# Meeting Bundle:", saved)
            self.assertIn("## Transcript", saved)

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            Config.ANTHROPIC_API_KEY = original_anthropic
            Config.SLACK_BOT_TOKEN = original_slack
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_render_smoke_suite_report_contains_scenarios(self):
        rendered = _render_smoke_suite_report(
            {
                "generated_at": "2026-03-25T18:00:00",
                "output_dir": "artifacts/smoke_suite_20260325_180000",
                "scenario_count": 2,
                "all_passed": True,
                "scenarios": [
                    {
                        "name": "client",
                        "meeting_id": "m-client",
                        "title": "카카오 미팅",
                        "template": "client",
                        "after_completed": True,
                        "proposal_draft_created": True,
                        "research_draft_created": True,
                        "follow_up_calendar_created": True,
                        "artifact_count": 7,
                        "bundle_markdown_path": "client_bundle.md",
                        "bundle_json_path": "client_bundle.json",
                    }
                ],
            }
        )

        self.assertIn("# Smoke Suite Report", rendered)
        self.assertIn("### client", rendered)
        self.assertIn("- proposal 초안: True", rendered)
        self.assertIn("- Markdown bundle: client_bundle.md", rendered)

    def test_render_demo_report_contains_sections(self):
        rendered = _render_demo_report(
            {
                "generated_at": "2026-03-26T12:00:00",
                "output_dir": "artifacts/demo_20260326_120000",
                "smoke_suite_output_dir": "artifacts/demo_20260326_120000/smoke_suite",
                "ops_export_output_dir": "artifacts/demo_20260326_120000/ops_export",
                "doctor_markdown_path": "artifacts/demo_20260326_120000/doctor_snapshot.md",
                "doctor_json_path": "artifacts/demo_20260326_120000/doctor_snapshot.json",
                "scenario_count": 3,
                "all_passed": True,
                "ops_entry_count": 3,
                "bundle_count": 2,
                "featured_meetings": [
                    {
                        "name": "client",
                        "meeting_id": "m-client",
                        "title": "카카오 미팅",
                        "template": "client",
                        "bundle_command": "python3 -m src.cli bundle --meeting-id m-client",
                        "status_command": "python3 -m src.cli status --meeting-id m-client",
                    }
                ],
                "next_steps": ["python3 -m src.cli bundle --meeting-id <EVENT_ID>"],
            }
        )

        self.assertIn("# Meetagain Demo Report", rendered)
        self.assertIn("smoke-suite 경로", rendered)
        self.assertIn("ops-export 경로", rendered)
        self.assertIn("doctor markdown", rendered)
        self.assertIn("## Featured Meetings", rendered)
        self.assertIn("m-client", rendered)
        self.assertIn("bundle --meeting-id m-client", rendered)
        self.assertIn("## Next Steps", rendered)

    def test_render_demo_playbook_contains_featured_meetings(self):
        rendered = _render_demo_playbook(
            {
                "output_dir": "artifacts/demo_20260326_120000",
                "doctor_markdown_path": "artifacts/demo_20260326_120000/doctor_snapshot.md",
                "featured_meetings": [
                    {
                        "name": "client",
                        "meeting_id": "m-client",
                        "title": "카카오 미팅",
                        "template": "client",
                        "bundle_command": "python3 -m src.cli bundle --meeting-id m-client",
                        "status_command": "python3 -m src.cli status --meeting-id m-client",
                    }
                ],
                "next_steps": ["python3 -m src.cli bundle --meeting-id <EVENT_ID>"],
            }
        )

        self.assertIn("# Meetagain Demo Playbook", rendered)
        self.assertIn("## 2. 대표 미팅 확인", rendered)
        self.assertIn("m-client", rendered)
        self.assertIn("status --meeting-id m-client", rendered)
        self.assertIn("bundle --meeting-id m-client", rendered)

    def test_render_meeting_state_list_contains_recent_entries(self):
        rendered = _render_meeting_state_list(
            [
                {
                    "meeting_id": "m2",
                    "title": "카카오 미팅",
                    "phase": "after",
                    "template": "client",
                    "updated_at": "2026-03-25T18:20:00",
                    "after_completed": True,
                    "artifacts": [{"type": "slack_summary", "path": "GeneratedDrafts/m2_slack_summary.md"}],
                }
            ]
        )

        self.assertIn("# Meeting State List", rendered)
        self.assertIn("- m2 | 카카오 미팅", rendered)
        self.assertIn("template=client", rendered)
        self.assertIn("next=", rendered)
        self.assertIn("python3 -m src.cli bundle --meeting-id m2", rendered)

    def test_build_dashboard_summarizes_key_counts(self):
        dashboard = _build_dashboard(
            [
                {
                    "meeting_id": "m1",
                    "title": "카카오 미팅",
                    "phase": "after",
                    "after_completed": True,
                    "follow_up_needed": True,
                    "transcript_collected": True,
                    "notes_generated": True,
                    "updated_at": "2026-03-25T18:10:00",
                    "template": "client",
                    "artifacts": [{"type": "slack_summary", "path": "GeneratedDrafts/m1_slack_summary.md"}],
                },
                {
                    "meeting_id": "m2",
                    "title": "내부 싱크",
                    "phase": "during",
                    "after_completed": False,
                    "transcript_collected": True,
                    "notes_generated": True,
                    "registered_agenda_count": 3,
                    "agenda_status_count": 1,
                    "updated_at": "2026-03-25T18:20:00",
                    "template": "internal",
                    "artifacts": [],
                },
            ]
        )

        self.assertEqual(dashboard["total_meetings"], 2)
        self.assertEqual(dashboard["after_completed_count"], 1)
        self.assertEqual(dashboard["follow_up_needed_count"], 1)
        self.assertEqual(dashboard["needs_after_count"], 2)
        self.assertEqual(dashboard["stalled_agenda_count"], 1)

    def test_filter_meeting_states_supports_operational_flags(self):
        entries = [
            {
                "meeting_id": "m1",
                "notes_generated": True,
                "after_completed": False,
                "follow_up_needed": False,
                "registered_agenda_count": 2,
                "agenda_status_count": 2,
                "artifacts": [],
            },
            {
                "meeting_id": "m2",
                "notes_generated": True,
                "after_completed": True,
                "follow_up_needed": True,
                "follow_up_calendar_created": False,
                "registered_agenda_count": 3,
                "agenda_status_count": 1,
                "artifacts": [
                    {"type": "slack_summary", "path": "GeneratedDrafts/m2_slack_summary.md"},
                    {"type": "follow_up_meeting", "path": "GeneratedDrafts/m2_follow_up_meeting.md"},
                ],
            },
        ]

        self.assertEqual(len(_filter_meeting_states(entries, needs_after=True)), 2)
        self.assertEqual(len(_filter_meeting_states(entries, stalled_agenda=True)), 1)
        self.assertEqual(len(_filter_meeting_states(entries, follow_up_needed=True)), 1)

    def test_render_dashboard_contains_sections(self):
        rendered = _render_dashboard(
            {
                "generated_at": "2026-03-25T18:30:00",
                "total_meetings": 2,
                "completion_rate": "1/2 (50%)",
                "follow_up_needed_count": 1,
                "missing_transcript_count": 0,
                "missing_notes_count": 0,
                "needs_after_count": 1,
                "stalled_agenda_count": 1,
                "recent_meetings": [
                    {
                        "meeting_id": "m1",
                        "title": "카카오 미팅",
                        "phase": "after",
                        "template": "client",
                        "updated_at": "2026-03-25T18:20:00",
                    }
                ],
                "needs_after": [
                    {
                        "meeting_id": "m2",
                        "title": "내부 싱크",
                        "reason": "After 후속 처리가 덜 끝남",
                        "updated_at": "2026-03-25T18:10:00",
                    }
                ],
                "stalled_agenda": [
                    {
                        "meeting_id": "m3",
                        "title": "분기 리뷰",
                        "agenda_progress": "1/3",
                        "updated_at": "2026-03-25T18:05:00",
                    }
                ],
            },
            as_json=False,
        )

        self.assertIn("# Meeting Dashboard", rendered)
        self.assertIn("## 최근 미팅", rendered)
        self.assertIn("## After 확인 필요", rendered)
        self.assertIn("## 어젠다 체크 지연", rendered)
        self.assertIn("cmd: python3 -m src.cli rerun --meeting-id m2 --stage after", rendered)

    def test_render_doctor_report_contains_sections(self):
        rendered = _render_doctor_report(
            {
                "generated_at": "2026-03-25T20:00:00",
                "mode": "dry_run",
                "meeting_state_count": 2,
                "env": {
                    "DRY_RUN": True,
                    "ANTHROPIC_API_KEY": False,
                    "SLACK_BOT_TOKEN": False,
                    "SLACK_SIGNING_SECRET": False,
                    "SLACK_APP_TOKEN": False,
                    "TRELLO_API_KEY": False,
                    "TRELLO_API_TOKEN": False,
                    "GWS_CRED_FILE": False,
                },
                "live_checks": {
                    "slack_ready": False,
                    "trello_ready": False,
                    "anthropic_ready": False,
                    "gws_ready": False,
                    "gws_cli_ready": False,
                    "core_live_ready": False,
                },
                "filesystem": {
                    "cache_dir": "/tmp/demo",
                    "cache_dir_exists": True,
                    "dry_run_drive_exists": True,
                    "meeting_state_dir_exists": True,
                    "meeting_notes_dir_exists": True,
                    "transcripts_dir_exists": True,
                    "drafts_dir_exists": True,
                },
                "latest_meeting": {
                    "meeting_id": "m1",
                    "title": "카카오 미팅",
                    "updated_at": "2026-03-25T19:00:00",
                    "phase": "after",
                },
                "dashboard": {
                    "completion_rate": "1/2 (50%)",
                    "follow_up_needed_count": 1,
                    "missing_transcript_count": 0,
                    "missing_notes_count": 0,
                    "needs_after_count": 1,
                    "stalled_agenda_count": 1,
                },
                "recommendations": ["python3 -m src.cli bundle --meeting-id m1"],
            },
            as_json=False,
        )

        self.assertIn("# Meetagain Doctor", rendered)
        self.assertIn("## Environment", rendered)
        self.assertIn("## Live Readiness", rendered)
        self.assertIn("gws_cli_ready", rendered)
        self.assertIn("## Filesystem", rendered)
        self.assertIn("## Recommendations", rendered)

    def test_render_ops_export_report_contains_files(self):
        rendered = _render_ops_export_report(
            {
                "generated_at": "2026-03-26T10:00:00",
                "output_dir": "artifacts/ops_export_demo",
                "entry_count": 3,
                "filters": {
                    "needs_after": True,
                    "stalled_agenda": False,
                    "follow_up_needed": False,
                },
                "files": {
                    "meeting_list_markdown": "artifacts/ops_export_demo/meeting_list.md",
                    "meeting_list_json": "artifacts/ops_export_demo/meeting_list.json",
                    "dashboard_markdown": "artifacts/ops_export_demo/dashboard.md",
                    "dashboard_json": "artifacts/ops_export_demo/dashboard.json",
                    "doctor_markdown": "artifacts/ops_export_demo/doctor.md",
                    "doctor_json": "artifacts/ops_export_demo/doctor.json",
                    "readme": "artifacts/ops_export_demo/README.md",
                    "metadata": "artifacts/ops_export_demo/metadata.json",
                },
                "bundles": [
                    {
                        "meeting_id": "m1",
                        "markdown": "artifacts/ops_export_demo/bundles/m1_bundle.md",
                        "json": "artifacts/ops_export_demo/bundles/m1_bundle.json",
                    }
                ],
            }
        )

        self.assertIn("# Ops Export", rendered)
        self.assertIn("meeting_list.md", rendered)
        self.assertIn("doctor.json", rendered)
        self.assertIn("## Bundles", rendered)
        self.assertIn("m1_bundle.md", rendered)

    def test_build_doctor_report_after_suite(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-cli-doctor-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            args = SimpleNamespace(
                output_dir=os.path.join(temp_dir, "suite"),
                json=True,
            )
            __import__("asyncio").run(_run_smoke_suite(args))

            report = _build_doctor_report(limit=3)

            self.assertEqual(report["mode"], "dry_run")
            self.assertGreaterEqual(report["meeting_state_count"], 3)
            self.assertTrue(report["filesystem"]["dry_run_drive_exists"])
            self.assertIn("live_checks", report)
            self.assertIn("slack_ready", report["live_checks"])
            self.assertIn("dashboard", report)
            self.assertTrue(report["recommendations"])
            self.assertTrue(
                any("ops-export" in item and "--include-bundles" in item for item in report["recommendations"])
            )

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            Config.ANTHROPIC_API_KEY = original_anthropic
            Config.SLACK_BOT_TOKEN = original_slack
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_build_doctor_report_respects_filters(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-cli-doctor-filter-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            args = SimpleNamespace(
                output_dir=os.path.join(temp_dir, "suite"),
                json=True,
            )
            __import__("asyncio").run(_run_smoke_suite(args))

            report = _build_doctor_report(limit=5, follow_up_needed=True)

            self.assertTrue(report["filters"]["follow_up_needed"])
            self.assertGreaterEqual(report["meeting_state_count"], 1)
            self.assertTrue(
                any("--follow-up-needed" in item for item in report["recommendations"] if "ops-export" in item)
            )

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            Config.ANTHROPIC_API_KEY = original_anthropic
            Config.SLACK_BOT_TOKEN = original_slack
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_export_ops_reports_saves_expected_files(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-cli-ops-export-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            suite_args = SimpleNamespace(
                output_dir=os.path.join(temp_dir, "suite"),
                json=True,
            )
            __import__("asyncio").run(_run_smoke_suite(suite_args))

            export_args = SimpleNamespace(
                output_dir=os.path.join(temp_dir, "ops_export"),
                limit=5,
                needs_after=False,
                stalled_agenda=False,
                follow_up_needed=True,
                json=True,
                include_bundles=False,
                bundle_limit=3,
            )
            report = _export_ops_reports(export_args)

            self.assertTrue(os.path.exists(os.path.join(temp_dir, "ops_export", "meeting_list.md")))
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "ops_export", "dashboard.json")))
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "ops_export", "doctor.md")))
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "ops_export", "README.md")))
            self.assertTrue(report["filters"]["follow_up_needed"])

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            Config.ANTHROPIC_API_KEY = original_anthropic
            Config.SLACK_BOT_TOKEN = original_slack
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_export_ops_reports_can_include_bundles(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-cli-ops-export-bundles-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            suite_args = SimpleNamespace(
                output_dir=os.path.join(temp_dir, "suite"),
                json=True,
            )
            __import__("asyncio").run(_run_smoke_suite(suite_args))

            export_args = SimpleNamespace(
                output_dir=os.path.join(temp_dir, "ops_export"),
                limit=2,
                needs_after=False,
                stalled_agenda=False,
                follow_up_needed=False,
                json=True,
                include_bundles=True,
                bundle_limit=2,
            )
            report = _export_ops_reports(export_args)

            self.assertEqual(len(report["bundles"]), 2)
            first_bundle = report["bundles"][0]
            self.assertTrue(os.path.exists(first_bundle["markdown"]))
            self.assertTrue(os.path.exists(first_bundle["json"]))

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            Config.ANTHROPIC_API_KEY = original_anthropic
            Config.SLACK_BOT_TOKEN = original_slack
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_run_smoke_suite_saves_index_and_bundles(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-cli-suite-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            output_dir = os.path.join(temp_dir, "suite")
            args = SimpleNamespace(
                output_dir=output_dir,
                json=True,
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                success = __import__("asyncio").run(_run_smoke_suite(args))

            self.assertTrue(success)
            payload = json.loads(buffer.getvalue())
            self.assertTrue(payload["all_passed"])
            self.assertEqual(payload["scenario_count"], 3)
            self.assertTrue(os.path.exists(os.path.join(output_dir, "README.md")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "suite_report.json")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "client_bundle.md")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "internal_bundle.json")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "review_bundle.md")))

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            Config.ANTHROPIC_API_KEY = original_anthropic
            Config.SLACK_BOT_TOKEN = original_slack
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_run_demo_generates_suite_and_ops_outputs(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-cli-demo-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            output_dir = os.path.join(temp_dir, "demo")
            args = SimpleNamespace(
                output_dir=output_dir,
                json=True,
                bundle_limit=2,
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                success = __import__("asyncio").run(_run_demo(args))

            self.assertTrue(success)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["scenario_count"], 3)
            self.assertTrue(payload["all_passed"])
            self.assertEqual(payload["bundle_count"], 2)
            self.assertIn("featured_meetings", payload)
            self.assertEqual(len(payload["featured_meetings"]), 3)
            self.assertIn("bundle_command", payload["featured_meetings"][0])
            self.assertIn("status_command", payload["featured_meetings"][0])
            self.assertTrue(os.path.exists(os.path.join(output_dir, "README.md")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "playbook.md")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "demo_report.json")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "doctor_snapshot.md")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "doctor_snapshot.json")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "smoke_suite", "suite_report.json")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "ops_export", "README.md")))

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            Config.ANTHROPIC_API_KEY = original_anthropic
            Config.SLACK_BOT_TOKEN = original_slack
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_list_meeting_states_returns_recent_entries_after_suite(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-cli-list-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            args = SimpleNamespace(
                output_dir=os.path.join(temp_dir, "suite"),
                json=True,
            )
            __import__("asyncio").run(_run_smoke_suite(args))

            entries = _list_meeting_states(limit=2)

            self.assertEqual(len(entries), 2)
            self.assertIn("meeting_id", entries[0])
            self.assertIn("updated_at", entries[0])

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            Config.ANTHROPIC_API_KEY = original_anthropic
            Config.SLACK_BOT_TOKEN = original_slack
            Config.TRELLO_API_KEY = original_trello_key
            Config.TRELLO_API_TOKEN = original_trello_token
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_dashboard_can_be_built_after_suite(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        original_anthropic = Config.ANTHROPIC_API_KEY
        original_slack = Config.SLACK_BOT_TOKEN
        original_trello_key = Config.TRELLO_API_KEY
        original_trello_token = Config.TRELLO_API_TOKEN

        temp_dir = tempfile.mkdtemp(prefix="meetagain-cli-dashboard-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir
            Config.ANTHROPIC_API_KEY = ""
            Config.SLACK_BOT_TOKEN = ""
            Config.TRELLO_API_KEY = ""
            Config.TRELLO_API_TOKEN = ""

            args = SimpleNamespace(
                output_dir=os.path.join(temp_dir, "suite"),
                json=True,
            )
            __import__("asyncio").run(_run_smoke_suite(args))

            entries = _list_meeting_states(limit=10)
            dashboard = _build_dashboard(entries)

            self.assertGreaterEqual(dashboard["total_meetings"], 3)
            self.assertIn("recent_meetings", dashboard)

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
