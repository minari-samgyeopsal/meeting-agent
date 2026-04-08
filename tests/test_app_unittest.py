import unittest
from asyncio import run
from unittest.mock import patch

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.app import (
    _emit_say_response,
    _decorate_recent_entries,
    _help_text,
    _normalize_natural_command,
    _parse_create_command,
    _parse_ops_arguments,
    _resolve_meeting_reference,
    dispatch_channel_message_event,
    dispatch_text_command,
    dispatch_message_event,
)
from src.utils.meeting_state import resolve_auto_rerun_stage
from src.utils.ops_formatter import format_dashboard_snapshot, format_doctor_summary, format_recent_meetings
from src.utils.status_formatter import format_meeting_status


class AppUnitTest(unittest.TestCase):
    def test_parse_structured_create_command(self):
        parsed = _parse_create_command(
            "create 카카오 미팅|2026-03-25T15:00:00|2026-03-25T16:00:00|user@kakao.com|서비스 소개"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["title"], "카카오 미팅")
        self.assertEqual(parsed["attendees"], ["user@kakao.com"])
        self.assertEqual(parsed["agenda"], "서비스 소개")

    def test_parse_semi_natural_create_command(self):
        parsed = _parse_create_command(
            "create 내일 15:00 카카오 미팅 with user@kakao.com, me@parametacorp.com about 서비스 소개"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["title"], "카카오 미팅")
        self.assertEqual(parsed["attendees"], ["user@kakao.com", "me@parametacorp.com"])
        self.assertEqual(parsed["agenda"], "서비스 소개")
        self.assertEqual(parsed["start_time"].hour, 15)
        self.assertEqual(parsed["end_time"].hour, 16)

    def test_parse_invalid_create_command_returns_none(self):
        self.assertIsNone(_parse_create_command("create something invalid"))

    def test_parse_structured_create_command_with_template(self):
        parsed = _parse_create_command(
            "create 카카오 미팅|2026-03-25T15:00:00|2026-03-25T16:00:00|user@kakao.com|서비스 소개|client"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["template"], "client")

    def test_parse_semi_natural_create_command_with_template(self):
        parsed = _parse_create_command(
            "create 내일 15:00 카카오 미팅 with user@kakao.com about 서비스 소개 template review"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["template"], "review")
        self.assertEqual(parsed["agenda"], "서비스 소개")

    def test_parse_semi_natural_create_command_with_pm_expression(self):
        parsed = _parse_create_command(
            "create 내일 오후 3:00 카카오 미팅 with user@kakao.com about 서비스 소개"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["start_time"].hour, 15)
        self.assertEqual(parsed["end_time"].hour, 16)

    def test_parse_semi_natural_create_command_with_am_expression(self):
        parsed = _parse_create_command(
            "create 오늘 오전 10:30 내부 싱크 with me@parametacorp.com"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["start_time"].hour, 10)
        self.assertEqual(parsed["start_time"].minute, 30)

    def test_help_text_contains_operational_commands(self):
        rendered = _help_text()

        self.assertIn("/meetagain help", rendered)
        self.assertIn("/meetagain list [limit]", rendered)
        self.assertIn("/meetagain bundle <meeting_id>", rendered)
        self.assertIn("/meetagain dashboard [limit] [needs-after|stalled-agenda|follow-up]", rendered)
        self.assertIn("/meetagain doctor [limit] [needs-after|stalled-agenda|follow-up]", rendered)
        self.assertIn("`latest`, `최근`, `방금`", rendered)

    def test_resolve_meeting_reference_returns_latest(self):
        with patch("src.app._list_meeting_states", return_value=[{"meeting_id": "m-latest"}]):
            self.assertEqual(_resolve_meeting_reference("latest"), "m-latest")
            self.assertEqual(_resolve_meeting_reference("최근"), "m-latest")
            self.assertEqual(_resolve_meeting_reference("방금"), "m-latest")

    def test_resolve_meeting_reference_returns_none_when_no_latest(self):
        with patch("src.app._list_meeting_states", return_value=[]):
            self.assertIsNone(_resolve_meeting_reference("latest"))

    def test_parse_ops_arguments_supports_limit_and_filters(self):
        limit, filters = _parse_ops_arguments(["7", "needs-after", "follow-up"], default_limit=5)

        self.assertEqual(limit, 7)
        self.assertTrue(filters["needs_after"])
        self.assertTrue(filters["follow_up_needed"])
        self.assertFalse(filters["stalled_agenda"])

    def test_normalize_natural_command_maps_korean_phrases(self):
        self.assertEqual(_normalize_natural_command("오늘 미팅 브리핑해줘"), "before")
        self.assertEqual(_normalize_natural_command("오늘미팅 브리핑해줘"), "before")
        self.assertEqual(_normalize_natural_command("오늘 미팅일정 브리핑해줘"), "before")
        self.assertEqual(_normalize_natural_command("방금 미팅 정리해줘"), "pipeline latest")
        self.assertEqual(_normalize_natural_command("방금 미팅 상태 보여줘"), "status latest")
        self.assertEqual(_normalize_natural_command("운영 상태 보여줘"), "doctor")

    def test_format_recent_meetings_contains_next_stage(self):
        rendered = format_recent_meetings(
            [
                {
                    "meeting_id": "m1",
                    "title": "카카오 미팅",
                    "phase": "after",
                    "next_stage": "after",
                    "template": "client",
                    "updated_at": "2026-03-25T18:00:00",
                    "artifact_count": 3,
                    "agenda_progress": "1/2",
                    "attention_flags": ["after 미완료", "어젠다 미완료"],
                    "status_command": "/meetagain status m1",
                    "recommended_command": "/meetagain rerun m1 after",
                }
            ]
        )

        self.assertIn("최근 미팅", rendered)
        self.assertIn("m1 | 카카오 미팅 | phase=after | next=after", rendered)
        self.assertIn("template=client | updated_at=2026-03-25T18:00:00 | artifacts=3 | agenda=1/2", rendered)
        self.assertIn("flags: after 미완료, 어젠다 미완료", rendered)
        self.assertIn("status: /meetagain status m1", rendered)
        self.assertIn("action: /meetagain rerun m1 after", rendered)

    def test_format_dashboard_snapshot_contains_sections(self):
        rendered = format_dashboard_snapshot(
            {
                "total_meetings": 3,
                "completion_rate": "2/3 (66%)",
                "needs_after_count": 1,
                "stalled_agenda_count": 1,
                "follow_up_needed_count": 1,
                "recent_meetings": [
                    {
                        "meeting_id": "m1",
                        "title": "카카오 미팅",
                        "phase": "after",
                        "recommended_command": "python3 -m src.cli bundle --meeting-id m1",
                    }
                ],
                "needs_after": [
                    {
                        "meeting_id": "m2",
                        "title": "내부 싱크",
                        "reason": "After 후속 처리가 덜 끝남",
                        "recommended_command": "python3 -m src.cli rerun --meeting-id m2 --stage after",
                    }
                ],
                "stalled_agenda": [
                    {
                        "meeting_id": "m3",
                        "title": "분기 리뷰",
                        "agenda_progress": "1/3",
                        "recommended_command": "python3 -m src.cli bundle --meeting-id m3",
                    }
                ],
            }
        )

        self.assertIn("대시보드 요약", rendered)
        self.assertIn("최근 미팅", rendered)
        self.assertIn("status: /meetagain status m1", rendered)
        self.assertIn("action: /meetagain bundle m1", rendered)
        self.assertIn("After 확인 필요", rendered)
        self.assertIn("어젠다 체크 지연", rendered)
        self.assertIn("action: /meetagain rerun m2 after", rendered)
        self.assertIn("action: /meetagain bundle m3", rendered)
        self.assertIn("추천 작업", rendered)
        self.assertIn("/meetagain doctor 5 needs-after", rendered)
        self.assertIn("/meetagain dashboard 10 stalled-agenda", rendered)

    def test_format_doctor_summary_contains_recommendations(self):
        rendered = format_doctor_summary(
            {
                "mode": "dry_run",
                "meeting_state_count": 3,
                "env": {"DRY_RUN": True},
                "live_checks": {
                    "slack_ready": True,
                    "trello_ready": True,
                    "anthropic_ready": False,
                    "gws_cli_ready": False,
                    "core_live_ready": False,
                },
                "filesystem": {"cache_dir_exists": True, "dry_run_drive_exists": True},
                "latest_meeting": {"meeting_id": "m1", "phase": "after"},
                "recommendations": [
                    "python3 -m src.cli bundle --meeting-id m1",
                    "python3 -m src.cli status --meeting-id m1",
                    "python3 -m src.cli ops-export --include-bundles",
                ],
            }
        )

        self.assertIn("운영 점검", rendered)
        self.assertIn("추천 작업", rendered)
        self.assertIn("Slack 준비: True", rendered)
        self.assertIn("gws CLI 준비: False", rendered)
        self.assertIn("Live 핵심 준비: False", rendered)
        self.assertIn("status: /meetagain status m1", rendered)
        self.assertIn("action: /meetagain bundle m1", rendered)
        self.assertIn("/meetagain bundle m1", rendered)
        self.assertIn("/meetagain status m1", rendered)
        self.assertIn("ops-export --include-bundles", rendered)

    def test_decorate_recent_entries_adds_next_stage(self):
        decorated = _decorate_recent_entries(
            [
                {
                    "meeting_id": "m1",
                    "notes_generated": True,
                    "after_completed": True,
                    "follow_up_needed": True,
                    "follow_up_calendar_created": False,
                    "artifacts": [
                        {"type": "slack_summary", "path": "GeneratedDrafts/m1_slack_summary.md"},
                        {"type": "follow_up_meeting", "path": "GeneratedDrafts/m1_follow_up_meeting.md"},
                    ],
                    "registered_agenda_count": 4,
                    "agenda_status_count": 2,
                }
            ]
        )

        self.assertEqual(decorated[0]["next_stage"], "after")
        self.assertEqual(decorated[0]["artifact_count"], 2)
        self.assertEqual(decorated[0]["agenda_progress"], "2/4")
        self.assertEqual(decorated[0]["attention_flags"], ["transcript 없음", "어젠다 미완료", "후속 미팅 대기"])
        self.assertEqual(decorated[0]["status_command"], "/meetagain status m1")
        self.assertEqual(decorated[0]["recommended_command"], "/meetagain rerun m1 after")

    def test_dispatch_text_command_returns_help_for_help(self):
        rendered = run(dispatch_text_command("help"))
        self.assertIn("/meetagain help", rendered)

    def test_dispatch_text_command_supports_natural_before_phrase(self):
        async def _send_briefing(meeting):
            return True

        with patch("src.app.BeforeAgent") as mock_agent_cls:
            mock_agent = mock_agent_cls.return_value
            mock_agent.calendar_svc.get_upcoming_meetings.return_value = [
                type(
                    "Meeting",
                    (),
                    {
                        "id": "m-kakao",
                        "title": "카카오 미팅",
                        "attendees": ["minwhan@kakao.com"],
                        "is_external": True,
                    },
                )()
            ]
            mock_agent.send_briefing.side_effect = _send_briefing
            mock_agent.drive_svc.load_generated_draft.return_value = "카카오 브리핑 본문"
            rendered = run(dispatch_text_command("오늘 미팅 브리핑해줘"))
        self.assertEqual(rendered, "카카오 브리핑 본문")

    def test_dispatch_text_command_supports_natural_pipeline_phrase(self):
        async def _process_meeting(meeting_id, trigger_after_agent=False):
            self.assertEqual(meeting_id, "m-latest")
            self.assertTrue(trigger_after_agent)
            return True

        with patch("src.app._list_meeting_states", return_value=[{"meeting_id": "m-latest"}]):
            with patch("src.agents.during_agent.DuringAgent.process_meeting", side_effect=_process_meeting):
                rendered = run(dispatch_text_command("방금 미팅 정리해줘"))
        self.assertIn("✅ 회의록 생성 완료", rendered)

    def test_dispatch_text_command_supports_natural_result_phrase(self):
        with patch("src.app._list_meeting_states", return_value=[{"meeting_id": "m-latest"}]):
            with patch(
                "src.services.drive_service.DriveService.load_meeting_state",
                return_value={"meeting_id": "m-latest", "after_completed": True},
            ):
                with patch(
                    "src.app._build_meeting_bundle",
                    return_value={
                        "meeting_id": "m-latest",
                        "state": {
                            "title": "카카오 미팅",
                            "after_completed": True,
                            "action_item_count": 1,
                            "decision_count": 1,
                            "contact_update_count": 1,
                            "follow_up_needed": True,
                        },
                        "notes": {"client": "ok", "internal": "ok"},
                    },
                ):
                    with patch(
                        "src.services.drive_service.DriveService.load_meeting_notes",
                        return_value="## 주요 결론\n- 1단계 파일럿: 카카오 사내 임직원 인증 모듈 (500명)\n\n## To Do\n- [류혁곤] 기술 연동 문서 발송 → 3/31까지\n- [김민환] 내부 기술팀 검토 요청 → 3/31까지\n",
                    ):
                        rendered = run(dispatch_text_command("방금 미팅 결과 보여줘"))
        self.assertIsInstance(rendered, dict)
        self.assertIn("✅ 카카오 미팅 결과", rendered["text"])
        self.assertIn("• 1단계 파일럿: 카카오 사내 임직원 인증 모듈 (500명)", rendered["text"])
        self.assertIn("• [류혁곤] 기술 연동 문서 발송 → 3/31까지", rendered["text"])
        self.assertIn("• [김민환] 내부 기술팀 검토 요청 → 3/31까지", rendered["text"])
        self.assertEqual(rendered["blocks"][-1]["type"], "actions")

    def test_dispatch_text_command_supports_natural_status_phrase(self):
        with patch("src.app._list_meeting_states", return_value=[{"meeting_id": "m1"}]):
            with patch(
                "src.services.drive_service.DriveService.load_meeting_state",
                return_value={
                    "meeting_id": "m1",
                    "title": "카카오 미팅",
                    "phase": "after",
                    "agenda_status_count": 3,
                    "registered_agenda_count": 3,
                    "decision_count": 1,
                    "action_item_count": 2,
                    "assignee_dm_count": 1,
                    "reminder_count": 1,
                    "contact_update_count": 1,
                    "follow_up_needed": True,
                },
            ):
                rendered = run(dispatch_text_command("방금 미팅 상태 보여줘"))
        self.assertIn("📌 카카오 미팅 진행 상태", rendered)
        self.assertIn("• 어젠다 진행률: 3/3", rendered)

    def test_dispatch_message_event_routes_channel_monitor_for_public_channel(self):
        async def _handle_channel_message(event, client=None):
            return {"text": "archive proposal", "blocks": [{"type": "actions"}]}

        with patch("src.app.ChannelMonitorAgent") as mock_agent_cls:
            mock_agent = mock_agent_cls.return_value
            mock_agent.handle_channel_message.side_effect = _handle_channel_message
            rendered = run(
                dispatch_message_event(
                    {
                        "channel_type": "channel",
                        "channel": "C123",
                        "text": "외부 미팅 정리와 후속 요청입니다.",
                        "ts": "123.456",
                    },
                    client=None,
                )
            )

        self.assertEqual(rendered["text"], "archive proposal")

    def test_dispatch_message_event_preserves_dm_flow_when_channel_monitor_returns_none(self):
        with patch("src.app.ChannelMonitorAgent") as mock_agent_cls:
            mock_agent = mock_agent_cls.return_value
            async def _handle_channel_message(event, client=None):
                return None
            mock_agent.handle_channel_message.side_effect = _handle_channel_message
            rendered = run(
                dispatch_message_event(
                    {"channel_type": "im", "text": "help", "ts": "1"},
                    client=None,
                )
        )
        self.assertIn("/meetagain help", rendered)

    def test_emit_say_response_supports_dict_payload(self):
        captured = {}

        def _say(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        _emit_say_response(_say, {"text": "hello", "thread_ts": "123.456", "blocks": [{"type": "section"}]})
        self.assertEqual(captured["args"], ())
        self.assertEqual(captured["kwargs"]["text"], "hello")
        self.assertEqual(captured["kwargs"]["thread_ts"], "123.456")

    def test_dispatch_channel_message_event_returns_none_for_dm(self):
        rendered = run(dispatch_channel_message_event({"channel_type": "im", "text": "안녕하세요", "ts": "1"}))
        self.assertIsNone(rendered)

    def test_dispatch_text_command_before_returns_briefing_summary(self):
        async def _run_daily_briefing():
            return True

        with patch("src.app.BeforeAgent") as mock_agent_cls:
            mock_agent = mock_agent_cls.return_value
            mock_agent.run_daily_briefing.side_effect = _run_daily_briefing
            mock_agent.drive_svc.load_generated_draft.return_value = "브리핑 초안 예시입니다. 고객 현황과 준비 항목이 정리되어 있습니다."

            with patch(
                "src.app._list_meeting_states",
                return_value=[
                    {
                        "meeting_id": "m-briefing",
                        "title": "카카오 미팅",
                        "start_time": "2026-03-26T08:00:00",
                        "before_briefing_created": True,
                    }
                ],
            ):
                rendered = run(dispatch_text_command("before"))

        self.assertIn("오늘 브리핑 요약", rendered)
        self.assertIn("브리핑 생성 수: 1", rendered)
        self.assertIn("카카오 미팅", rendered)
        self.assertIn("브리핑 초안 예시입니다.", rendered)

    def test_dispatch_text_command_list_returns_recent_summary(self):
        rendered = run(dispatch_text_command("list 2"))
        self.assertIn("최근 미팅", rendered)

    def test_dispatch_text_command_dashboard_returns_snapshot(self):
        rendered = run(dispatch_text_command("dashboard 3"))
        self.assertIn("대시보드 요약", rendered)

    def test_dispatch_text_command_doctor_returns_summary(self):
        rendered = run(dispatch_text_command("doctor 2"))
        self.assertIn("운영 점검", rendered)

    def test_dispatch_text_command_bundle_returns_summary(self):
        with patch(
            "src.app._build_meeting_bundle",
            return_value={
                "meeting_id": "dry-run-meeting",
                "state": {
                    "title": "카카오 미팅",
                    "phase": "after",
                    "action_item_count": 3,
                    "decision_count": 2,
                    "registered_agenda_count": 4,
                    "agenda_status_count": 2,
                    "proposal_draft_created": True,
                    "research_draft_created": False,
                    "follow_up_needed": True,
                    "follow_up_draft_created": True,
                    "follow_up_calendar_created": False,
                },
                "transcript": "sample transcript",
                "notes": {"client": "client", "internal": "internal"},
                "artifacts": [
                    {"type": "slack_summary", "path": "GeneratedDrafts/dry-run-meeting_slack_summary.md"},
                    {"type": "proposal", "path": "GeneratedDrafts/dry-run-meeting_proposal.md"},
                ],
            },
        ):
            with patch(
                "src.services.drive_service.DriveService.load_meeting_notes",
                return_value="## 주요 결론\n- 1단계 파일럿: 카카오 사내 임직원 인증 모듈 (500명)\n\n## To Do\n- [류혁곤] 기술 연동 문서 발송 / 기한: 2026-03-31\n- [김민환] 내부 기술팀 검토 요청 / 기한: 2026-03-31\n",
            ):
                rendered = run(dispatch_text_command("bundle dry-run-meeting"))
        self.assertIsInstance(rendered, dict)
        self.assertIn("✅ 카카오 미팅 결과", rendered["text"])
        self.assertIn("📄 생성된 파일", rendered["text"])
        self.assertIn("• 1단계 파일럿: 카카오 사내 임직원 인증 모듈 (500명)", rendered["text"])
        self.assertIn("• [류혁곤] 기술 연동 문서 발송 / 기한: 2026-03-31", rendered["text"])
        self.assertIn("• [김민환] 내부 기술팀 검토 요청 / 기한: 2026-03-31", rendered["text"])
        self.assertEqual(rendered["blocks"][-1]["type"], "actions")

    def test_dispatch_text_command_status_supports_latest_reference(self):
        with patch("src.app._list_meeting_states", return_value=[{"meeting_id": "m1"}]):
            with patch(
                "src.services.drive_service.DriveService.load_meeting_state",
                return_value={"meeting_id": "m1", "title": "카카오 미팅", "phase": "before"},
            ):
                rendered = run(dispatch_text_command("status latest"))
        self.assertIn("미팅 상태: m1", rendered)

    def test_dispatch_text_command_pipeline_requires_latest_when_missing(self):
        with patch("src.app._list_meeting_states", return_value=[]):
            rendered = run(dispatch_text_command("pipeline latest"))
        self.assertIn("최근 미팅이 없습니다", rendered)

    def test_dispatch_text_command_supports_filtered_dashboard(self):
        rendered = run(dispatch_text_command("dashboard 3 follow-up"))
        self.assertIn("대시보드 요약", rendered)

    def test_dispatch_text_command_supports_filtered_doctor(self):
        rendered = run(dispatch_text_command("doctor 3 needs-after"))
        self.assertIn("운영 점검", rendered)

    def test_format_meeting_status_contains_flags(self):
        rendered = format_meeting_status(
            {
                "meeting_id": "m1",
                "title": "카카오 미팅",
                "phase": "after",
                "updated_at": "2026-03-25T17:20:00",
                "template": "client",
                "template_source": "inferred",
                "briefing_sent": True,
                "before_briefing_created": True,
                "channel_share_created": False,
                "agenda_registered": True,
                "transcript_collected": True,
                "notes_generated": True,
                "after_completed": False,
                "registered_agenda_count": 2,
                "agenda_status_count": 1,
                "contact_update_count": 1,
                "assignee_dm_count": 2,
                "reminder_count": 1,
                "proposal_draft_created": True,
                "research_draft_created": False,
                "follow_up_needed": True,
                "follow_up_draft_created": True,
                "follow_up_calendar_created": True,
                "action_item_count": 2,
                "decision_count": 1,
                "artifacts": [{"type": "proposal", "path": "GeneratedDrafts/m1_proposal.md"}],
            }
        )

        self.assertIn("미팅 상태: m1", rendered)
        self.assertIn("- 현재 단계: after", rendered)
        self.assertIn("- 마지막 갱신: 2026-03-25T17:20:00", rendered)
        self.assertIn("- 템플릿: client", rendered)
        self.assertIn("- 템플릿 출처: inferred", rendered)
        self.assertIn("- 브리핑 초안 생성: True", rendered)
        self.assertIn("- 채널 공유 초안 생성: False", rendered)
        self.assertIn("- 등록 어젠다 수: 2", rendered)
        self.assertIn("- 어젠다 체크 수: 1", rendered)
        self.assertIn("- 어젠다 진행률: 1/2 (50%)", rendered)
        self.assertIn("- 액션아이템 수: 2", rendered)
        self.assertIn("- 담당자 DM 수: 2", rendered)
        self.assertIn("- 리마인더 수: 1", rendered)
        self.assertIn("- Contacts 업데이트 수: 1", rendered)
        self.assertIn("- 제안서 초안 생성: True", rendered)
        self.assertIn("- 리서치 초안 생성: False", rendered)
        self.assertIn("- 후속 미팅 필요: True", rendered)
        self.assertIn("- 후속 미팅 초안 생성: True", rendered)
        self.assertIn("- 후속 미팅 캘린더 초안 생성: True", rendered)
        self.assertIn("- 산출물 요약: proposal 1개", rendered)
        self.assertIn("[proposal] GeneratedDrafts/m1_proposal.md", rendered)
        self.assertIn("- 다음 권장 작업:", rendered)

    def test_format_meeting_status_recommends_transcript_when_missing(self):
        rendered = format_meeting_status(
            {
                "meeting_id": "m2",
                "title": "카카오 미팅",
                "phase": "before",
                "briefing_sent": True,
                "agenda_registered": True,
                "transcript_collected": False,
                "notes_generated": False,
            }
        )

        self.assertIn("transcript를 업로드하거나 During를 재실행하세요", rendered)

    def test_format_meeting_status_recommends_missing_follow_up_artifact(self):
        rendered = format_meeting_status(
            {
                "meeting_id": "m3",
                "title": "카카오 미팅",
                "phase": "after",
                "briefing_sent": True,
                "agenda_registered": True,
                "transcript_collected": True,
                "notes_generated": True,
                "after_completed": True,
                "has_follow_up_meeting": True,
                "artifacts": [{"type": "slack_summary", "path": "GeneratedDrafts/m3_slack_summary.md"}],
            }
        )

        self.assertIn("후속 미팅 초안을 다시 생성하세요", rendered)

    def test_format_meeting_status_recommends_follow_up_calendar_retry(self):
        rendered = format_meeting_status(
            {
                "meeting_id": "m3-2",
                "title": "카카오 미팅",
                "phase": "after",
                "briefing_sent": True,
                "agenda_registered": True,
                "transcript_collected": True,
                "notes_generated": True,
                "after_completed": True,
                "follow_up_needed": True,
                "follow_up_draft_created": True,
                "follow_up_calendar_created": False,
                "artifacts": [
                    {"type": "slack_summary", "path": "GeneratedDrafts/m3_slack_summary.md"},
                    {"type": "follow_up_meeting", "path": "GeneratedDrafts/m3_follow_up_meeting.md"},
                ],
            }
        )

        self.assertIn("후속 미팅 캘린더 초안을 다시 생성하거나 검토하세요", rendered)

    def test_format_meeting_status_recommends_agenda_review_when_counts_lag(self):
        rendered = format_meeting_status(
            {
                "meeting_id": "m4",
                "title": "카카오 미팅",
                "phase": "during",
                "briefing_sent": True,
                "agenda_registered": True,
                "transcript_collected": True,
                "notes_generated": True,
                "registered_agenda_count": 4,
                "agenda_status_count": 2,
            }
        )

        self.assertIn("어젠다 달성 체크를 검토하고 During를 다시 실행하세요", rendered)

    def test_resolve_auto_rerun_stage_prefers_after_when_follow_up_artifact_missing(self):
        stage = resolve_auto_rerun_stage(
            {
                "notes_generated": True,
                "after_completed": True,
                "has_follow_up_meeting": True,
                "artifacts": [{"type": "slack_summary", "path": "GeneratedDrafts/m1_slack_summary.md"}],
            }
        )

        self.assertEqual(stage, "after")

    def test_resolve_auto_rerun_stage_prefers_after_when_follow_up_calendar_missing(self):
        stage = resolve_auto_rerun_stage(
            {
                "notes_generated": True,
                "after_completed": True,
                "follow_up_needed": True,
                "follow_up_calendar_created": False,
                "artifacts": [
                    {"type": "slack_summary", "path": "GeneratedDrafts/m1_slack_summary.md"},
                    {"type": "follow_up_meeting", "path": "GeneratedDrafts/m1_follow_up_meeting.md"},
                ],
            }
        )

        self.assertEqual(stage, "after")


if __name__ == "__main__":
    unittest.main()
