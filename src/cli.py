"""
Meetagain 수동 실행 CLI

Slack 진입점 구현 전까지 Before / During / After 에이전트를
터미널에서 직접 실행할 수 있는 최소 진입점입니다.
"""

import argparse
import asyncio
import io
import json
from pathlib import Path
import shutil
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from src.agents.before_agent import BeforeAgent
from src.agents.during_agent import DuringAgent
from src.agents.after_agent import AfterAgent
from src.agents.channel_monitor_agent import ChannelMonitorAgent
from src.services.slack_service import SlackService
from src.utils.config import Config
from src.utils.meeting_state import get_follow_up_needed, resolve_auto_rerun_stage
from src.utils.status_formatter import format_meeting_status


async def main():
    parser = argparse.ArgumentParser(description="Meetagain manual runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    before_parser = subparsers.add_parser("before", help="Before Agent 실행")
    before_parser.add_argument(
        "--update-company-knowledge",
        action="store_true",
        help="company_knowledge.md 갱신만 실행",
    )

    create_parser = subparsers.add_parser("create-meeting", help="미팅 생성 + 브리핑 연계")
    create_parser.add_argument("--title", required=True, help="미팅 제목")
    create_parser.add_argument("--start", required=True, help="시작 시각 ISO format")
    create_parser.add_argument("--end", required=True, help="종료 시각 ISO format")
    create_parser.add_argument(
        "--attendee",
        action="append",
        required=True,
        help="참석자 이메일, 여러 번 반복 가능",
    )
    create_parser.add_argument("--agenda", default="", help="어젠다 텍스트")
    create_parser.add_argument(
        "--template",
        choices=["internal", "client", "review"],
        help="기본 어젠다 템플릿",
    )
    create_parser.add_argument("--share-channel", help="채널 공유용 채널명 또는 ID")

    during_parser = subparsers.add_parser("during", help="During Agent 실행")
    during_parser.add_argument("--meeting-id", required=True, help="Calendar event ID")
    during_parser.add_argument(
        "--transcript-file",
        help="Drive 대신 로컬 transcript 파일을 사용",
    )
    during_parser.add_argument(
        "--trigger-after-agent",
        action="store_true",
        help="During 완료 후 After Agent까지 연속 실행",
    )

    pipeline_parser = subparsers.add_parser("pipeline", help="During -> After 연속 실행")
    pipeline_parser.add_argument("--meeting-id", required=True, help="Calendar event ID")
    pipeline_parser.add_argument(
        "--transcript-file",
        help="Drive 대신 로컬 transcript 파일을 사용",
    )

    smoke_parser = subparsers.add_parser(
        "smoke",
        help="DRY_RUN 기준 Before -> During -> After -> 상태확인을 한 번에 실행",
    )
    smoke_parser.add_argument("--title", default="DRY RUN 외부 미팅", help="미팅 제목")
    smoke_parser.add_argument(
        "--start",
        default="2026-03-25T15:00:00",
        help="시작 시각 ISO format",
    )
    smoke_parser.add_argument(
        "--end",
        default="2026-03-25T16:00:00",
        help="종료 시각 ISO format",
    )
    smoke_parser.add_argument(
        "--attendee",
        action="append",
        help="참석자 이메일, 여러 번 반복 가능",
    )
    smoke_parser.add_argument("--agenda", default="", help="어젠다 텍스트")
    smoke_parser.add_argument(
        "--template",
        choices=["internal", "client", "review"],
        help="기본 어젠다 템플릿",
    )
    smoke_parser.add_argument(
        "--transcript-file",
        help="로컬 transcript 파일 경로",
    )
    smoke_parser.add_argument(
        "--transcript-text",
        help="직접 전달할 transcript 텍스트",
    )
    smoke_parser.add_argument(
        "--json",
        action="store_true",
        help="최종 상태를 JSON으로 출력",
    )
    smoke_parser.add_argument(
        "--bundle",
        action="store_true",
        help="최종 상태 대신 bundle 전체를 출력",
    )
    smoke_parser.add_argument(
        "--save-bundle",
        help="bundle 출력을 로컬 파일로 저장",
    )

    smoke_suite_parser = subparsers.add_parser(
        "smoke-suite",
        help="DRY_RUN 기준 client/internal/review 시나리오를 한 번에 검증",
    )
    smoke_suite_parser.add_argument(
        "--output-dir",
        help="suite 결과물을 저장할 디렉토리",
    )
    smoke_suite_parser.add_argument(
        "--json",
        action="store_true",
        help="suite 요약을 JSON으로 출력",
    )

    demo_parser = subparsers.add_parser(
        "demo",
        help="DRY_RUN 기준 시연용 smoke-suite + 운영 리포트를 한 번에 생성",
    )
    demo_parser.add_argument(
        "--output-dir",
        help="데모 결과물을 저장할 디렉토리",
    )
    demo_parser.add_argument(
        "--json",
        action="store_true",
        help="데모 요약을 JSON으로 출력",
    )
    demo_parser.add_argument(
        "--bundle-limit",
        type=int,
        default=3,
        help="ops-export에 포함할 bundle 최대 개수",
    )

    bundle_parser = subparsers.add_parser(
        "bundle",
        help="meeting_id 기준 transcript/회의록/draft/state를 한 번에 조회",
    )
    bundle_parser.add_argument("--meeting-id", required=True, help="Calendar event ID")
    bundle_parser.add_argument(
        "--json",
        action="store_true",
        help="텍스트 대신 JSON으로 출력",
    )
    bundle_parser.add_argument(
        "--save",
        help="bundle 출력을 로컬 파일로 저장",
    )

    list_parser = subparsers.add_parser(
        "list",
        help="최근 저장된 meeting state 목록 조회",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="출력할 최대 개수",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="목록을 JSON으로 출력",
    )
    list_parser.add_argument(
        "--save",
        help="목록 출력을 로컬 파일로 저장",
    )
    list_parser.add_argument(
        "--needs-after",
        action="store_true",
        help="After 확인이 필요한 미팅만 조회",
    )
    list_parser.add_argument(
        "--stalled-agenda",
        action="store_true",
        help="어젠다 체크가 지연된 미팅만 조회",
    )
    list_parser.add_argument(
        "--follow-up-needed",
        action="store_true",
        help="후속 미팅이 필요한 미팅만 조회",
    )

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="최근 meeting state 전체 요약과 주의 항목 조회",
    )
    dashboard_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="집계에 포함할 최대 개수",
    )
    dashboard_parser.add_argument(
        "--json",
        action="store_true",
        help="대시보드를 JSON으로 출력",
    )
    dashboard_parser.add_argument(
        "--save",
        help="대시보드 출력을 로컬 파일로 저장",
    )
    dashboard_parser.add_argument(
        "--needs-after",
        action="store_true",
        help="After 확인이 필요한 미팅만 집계",
    )
    dashboard_parser.add_argument(
        "--stalled-agenda",
        action="store_true",
        help="어젠다 체크가 지연된 미팅만 집계",
    )
    dashboard_parser.add_argument(
        "--follow-up-needed",
        action="store_true",
        help="후속 미팅이 필요한 미팅만 집계",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="DRY_RUN/캐시/meeting state 기준 운영 점검",
    )
    doctor_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="최근 미팅 샘플 최대 개수",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="점검 결과를 JSON으로 출력",
    )
    doctor_parser.add_argument(
        "--save",
        help="점검 결과를 로컬 파일로 저장",
    )
    doctor_parser.add_argument(
        "--needs-after",
        action="store_true",
        help="After 확인이 필요한 미팅 중심으로 점검",
    )
    doctor_parser.add_argument(
        "--stalled-agenda",
        action="store_true",
        help="어젠다 체크 지연 미팅 중심으로 점검",
    )
    doctor_parser.add_argument(
        "--follow-up-needed",
        action="store_true",
        help="후속 미팅 필요 미팅 중심으로 점검",
    )

    ops_export_parser = subparsers.add_parser(
        "ops-export",
        help="list/dashboard/doctor 결과를 한 번에 파일로 저장",
    )
    ops_export_parser.add_argument(
        "--output-dir",
        help="운영 리포트를 저장할 디렉토리",
    )
    ops_export_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="리포트에 포함할 최대 미팅 수",
    )
    ops_export_parser.add_argument(
        "--needs-after",
        action="store_true",
        help="After 확인이 필요한 미팅 중심으로 저장",
    )
    ops_export_parser.add_argument(
        "--stalled-agenda",
        action="store_true",
        help="어젠다 체크 지연 미팅 중심으로 저장",
    )
    ops_export_parser.add_argument(
        "--follow-up-needed",
        action="store_true",
        help="후속 미팅 필요 미팅 중심으로 저장",
    )
    ops_export_parser.add_argument(
        "--json",
        action="store_true",
        help="요약 메타데이터를 JSON으로 출력",
    )
    ops_export_parser.add_argument(
        "--include-bundles",
        action="store_true",
        help="최근 미팅 bundle도 함께 저장",
    )
    ops_export_parser.add_argument(
        "--bundle-limit",
        type=int,
        default=3,
        help="bundle을 저장할 최대 미팅 수",
    )

    status_parser = subparsers.add_parser("status", help="meeting_id 상태 조회")
    status_parser.add_argument("--meeting-id", required=True, help="Calendar event ID")
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="사람용 포맷 대신 JSON으로 출력",
    )

    after_parser = subparsers.add_parser("after", help="After Agent 실행")
    after_parser.add_argument("--meeting-id", required=True, help="Calendar event ID")

    channel_monitor_daily_parser = subparsers.add_parser(
        "channel-monitor-daily",
        help="전일 17시 ~ 당일 17시 기준 채널 메시지 배치 수집",
    )
    channel_monitor_daily_parser.add_argument("--channel", action="append", help="채널 ID 또는 이름, 여러 번 반복 가능")
    channel_monitor_daily_parser.add_argument("--window-end", help="기준 시각 ISO format")
    channel_monitor_daily_parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    channel_monitor_daily_parser.add_argument(
        "--send-dm-email",
        help="리뷰 큐를 보낼 Slack 사용자 이메일. 미지정 시 CHANNEL_MONITOR_REVIEW_DM_EMAIL 사용",
    )
    channel_monitor_daily_parser.add_argument(
        "--send-channel",
        help="리뷰 큐를 보낼 Slack 채널/DM 채널 ID. 미지정 시 CHANNEL_MONITOR_REVIEW_CHANNEL 사용",
    )

    rerun_parser = subparsers.add_parser("rerun", help="meeting_id 기준 단계 재실행")
    rerun_parser.add_argument("--meeting-id", required=True, help="Calendar event ID")
    rerun_parser.add_argument(
        "--stage",
        choices=["before", "during", "after", "pipeline", "auto"],
        default="auto",
        help="재실행할 단계",
    )

    args = parser.parse_args()

    if args.command == "before":
        if not Config.validate(["SLACK_BOT_TOKEN", "ANTHROPIC_API_KEY", "TRELLO_API_KEY", "TRELLO_API_TOKEN"]):
            raise SystemExit(1)
        agent = BeforeAgent()
        if args.update_company_knowledge:
            success = await agent.update_company_knowledge()
        else:
            success = await agent.run_daily_briefing()
        raise SystemExit(0 if success else 1)

    if args.command == "during":
        if not Config.validate(["ANTHROPIC_API_KEY"]):
            raise SystemExit(1)
        agent = DuringAgent()
        transcript_text = None
        if args.transcript_file:
            transcript_text = agent.load_transcript_from_file(args.transcript_file)
            if transcript_text is None:
                raise SystemExit(1)
        success = await agent.process_meeting(
            meeting_id=args.meeting_id,
            trigger_after_agent=args.trigger_after_agent,
            transcript_text=transcript_text,
        )
        raise SystemExit(0 if success else 1)

    if args.command == "after":
        if not Config.validate(["SLACK_BOT_TOKEN", "ANTHROPIC_API_KEY", "TRELLO_API_KEY", "TRELLO_API_TOKEN"]):
            raise SystemExit(1)
        agent = AfterAgent()
        success = await agent.process_meeting(args.meeting_id)
        raise SystemExit(0 if success else 1)

    if args.command == "channel-monitor-daily":
        if not Config.validate(["SLACK_BOT_TOKEN"]):
            raise SystemExit(1)
        channels = args.channel or Config.CHANNEL_MONITOR_TARGET_CHANNELS
        if not channels:
            print("수집할 채널이 없습니다. --channel 또는 CHANNEL_MONITOR_TARGET_CHANNELS를 설정하세요.")
            raise SystemExit(1)
        reference = datetime.fromisoformat(args.window_end) if args.window_end else None
        report = await ChannelMonitorAgent().run_daily_collection(channels=channels, reference=reference)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(_render_channel_monitor_daily_report(report))
        send_channel = getattr(args, "send_channel", None) or Config.CHANNEL_MONITOR_REVIEW_CHANNEL
        send_dm_email = getattr(args, "send_dm_email", None) or Config.CHANNEL_MONITOR_REVIEW_DM_EMAIL
        if send_channel or send_dm_email:
            delivery = _send_channel_monitor_review_queue(
                report,
                send_channel=send_channel,
                send_dm_email=send_dm_email,
            )
            print(delivery)
        raise SystemExit(0)

    if args.command == "pipeline":
        if not Config.validate(["ANTHROPIC_API_KEY"]):
            raise SystemExit(1)
        agent = DuringAgent()
        transcript_text = None
        if args.transcript_file:
            transcript_text = agent.load_transcript_from_file(args.transcript_file)
            if transcript_text is None:
                raise SystemExit(1)
        success = await agent.process_meeting(
            meeting_id=args.meeting_id,
            trigger_after_agent=True,
            transcript_text=transcript_text,
        )
        raise SystemExit(0 if success else 1)

    if args.command == "smoke":
        if not Config.validate(["SLACK_BOT_TOKEN", "ANTHROPIC_API_KEY", "TRELLO_API_KEY", "TRELLO_API_TOKEN"]):
            raise SystemExit(1)
        success = await _run_smoke_test(args)
        raise SystemExit(0 if success else 1)

    if args.command == "smoke-suite":
        if not Config.validate(["SLACK_BOT_TOKEN", "ANTHROPIC_API_KEY", "TRELLO_API_KEY", "TRELLO_API_TOKEN"]):
            raise SystemExit(1)
        success = await _run_smoke_suite(args)
        raise SystemExit(0 if success else 1)

    if args.command == "demo":
        if not Config.validate(["SLACK_BOT_TOKEN", "ANTHROPIC_API_KEY", "TRELLO_API_KEY", "TRELLO_API_TOKEN"]):
            raise SystemExit(1)
        success = await _run_demo(args)
        raise SystemExit(0 if success else 1)

    if args.command == "bundle":
        bundle = _build_meeting_bundle(args.meeting_id)
        if not bundle:
            print(f"bundle 생성 실패: {args.meeting_id}")
            raise SystemExit(1)
        _print_bundle(bundle, args.json, args.save)
        raise SystemExit(0)

    if args.command == "list":
        entries = _list_meeting_states(
            limit=args.limit,
            needs_after=getattr(args, "needs_after", False),
            stalled_agenda=getattr(args, "stalled_agenda", False),
            follow_up_needed=getattr(args, "follow_up_needed", False),
        )
        _print_meeting_state_list(entries, args.json, args.save)
        raise SystemExit(0)

    if args.command == "dashboard":
        entries = _list_meeting_states(
            limit=args.limit,
            needs_after=getattr(args, "needs_after", False),
            stalled_agenda=getattr(args, "stalled_agenda", False),
            follow_up_needed=getattr(args, "follow_up_needed", False),
        )
        dashboard = _build_dashboard(entries)
        _print_dashboard(dashboard, args.json, args.save)
        raise SystemExit(0)

    if args.command == "doctor":
        report = _build_doctor_report(
            limit=args.limit,
            needs_after=getattr(args, "needs_after", False),
            stalled_agenda=getattr(args, "stalled_agenda", False),
            follow_up_needed=getattr(args, "follow_up_needed", False),
        )
        _print_doctor_report(report, args.json, args.save)
        raise SystemExit(0)

    if args.command == "ops-export":
        report = _export_ops_reports(args)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(_render_ops_export_report(report))
        raise SystemExit(0)

    if args.command == "status":
        state = DuringAgent().drive_svc.load_meeting_state(args.meeting_id)
        if not state:
            print(f"상태 정보 없음: {args.meeting_id}")
            raise SystemExit(1)

        if args.json:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            print(format_meeting_status(state))
        raise SystemExit(0)

    if args.command == "create-meeting":
        if not Config.validate(["SLACK_BOT_TOKEN", "ANTHROPIC_API_KEY", "TRELLO_API_KEY", "TRELLO_API_TOKEN"]):
            raise SystemExit(1)

        agent = BeforeAgent()
        meeting = await agent.create_meeting_with_briefing(
            title=args.title,
            start_time=datetime.fromisoformat(args.start),
            end_time=datetime.fromisoformat(args.end),
            attendees=args.attendee,
            agenda=args.agenda,
            template=args.template,
            share_channel=args.share_channel,
        )
        raise SystemExit(0 if meeting else 1)

    if args.command == "rerun":
        stage = args.stage

        if stage in ("during", "pipeline", "auto"):
            if not Config.validate(["ANTHROPIC_API_KEY"]):
                raise SystemExit(1)
        else:
            if not Config.validate(["SLACK_BOT_TOKEN", "ANTHROPIC_API_KEY", "TRELLO_API_KEY", "TRELLO_API_TOKEN"]):
                raise SystemExit(1)

        success = await _rerun_meeting(args.meeting_id, stage)
        raise SystemExit(0 if success else 1)


async def _rerun_meeting(meeting_id: str, stage: str) -> bool:
    drive_svc = DuringAgent().drive_svc
    state = drive_svc.load_meeting_state(meeting_id)

    if stage == "auto":
        stage = resolve_auto_rerun_stage(state)

    if stage == "before":
        return await BeforeAgent().rerun_briefing_from_state(meeting_id)

    if stage == "during":
        return await DuringAgent().process_meeting(meeting_id)

    if stage == "after":
        return await AfterAgent().process_meeting(meeting_id)

    if stage == "pipeline":
        return await DuringAgent().process_meeting(meeting_id, trigger_after_agent=True)

    return False


async def _run_smoke_test(args: SimpleNamespace) -> bool:
    outcome = await _execute_smoke_scenario(args)
    if not outcome:
        return False

    state = outcome["state"]
    if getattr(args, "bundle", False) or getattr(args, "save_bundle", None):
        bundle = outcome["bundle"]
        if not bundle:
            print(f"bundle 생성 실패: {outcome['meeting_id']}")
            return False
        _print_bundle(bundle, args.json, getattr(args, "save_bundle", None))
    else:
        _print_status(state, args.json)
    return True


async def _run_smoke_suite(args: SimpleNamespace) -> bool:
    output_dir = Path(args.output_dir) if getattr(args, "output_dir", None) else _default_smoke_suite_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    scenarios = []
    for spec in _smoke_suite_specs():
        scenario_args = SimpleNamespace(
            title=spec["title"],
            start=spec["start"],
            end=spec["end"],
            attendee=spec["attendee"],
            agenda=spec["agenda"],
            template=spec["template"],
            transcript_file=None,
            transcript_text=spec["transcript_text"],
            json=False,
            bundle=True,
            save_bundle=None,
        )
        outcome = await _execute_smoke_scenario(scenario_args)
        if not outcome:
            return False

        bundle_path = output_dir / f"{spec['name']}_bundle.md"
        bundle_json_path = output_dir / f"{spec['name']}_bundle.json"
        _write_local_file(str(bundle_path), _render_bundle(outcome["bundle"], as_json=False))
        _write_local_file(str(bundle_json_path), _render_bundle(outcome["bundle"], as_json=True))

        state = outcome["state"]
        scenarios.append(
            {
                "name": spec["name"],
                "meeting_id": outcome["meeting_id"],
                "title": state.get("title", spec["title"]),
                "template": state.get("template", spec["template"]),
                "after_completed": state.get("after_completed", False),
                "proposal_draft_created": state.get("proposal_draft_created", False),
                "research_draft_created": state.get("research_draft_created", False),
                "follow_up_calendar_created": state.get("follow_up_calendar_created", False),
                "artifact_count": len(state.get("artifacts", [])),
                "bundle_markdown_path": str(bundle_path),
                "bundle_json_path": str(bundle_json_path),
            }
        )

    suite_report = {
        "generated_at": datetime.now().isoformat(),
        "output_dir": str(output_dir),
        "scenario_count": len(scenarios),
        "all_passed": all(scenario["after_completed"] for scenario in scenarios),
        "scenarios": scenarios,
    }
    _write_local_file(str(output_dir / "suite_report.json"), json.dumps(suite_report, ensure_ascii=False, indent=2))
    _write_local_file(str(output_dir / "README.md"), _render_smoke_suite_report(suite_report))

    if args.json:
        print(json.dumps(suite_report, ensure_ascii=False, indent=2))
    else:
        print(_render_smoke_suite_report(suite_report))

    return suite_report["all_passed"]


async def _execute_smoke_scenario(args: SimpleNamespace) -> Optional[dict]:
    before_agent = BeforeAgent()
    during_agent = DuringAgent()

    attendees = args.attendee or ["owner@parametacorp.com", "partner@example.com"]
    transcript_text = _resolve_smoke_transcript(args, during_agent)
    if transcript_text is None:
        return None

    meeting = await before_agent.create_meeting_with_briefing(
        title=args.title,
        start_time=datetime.fromisoformat(args.start),
        end_time=datetime.fromisoformat(args.end),
        attendees=attendees,
        agenda=args.agenda,
        template=args.template,
    )
    if not meeting:
        return None

    success = await during_agent.process_meeting(
        meeting_id=meeting.id,
        trigger_after_agent=True,
        transcript_text=transcript_text,
    )
    if not success:
        return None

    state = during_agent.drive_svc.load_meeting_state(meeting.id)
    if not state:
        print(f"상태 정보 없음: {meeting.id}")
        return None

    bundle = _build_meeting_bundle(meeting.id)
    return {
        "meeting_id": meeting.id,
        "meeting": meeting,
        "state": state,
        "bundle": bundle,
    }


def _resolve_smoke_transcript(args: SimpleNamespace, during_agent: DuringAgent) -> Optional[str]:
    if getattr(args, "transcript_text", None):
        return args.transcript_text

    transcript_file = getattr(args, "transcript_file", None)
    if transcript_file:
        return during_agent.load_transcript_from_file(transcript_file)

    return _build_smoke_transcript(args.title, args.agenda)


def _render_channel_monitor_daily_report(report: dict) -> str:
    lines = [
        "채널 모니터 일일 수집 결과",
        f"- 수집 창 시작: {report.get('window_start', '')}",
        f"- 수집 창 종료: {report.get('window_end', '')}",
        f"- 대상 채널: {', '.join(report.get('channels', [])) or '없음'}",
        f"- 스캔 메시지 수: {report.get('scanned_count', 0)}",
        f"- 제안 생성 수: {report.get('proposal_count', 0)}",
        f"- 리뷰 후보 수: {report.get('review_candidate_count', 0)}",
    ]
    for item in report.get("proposals", [])[:10]:
        headline = (item.get("text", "") or "").splitlines()[0]
        lines.append(
            f"- [{item.get('channel', '')}] {item.get('ts', '')} | score={item.get('score', 0)} | {headline}"
        )
    review_candidates = report.get("review_candidates", [])
    if review_candidates:
        lines.append("")
        lines.append("리뷰 후보")
        for item in review_candidates[:10]:
            lines.append(
                f"- [{item.get('channel', '')}] {item.get('ts', '')} | score={item.get('score', 0)} | "
                f"{item.get('headline', '')} | reasons={', '.join(item.get('reasons', []))}"
            )
    return "\n".join(lines)


def _send_channel_monitor_review_queue(
    report: dict,
    send_channel: Optional[str] = None,
    send_dm_email: Optional[str] = None,
) -> str:
    slack_svc = SlackService()
    payload = slack_svc.build_channel_monitor_review_queue_message(report)
    sent_followups = 0

    if send_channel:
        ts = slack_svc.send_message(send_channel, payload["text"], payload.get("blocks"))
        if ts:
            sent_followups = _send_channel_monitor_proposals(
                slack_svc=slack_svc,
                report=report,
                channel=send_channel,
            )
        return (
            f"리뷰 큐 전송: channel={send_channel} ts={ts or 'failed'} "
            f"(actionable_items={sent_followups})"
        )

    if send_dm_email:
        ts = slack_svc.send_dm(send_dm_email, payload["text"], payload.get("blocks"))
        if ts:
            dm_channel = _resolve_dm_channel_id(slack_svc, send_dm_email)
            if dm_channel:
                sent_followups = _send_channel_monitor_proposals(
                    slack_svc=slack_svc,
                    report=report,
                    channel=dm_channel,
                )
        return (
            f"리뷰 큐 전송: dm={send_dm_email} ts={ts or 'failed'} "
            f"(actionable_items={sent_followups})"
        )

    return "리뷰 큐 전송 대상이 설정되지 않았습니다."


def _resolve_dm_channel_id(slack_svc: SlackService, email: str) -> Optional[str]:
    try:
        if Config.DRY_RUN:
            return "DRYRUN_DM_CHANNEL"
        user_id = slack_svc.get_user_id(email)
        if not user_id or not slack_svc.client:
            return None
        response = slack_svc.client.conversations_open(users=[user_id])
        return response.get("channel", {}).get("id")
    except Exception:
        return None


def _send_channel_monitor_proposals(slack_svc: SlackService, report: dict, channel: str) -> int:
    count = 0
    for item in (report.get("proposals") or [])[:5]:
        blocks = item.get("blocks") or []
        text = item.get("text") or "Meetagain 아카이빙 제안"
        ts = slack_svc.send_message(channel, text, blocks)
        if ts:
            count += 1
    return count


def _build_smoke_transcript(title: str, agenda: str) -> str:
    agenda_lines = [line.strip().lstrip("-*• ").strip() for line in agenda.splitlines() if line.strip()]
    agenda_summary = ", ".join(agenda_lines) if agenda_lines else "서비스 소개와 다음 단계 협의"
    return (
        f"{title}에서 {agenda_summary}를 논의했고, 고객사는 제안서 초안과 시장 분석 리서치를 요청했으며 다음 주 후속 미팅도 필요하다고 합의했습니다.\n"
        "고객사는 레퍼런스 전달 이후 제안 방향을 다시 검토하자고 요청했습니다.\n"
        "홍길동이 레퍼런스 전달을 맡고, 김영희가 후속 일정 조율을 진행합니다."
    )


def _smoke_suite_specs() -> list:
    return [
        {
            "name": "client",
            "title": "카카오 미팅",
            "start": "2026-03-25T15:00:00",
            "end": "2026-03-25T16:00:00",
            "attendee": ["owner@parametacorp.com", "user@kakao.com"],
            "agenda": "- 서비스 소개\n- 다음 단계 협의",
            "template": "client",
            "transcript_text": (
                "카카오 미팅에서 서비스 소개와 다음 단계 협의를 논의했습니다.\n"
                "고객사는 제안서 초안과 시장 분석 리서치를 요청했고 다음 주 후속 미팅도 필요하다고 합의했습니다."
            ),
        },
        {
            "name": "internal",
            "title": "내부 전략 싱크",
            "start": "2026-03-26T10:00:00",
            "end": "2026-03-26T11:00:00",
            "attendee": ["owner@parametacorp.com", "teammate@parametacorp.com"],
            "agenda": "- 진행 상황 공유\n- 리스크 정리",
            "template": "internal",
            "transcript_text": (
                "내부 전략 싱크에서 진행 상황과 리스크를 정리했습니다.\n"
                "제안서 방향성과 시장 분석 리서치를 내부적으로 준비하고 후속 미팅 필요성도 확인했습니다."
            ),
        },
        {
            "name": "review",
            "title": "분기 리뷰 미팅",
            "start": "2026-03-27T14:00:00",
            "end": "2026-03-27T15:00:00",
            "attendee": ["owner@parametacorp.com", "lead@parametacorp.com"],
            "agenda": "- 목표 대비 결과 리뷰\n- 개선 액션 도출",
            "template": "review",
            "transcript_text": (
                "분기 리뷰 미팅에서 목표 대비 결과 리뷰와 개선 액션을 논의했습니다.\n"
                "다음 제안서 업데이트와 시장 분석 리서치를 이어가고 후속 리뷰 미팅도 진행하기로 했습니다."
            ),
        },
    ]


def _default_smoke_suite_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("artifacts") / f"smoke_suite_{timestamp}"


def _default_demo_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("artifacts") / f"demo_{timestamp}"


def _print_status(state: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
    else:
        print(format_meeting_status(state))


def _build_meeting_bundle(meeting_id: str) -> Optional[dict]:
    drive_svc = DuringAgent().drive_svc
    state = drive_svc.load_meeting_state(meeting_id)
    if not state:
        return None

    artifacts = []
    for artifact in state.get("artifacts", []):
        path = artifact.get("path", "")
        artifacts.append(
            {
                "type": artifact.get("type", "unknown"),
                "path": path,
                "content": drive_svc.load_text_file(path) if path else None,
            }
        )

    return {
        "meeting_id": meeting_id,
        "state": state,
        "transcript": drive_svc.load_meeting_transcript(meeting_id),
        "notes": {
            "client": drive_svc.load_meeting_notes(meeting_id, version="client"),
            "internal": drive_svc.load_meeting_notes(meeting_id, version="internal"),
        },
        "artifacts": artifacts,
    }


def _list_meeting_states(
    limit: int = 10,
    needs_after: bool = False,
    stalled_agenda: bool = False,
    follow_up_needed: bool = False,
) -> list:
    drive_svc = DuringAgent().drive_svc
    states = drive_svc.list_meeting_states()
    states = _filter_meeting_states(
        states,
        needs_after=needs_after,
        stalled_agenda=stalled_agenda,
        follow_up_needed=follow_up_needed,
    )
    if limit <= 0:
        return states
    return states[:limit]


def _print_meeting_state_list(entries: list, as_json: bool, save_path: Optional[str] = None) -> None:
    rendered = _render_meeting_state_list(entries, as_json=as_json)
    if save_path:
        _write_local_file(save_path, rendered)
    print(rendered)


def _render_meeting_state_list(entries: list, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(entries, ensure_ascii=False, indent=2)

    if not entries:
        return "저장된 meeting state가 없습니다."

    lines = ["# Meeting State List", ""]
    for entry in entries:
        meeting_id = entry.get("meeting_id", "unknown")
        lines.extend(
            [
                f"- {meeting_id} | {entry.get('title', '미정')}",
                f"  phase={entry.get('phase', '미정')}, template={entry.get('template') or '없음'}, updated_at={entry.get('updated_at', '미정')}",
                f"  after_completed={entry.get('after_completed', False)}, artifacts={len(entry.get('artifacts', []))}, next={resolve_auto_rerun_stage(entry)}",
                f"  cmd: python3 -m src.cli status --meeting-id {meeting_id}",
                f"  cmd: python3 -m src.cli bundle --meeting-id {meeting_id}",
                f"  cmd: python3 -m src.cli rerun --meeting-id {meeting_id} --stage auto",
            ]
        )

    return "\n".join(lines)


def _build_dashboard(entries: list) -> dict:
    total = len(entries)
    after_completed = sum(1 for entry in entries if entry.get("after_completed"))
    with_follow_up = sum(1 for entry in entries if entry.get("follow_up_needed", entry.get("has_follow_up_meeting", False)))
    missing_transcript = sum(1 for entry in entries if not entry.get("transcript_collected"))
    missing_notes = sum(1 for entry in entries if entry.get("transcript_collected") and not entry.get("notes_generated"))
    needs_after = []
    stalled_agenda = []

    for entry in entries:
        if _needs_after_attention(entry):
            needs_after.append(
                {
                    "meeting_id": entry.get("meeting_id", "unknown"),
                    "title": entry.get("title", "미정"),
                    "updated_at": entry.get("updated_at", "미정"),
                    "reason": "After 후속 처리가 덜 끝남",
                    "recommended_command": f"python3 -m src.cli rerun --meeting-id {entry.get('meeting_id', 'unknown')} --stage after",
                }
            )

        if entry.get("registered_agenda_count", 0) > entry.get("agenda_status_count", 0):
            stalled_agenda.append(
                {
                    "meeting_id": entry.get("meeting_id", "unknown"),
                    "title": entry.get("title", "미정"),
                    "updated_at": entry.get("updated_at", "미정"),
                    "agenda_progress": f"{entry.get('agenda_status_count', 0)}/{entry.get('registered_agenda_count', 0)}",
                    "recommended_command": f"python3 -m src.cli bundle --meeting-id {entry.get('meeting_id', 'unknown')}",
                }
            )

    recent_titles = [
        {
            "meeting_id": entry.get("meeting_id", "unknown"),
            "title": entry.get("title", "미정"),
            "phase": entry.get("phase", "미정"),
            "updated_at": entry.get("updated_at", "미정"),
            "template": entry.get("template") or "없음",
            "recommended_command": f"python3 -m src.cli bundle --meeting-id {entry.get('meeting_id', 'unknown')}",
        }
        for entry in entries[:5]
    ]

    return {
        "generated_at": datetime.now().isoformat(),
        "total_meetings": total,
        "after_completed_count": after_completed,
        "completion_rate": _calculate_rate(after_completed, total),
        "follow_up_needed_count": with_follow_up,
        "missing_transcript_count": missing_transcript,
        "missing_notes_count": missing_notes,
        "needs_after_count": len(needs_after),
        "stalled_agenda_count": len(stalled_agenda),
        "recent_meetings": recent_titles,
        "needs_after": needs_after[:5],
        "stalled_agenda": stalled_agenda[:5],
    }


def _filter_meeting_states(
    entries: list,
    needs_after: bool = False,
    stalled_agenda: bool = False,
    follow_up_needed: bool = False,
) -> list:
    filtered = list(entries)

    if needs_after:
        filtered = [entry for entry in filtered if _needs_after_attention(entry)]

    if stalled_agenda:
        filtered = [
            entry
            for entry in filtered
            if entry.get("registered_agenda_count", 0) > entry.get("agenda_status_count", 0)
        ]

    if follow_up_needed:
        filtered = [entry for entry in filtered if get_follow_up_needed(entry)]

    return filtered


def _needs_after_attention(state: dict) -> bool:
    artifacts = {artifact.get("type") for artifact in state.get("artifacts", [])}
    follow_up_needed = get_follow_up_needed(state)

    if not state.get("notes_generated"):
        return False

    if not state.get("after_completed"):
        return True

    if "slack_summary" not in artifacts:
        return True

    if state.get("contact_update_count", 0) > 0 and "contact_updates" not in artifacts:
        return True

    if follow_up_needed and "follow_up_meeting" not in artifacts:
        return True

    if follow_up_needed and not state.get("follow_up_calendar_created", False):
        return True

    return False


def _calculate_rate(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0/0 (0%)"
    percentage = int((numerator / denominator) * 100)
    return f"{numerator}/{denominator} ({percentage}%)"


def _print_dashboard(dashboard: dict, as_json: bool, save_path: Optional[str] = None) -> None:
    rendered = _render_dashboard(dashboard, as_json)
    if save_path:
        _write_local_file(save_path, rendered)
    print(rendered)


def _render_dashboard(dashboard: dict, as_json: bool) -> str:
    if as_json:
        return json.dumps(dashboard, ensure_ascii=False, indent=2)

    lines = [
        "# Meeting Dashboard",
        "",
        f"- 생성 시각: {dashboard.get('generated_at', '미정')}",
        f"- 전체 미팅 수: {dashboard.get('total_meetings', 0)}",
        f"- After 완료율: {dashboard.get('completion_rate', '0/0 (0%)')}",
        f"- 후속 미팅 필요 수: {dashboard.get('follow_up_needed_count', 0)}",
        f"- transcript 누락 수: {dashboard.get('missing_transcript_count', 0)}",
        f"- notes 누락 수: {dashboard.get('missing_notes_count', 0)}",
        f"- After 후속처리 필요 수: {dashboard.get('needs_after_count', 0)}",
        f"- 어젠다 체크 지연 수: {dashboard.get('stalled_agenda_count', 0)}",
        "",
        "## 최근 미팅",
    ]

    recent_meetings = dashboard.get("recent_meetings", [])
    if not recent_meetings:
        lines.append("- 없음")
    else:
        for item in recent_meetings:
            meeting_id = item.get("meeting_id", "unknown")
            lines.append(
                f"- {meeting_id} | {item.get('title', '미정')} | phase={item.get('phase', '미정')} | template={item.get('template', '없음')} | updated_at={item.get('updated_at', '미정')}"
            )
            lines.append(f"  cmd: {item.get('recommended_command') or f'python3 -m src.cli bundle --meeting-id {meeting_id}'}")

    lines.extend(["", "## After 확인 필요"])
    needs_after = dashboard.get("needs_after", [])
    if not needs_after:
        lines.append("- 없음")
    else:
        for item in needs_after:
            meeting_id = item.get("meeting_id", "unknown")
            lines.append(
                f"- {meeting_id} | {item.get('title', '미정')} | {item.get('reason', '')} | updated_at={item.get('updated_at', '미정')}"
            )
            lines.append(f"  cmd: {item.get('recommended_command') or f'python3 -m src.cli rerun --meeting-id {meeting_id} --stage after'}")

    lines.extend(["", "## 어젠다 체크 지연"])
    stalled_agenda = dashboard.get("stalled_agenda", [])
    if not stalled_agenda:
        lines.append("- 없음")
    else:
        for item in stalled_agenda:
            meeting_id = item.get("meeting_id", "unknown")
            lines.append(
                f"- {meeting_id} | {item.get('title', '미정')} | progress={item.get('agenda_progress', '0/0')} | updated_at={item.get('updated_at', '미정')}"
            )
            lines.append(f"  cmd: {item.get('recommended_command') or f'python3 -m src.cli bundle --meeting-id {meeting_id}'}")

    return "\n".join(lines)


def _build_doctor_report(
    limit: int = 5,
    needs_after: bool = False,
    stalled_agenda: bool = False,
    follow_up_needed: bool = False,
) -> dict:
    drive_svc = DuringAgent().drive_svc
    entries = drive_svc.list_meeting_states()
    filtered_entries = _filter_meeting_states(
        entries,
        needs_after=needs_after,
        stalled_agenda=stalled_agenda,
        follow_up_needed=follow_up_needed,
    )
    dashboard_entries = filtered_entries[:limit] if limit > 0 else filtered_entries
    dashboard = _build_dashboard(dashboard_entries)

    cache_root = Path(Config.CACHE_DIR)
    dry_run_root = cache_root / "dry_run_drive"
    filesystem = {
        "cache_dir": str(cache_root),
        "cache_dir_exists": cache_root.exists(),
        "dry_run_drive_exists": dry_run_root.exists(),
        "meeting_state_dir_exists": (dry_run_root / Config.MEETING_STATE_FOLDER).exists(),
        "meeting_notes_dir_exists": (dry_run_root / Config.MEETING_NOTES_FOLDER).exists(),
        "transcripts_dir_exists": (dry_run_root / Config.MEETING_TRANSCRIPTS_FOLDER).exists(),
        "drafts_dir_exists": (dry_run_root / Config.GENERATED_DRAFTS_FOLDER).exists(),
    }
    env = {
        "DRY_RUN": Config.DRY_RUN,
        "DRY_RUN_CALENDAR": Config.DRY_RUN_CALENDAR,
        "DRY_RUN_TRELLO": Config.DRY_RUN_TRELLO,
        "ANTHROPIC_API_KEY": bool(Config.ANTHROPIC_API_KEY),
        "SLACK_BOT_TOKEN": bool(Config.SLACK_BOT_TOKEN),
        "SLACK_SIGNING_SECRET": bool(Config.SLACK_SIGNING_SECRET),
        "SLACK_APP_TOKEN": bool(Config.SLACK_APP_TOKEN),
        "TRELLO_API_KEY": bool(Config.TRELLO_API_KEY),
        "TRELLO_API_TOKEN": bool(Config.TRELLO_API_TOKEN),
        "GWS_CRED_FILE": bool(Config.GWS_CRED_FILE and Config.GWS_CRED_FILE != "/path/to/credentials.json"),
    }
    live_checks = {
        "slack_ready": all(
            [
                env["SLACK_BOT_TOKEN"],
                env["SLACK_SIGNING_SECRET"],
                env["SLACK_APP_TOKEN"],
            ]
        ),
        "trello_ready": env["TRELLO_API_KEY"] and env["TRELLO_API_TOKEN"],
        "anthropic_ready": env["ANTHROPIC_API_KEY"],
        "gws_ready": env["GWS_CRED_FILE"],
        "gws_cli_ready": bool(shutil.which("gws")) or Path(Config.gws_bin()).exists(),
        "calendar_live": not Config.DRY_RUN_CALENDAR,
        "trello_live": not Config.DRY_RUN_TRELLO,
    }
    live_checks["core_live_ready"] = all(
        [
            live_checks["slack_ready"],
            live_checks["trello_ready"],
            live_checks["anthropic_ready"],
            live_checks["gws_ready"],
            live_checks["gws_cli_ready"],
        ]
    )
    latest = dashboard_entries[0] if dashboard_entries else {}
    recommendations = []
    if not Config.DRY_RUN:
        recommendations.append("실연동 환경 점검으로 전환하세요.")
    else:
        if not live_checks["core_live_ready"]:
            recommendations.append("python3 -m src.cli doctor 로 live 전환 필수 env 값을 먼저 확인하세요.")
        if not dashboard_entries:
            recommendations.append("python3 -m src.cli smoke --bundle 로 첫 dry-run 산출물을 생성하세요.")
        else:
            meeting_id = latest.get("meeting_id")
            if meeting_id:
                recommendations.append(f"python3 -m src.cli bundle --meeting-id {meeting_id}")
                recommendations.append(f"python3 -m src.cli status --meeting-id {meeting_id}")
            recommendations.append(
                _build_ops_export_command(
                    needs_after=needs_after,
                    stalled_agenda=stalled_agenda,
                    follow_up_needed=follow_up_needed,
                    include_bundles=True,
                )
            )
            if dashboard.get("needs_after_count", 0) > 0:
                recommendations.append("python3 -m src.cli dashboard 로 After 확인 필요 항목을 검토하세요.")

    return {
        "generated_at": datetime.now().isoformat(),
        "mode": "dry_run" if Config.DRY_RUN else "live",
        "env": env,
        "live_checks": live_checks,
        "filesystem": filesystem,
        "meeting_state_count": len(filtered_entries),
        "latest_meeting": {
            "meeting_id": latest.get("meeting_id"),
            "title": latest.get("title"),
            "updated_at": latest.get("updated_at"),
            "phase": latest.get("phase"),
        },
        "dashboard": dashboard,
        "recent_meetings": dashboard_entries,
        "filters": {
            "needs_after": needs_after,
            "stalled_agenda": stalled_agenda,
            "follow_up_needed": follow_up_needed,
        },
        "recommendations": recommendations,
    }


def _build_ops_export_command(
    needs_after: bool = False,
    stalled_agenda: bool = False,
    follow_up_needed: bool = False,
    include_bundles: bool = False,
) -> str:
    parts = ["python3", "-m", "src.cli", "ops-export"]
    if needs_after:
        parts.append("--needs-after")
    if stalled_agenda:
        parts.append("--stalled-agenda")
    if follow_up_needed:
        parts.append("--follow-up-needed")
    if include_bundles:
        parts.append("--include-bundles")
    return " ".join(parts)


def _default_ops_export_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("artifacts") / f"ops_export_{timestamp}"


def _export_ops_reports(args: SimpleNamespace) -> dict:
    output_dir = Path(args.output_dir) if getattr(args, "output_dir", None) else _default_ops_export_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    entries = _list_meeting_states(
        limit=args.limit,
        needs_after=getattr(args, "needs_after", False),
        stalled_agenda=getattr(args, "stalled_agenda", False),
        follow_up_needed=getattr(args, "follow_up_needed", False),
    )
    dashboard = _build_dashboard(entries)
    doctor = _build_doctor_report(
        limit=args.limit,
        needs_after=getattr(args, "needs_after", False),
        stalled_agenda=getattr(args, "stalled_agenda", False),
        follow_up_needed=getattr(args, "follow_up_needed", False),
    )

    list_md_path = output_dir / "meeting_list.md"
    list_json_path = output_dir / "meeting_list.json"
    dashboard_md_path = output_dir / "dashboard.md"
    dashboard_json_path = output_dir / "dashboard.json"
    doctor_md_path = output_dir / "doctor.md"
    doctor_json_path = output_dir / "doctor.json"
    readme_path = output_dir / "README.md"
    metadata_path = output_dir / "metadata.json"
    bundle_reports = []

    _write_local_file(str(list_md_path), _render_meeting_state_list(entries, as_json=False))
    _write_local_file(str(list_json_path), _render_meeting_state_list(entries, as_json=True))
    _write_local_file(str(dashboard_md_path), _render_dashboard(dashboard, as_json=False))
    _write_local_file(str(dashboard_json_path), _render_dashboard(dashboard, as_json=True))
    _write_local_file(str(doctor_md_path), _render_doctor_report(doctor, as_json=False))
    _write_local_file(str(doctor_json_path), _render_doctor_report(doctor, as_json=True))

    if getattr(args, "include_bundles", False):
        bundles_dir = output_dir / "bundles"
        bundles_dir.mkdir(parents=True, exist_ok=True)
        bundle_limit = max(getattr(args, "bundle_limit", 3), 0)
        for entry in entries[:bundle_limit]:
            meeting_id = entry.get("meeting_id")
            if not meeting_id:
                continue

            bundle = _build_meeting_bundle(meeting_id)
            if not bundle:
                continue

            bundle_md_path = bundles_dir / f"{meeting_id}_bundle.md"
            bundle_json_path = bundles_dir / f"{meeting_id}_bundle.json"
            _write_local_file(str(bundle_md_path), _render_bundle(bundle, as_json=False))
            _write_local_file(str(bundle_json_path), _render_bundle(bundle, as_json=True))
            bundle_reports.append(
                {
                    "meeting_id": meeting_id,
                    "markdown": str(bundle_md_path),
                    "json": str(bundle_json_path),
                }
            )

    report = {
        "generated_at": datetime.now().isoformat(),
        "output_dir": str(output_dir),
        "entry_count": len(entries),
        "filters": {
            "needs_after": getattr(args, "needs_after", False),
            "stalled_agenda": getattr(args, "stalled_agenda", False),
            "follow_up_needed": getattr(args, "follow_up_needed", False),
        },
        "files": {
            "meeting_list_markdown": str(list_md_path),
            "meeting_list_json": str(list_json_path),
            "dashboard_markdown": str(dashboard_md_path),
            "dashboard_json": str(dashboard_json_path),
            "doctor_markdown": str(doctor_md_path),
            "doctor_json": str(doctor_json_path),
            "readme": str(readme_path),
            "metadata": str(metadata_path),
        },
        "bundles": bundle_reports,
    }
    _write_local_file(str(readme_path), _render_ops_export_report(report))
    _write_local_file(str(metadata_path), json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _render_ops_export_report(report: dict) -> str:
    files = report.get("files", {})
    filters = report.get("filters", {})
    bundles = report.get("bundles", [])
    lines = [
        "# Ops Export",
        "",
        f"- 생성 시각: {report.get('generated_at', '미정')}",
        f"- 출력 디렉토리: {report.get('output_dir', '미정')}",
        f"- 포함 미팅 수: {report.get('entry_count', 0)}",
        "",
        "## Filters",
        f"- needs_after: {filters.get('needs_after', False)}",
        f"- stalled_agenda: {filters.get('stalled_agenda', False)}",
        f"- follow_up_needed: {filters.get('follow_up_needed', False)}",
        "",
        "## Files",
        f"- meeting_list.md: {files.get('meeting_list_markdown', '')}",
        f"- meeting_list.json: {files.get('meeting_list_json', '')}",
        f"- dashboard.md: {files.get('dashboard_markdown', '')}",
        f"- dashboard.json: {files.get('dashboard_json', '')}",
        f"- doctor.md: {files.get('doctor_markdown', '')}",
        f"- doctor.json: {files.get('doctor_json', '')}",
        f"- README.md: {files.get('readme', '')}",
        f"- metadata.json: {files.get('metadata', '')}",
    ]

    lines.extend(["", "## Bundles"])
    if not bundles:
        lines.append("- 없음")
    else:
        for bundle in bundles:
            lines.append(f"- {bundle.get('meeting_id', 'unknown')}")
            lines.append(f"  md: {bundle.get('markdown', '')}")
            lines.append(f"  json: {bundle.get('json', '')}")

    return "\n".join(lines)


def _print_doctor_report(report: dict, as_json: bool, save_path: Optional[str] = None) -> None:
    rendered = _render_doctor_report(report, as_json=as_json)
    if save_path:
        _write_local_file(save_path, rendered)
    print(rendered)


def _render_doctor_report(report: dict, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(report, ensure_ascii=False, indent=2)

    env = report.get("env", {})
    filesystem = report.get("filesystem", {})
    latest = report.get("latest_meeting", {})
    dashboard = report.get("dashboard", {})

    lines = [
        "# Meetagain Doctor",
        "",
        f"- 생성 시각: {report.get('generated_at', '미정')}",
        f"- 모드: {report.get('mode', 'unknown')}",
        f"- meeting state 수: {report.get('meeting_state_count', 0)}",
        "",
        "## Environment",
        f"- DRY_RUN: {env.get('DRY_RUN', False)}",
        f"- DRY_RUN_CALENDAR: {env.get('DRY_RUN_CALENDAR', False)}",
        f"- DRY_RUN_TRELLO: {env.get('DRY_RUN_TRELLO', False)}",
        f"- ANTHROPIC_API_KEY: {env.get('ANTHROPIC_API_KEY', False)}",
        f"- SLACK_BOT_TOKEN: {env.get('SLACK_BOT_TOKEN', False)}",
        f"- SLACK_SIGNING_SECRET: {env.get('SLACK_SIGNING_SECRET', False)}",
        f"- SLACK_APP_TOKEN: {env.get('SLACK_APP_TOKEN', False)}",
        f"- TRELLO_API_KEY: {env.get('TRELLO_API_KEY', False)}",
        f"- TRELLO_API_TOKEN: {env.get('TRELLO_API_TOKEN', False)}",
        f"- GWS_CRED_FILE: {env.get('GWS_CRED_FILE', False)}",
        "",
        "## Live Readiness",
        f"- slack_ready: {report.get('live_checks', {}).get('slack_ready', False)}",
        f"- trello_ready: {report.get('live_checks', {}).get('trello_ready', False)}",
        f"- anthropic_ready: {report.get('live_checks', {}).get('anthropic_ready', False)}",
        f"- gws_ready: {report.get('live_checks', {}).get('gws_ready', False)}",
        f"- gws_cli_ready: {report.get('live_checks', {}).get('gws_cli_ready', False)}",
        f"- calendar_live: {report.get('live_checks', {}).get('calendar_live', False)}",
        f"- trello_live: {report.get('live_checks', {}).get('trello_live', False)}",
        f"- core_live_ready: {report.get('live_checks', {}).get('core_live_ready', False)}",
        "",
        "## Filesystem",
        f"- cache_dir: {filesystem.get('cache_dir', '미정')}",
        f"- cache_dir_exists: {filesystem.get('cache_dir_exists', False)}",
        f"- dry_run_drive_exists: {filesystem.get('dry_run_drive_exists', False)}",
        f"- meeting_state_dir_exists: {filesystem.get('meeting_state_dir_exists', False)}",
        f"- meeting_notes_dir_exists: {filesystem.get('meeting_notes_dir_exists', False)}",
        f"- transcripts_dir_exists: {filesystem.get('transcripts_dir_exists', False)}",
        f"- drafts_dir_exists: {filesystem.get('drafts_dir_exists', False)}",
        "",
        "## Latest Meeting",
        f"- meeting_id: {latest.get('meeting_id') or '없음'}",
        f"- title: {latest.get('title') or '없음'}",
        f"- updated_at: {latest.get('updated_at') or '없음'}",
        f"- phase: {latest.get('phase') or '없음'}",
        "",
        "## Filters",
        f"- needs_after: {report.get('filters', {}).get('needs_after', False)}",
        f"- stalled_agenda: {report.get('filters', {}).get('stalled_agenda', False)}",
        f"- follow_up_needed: {report.get('filters', {}).get('follow_up_needed', False)}",
        "",
        "## Dashboard Snapshot",
        f"- completion_rate: {dashboard.get('completion_rate', '0/0 (0%)')}",
        f"- follow_up_needed_count: {dashboard.get('follow_up_needed_count', 0)}",
        f"- missing_transcript_count: {dashboard.get('missing_transcript_count', 0)}",
        f"- missing_notes_count: {dashboard.get('missing_notes_count', 0)}",
        f"- needs_after_count: {dashboard.get('needs_after_count', 0)}",
        f"- stalled_agenda_count: {dashboard.get('stalled_agenda_count', 0)}",
        "",
        "## Recommendations",
    ]

    recommendations = report.get("recommendations", [])
    if recommendations:
        lines.extend(f"- {item}" for item in recommendations)
    else:
        lines.append("- 없음")

    return "\n".join(lines)


def _print_bundle(bundle: dict, as_json: bool, save_path: Optional[str] = None) -> None:
    rendered = _render_bundle(bundle, as_json)
    if save_path:
        _write_local_file(save_path, rendered)
    if as_json:
        print(rendered)
        return

    print(rendered)


def _render_bundle(bundle: dict, as_json: bool) -> str:
    if as_json:
        return json.dumps(bundle, ensure_ascii=False, indent=2)

    lines = [
        f"# Meeting Bundle: {bundle.get('meeting_id', 'unknown')}",
        "",
        "## 상태",
        format_meeting_status(bundle.get("state", {})),
        "",
        "## Transcript",
        bundle.get("transcript") or "없음",
        "",
        "## Client Notes",
        (bundle.get("notes", {}) or {}).get("client") or "없음",
        "",
        "## Internal Notes",
        (bundle.get("notes", {}) or {}).get("internal") or "없음",
        "",
        "## Artifacts",
    ]

    artifacts = bundle.get("artifacts", [])
    if not artifacts:
        lines.append("없음")
    else:
        for artifact in artifacts:
            lines.extend(
                [
                    f"### [{artifact.get('type', 'unknown')}] {artifact.get('path', '')}",
                    artifact.get("content") or "내용 없음",
                    "",
                ]
            )

    return "\n".join(lines).rstrip()


def _write_local_file(filepath: str, content: str) -> None:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def _run_demo(args: SimpleNamespace) -> bool:
    output_dir = Path(getattr(args, "output_dir", None) or _default_demo_dir())
    output_dir.mkdir(parents=True, exist_ok=True)

    suite_args = SimpleNamespace(
        output_dir=str(output_dir / "smoke_suite"),
        json=False,
    )
    with redirect_stdout(io.StringIO()):
        suite_success = await _run_smoke_suite(suite_args)
    if not suite_success:
        return False

    export_args = SimpleNamespace(
        output_dir=str(output_dir / "ops_export"),
        limit=10,
        needs_after=False,
        stalled_agenda=False,
        follow_up_needed=False,
        json=False,
        include_bundles=True,
        bundle_limit=getattr(args, "bundle_limit", 3),
    )
    ops_report = _export_ops_reports(export_args)

    doctor_report = _build_doctor_report(limit=5)
    doctor_markdown_path = output_dir / "doctor_snapshot.md"
    doctor_json_path = output_dir / "doctor_snapshot.json"
    _write_local_file(str(doctor_markdown_path), _render_doctor_report(doctor_report, as_json=False))
    _write_local_file(str(doctor_json_path), _render_doctor_report(doctor_report, as_json=True))

    suite_report_path = output_dir / "smoke_suite" / "suite_report.json"
    suite_report = json.loads(suite_report_path.read_text(encoding="utf-8"))
    featured_meetings = []
    for scenario in suite_report.get("scenarios", [])[:3]:
        meeting_id = scenario.get("meeting_id", "unknown")
        featured_meetings.append(
            {
                "name": scenario.get("name", "unknown"),
                "meeting_id": meeting_id,
                "title": scenario.get("title", "미정"),
                "template": scenario.get("template", "미정"),
                "bundle_command": f"python3 -m src.cli bundle --meeting-id {meeting_id}",
                "status_command": f"python3 -m src.cli status --meeting-id {meeting_id}",
            }
        )

    demo_report = {
        "generated_at": datetime.now().isoformat(),
        "output_dir": str(output_dir),
        "smoke_suite_output_dir": str(output_dir / "smoke_suite"),
        "ops_export_output_dir": str(output_dir / "ops_export"),
        "scenario_count": suite_report.get("scenario_count", 0),
        "all_passed": suite_report.get("all_passed", False),
        "ops_entry_count": ops_report.get("entry_count", 0),
        "bundle_count": len(ops_report.get("bundles", [])),
        "doctor_markdown_path": str(doctor_markdown_path),
        "doctor_json_path": str(doctor_json_path),
        "featured_meetings": featured_meetings,
        "next_steps": [
            f"python3 -m src.cli bundle --meeting-id <EVENT_ID>",
            f"python3 -m src.cli doctor --save {doctor_markdown_path}",
        ],
    }

    _write_local_file(str(output_dir / "demo_report.json"), json.dumps(demo_report, ensure_ascii=False, indent=2))
    _write_local_file(str(output_dir / "README.md"), _render_demo_report(demo_report))
    _write_local_file(str(output_dir / "playbook.md"), _render_demo_playbook(demo_report))

    if getattr(args, "json", False):
        print(json.dumps(demo_report, ensure_ascii=False, indent=2))
    else:
        print(_render_demo_report(demo_report))

    return demo_report.get("all_passed", False)


def _render_smoke_suite_report(report: dict) -> str:
    lines = [
        "# Smoke Suite Report",
        "",
        f"- 생성 시각: {report.get('generated_at', '미정')}",
        f"- 출력 디렉토리: {report.get('output_dir', '미정')}",
        f"- 시나리오 수: {report.get('scenario_count', 0)}",
        f"- 전체 성공: {report.get('all_passed', False)}",
        "",
        "## 시나리오 요약",
    ]

    for scenario in report.get("scenarios", []):
        lines.extend(
            [
                f"### {scenario.get('name', 'unknown')}",
                f"- meeting_id: {scenario.get('meeting_id', 'unknown')}",
                f"- 제목: {scenario.get('title', '미정')}",
                f"- 템플릿: {scenario.get('template', '미정')}",
                f"- After 완료: {scenario.get('after_completed', False)}",
                f"- proposal 초안: {scenario.get('proposal_draft_created', False)}",
                f"- research 초안: {scenario.get('research_draft_created', False)}",
                f"- follow-up calendar 초안: {scenario.get('follow_up_calendar_created', False)}",
                f"- 산출물 수: {scenario.get('artifact_count', 0)}",
                f"- Markdown bundle: {scenario.get('bundle_markdown_path', '')}",
                f"- JSON bundle: {scenario.get('bundle_json_path', '')}",
                "",
            ]
        )

    return "\n".join(lines).rstrip()


def _render_demo_report(report: dict) -> str:
    lines = [
        "# Meetagain Demo Report",
        "",
        f"- 생성 시각: {report.get('generated_at', '미정')}",
        f"- 출력 디렉토리: {report.get('output_dir', '미정')}",
        f"- smoke-suite 경로: {report.get('smoke_suite_output_dir', '미정')}",
        f"- ops-export 경로: {report.get('ops_export_output_dir', '미정')}",
        f"- doctor markdown: {report.get('doctor_markdown_path', '미정')}",
        f"- doctor json: {report.get('doctor_json_path', '미정')}",
        f"- 시나리오 수: {report.get('scenario_count', 0)}",
        f"- 전체 성공: {report.get('all_passed', False)}",
        f"- 운영 리포트 미팅 수: {report.get('ops_entry_count', 0)}",
        f"- 포함 bundle 수: {report.get('bundle_count', 0)}",
        "",
        "## Featured Meetings",
    ]

    featured_meetings = report.get("featured_meetings", [])
    if not featured_meetings:
        lines.append("- 없음")
    else:
        for item in featured_meetings:
            lines.extend(
                [
                    f"- {item.get('name', 'unknown')} | {item.get('meeting_id', 'unknown')} | {item.get('title', '미정')}",
                    f"  template: {item.get('template', '미정')}",
                    f"  bundle: {item.get('bundle_command', '')}",
                    f"  status: {item.get('status_command', '')}",
                ]
            )

    lines.extend([
        "",
        "## Next Steps",
    ])

    for item in report.get("next_steps", []):
        lines.append(f"- {item}")

    return "\n".join(lines).rstrip()


def _render_demo_playbook(report: dict) -> str:
    lines = [
        "# Meetagain Demo Playbook",
        "",
        "## 1. 데모 시작",
        f"- 결과 폴더 확인: {report.get('output_dir', '미정')}",
        f"- doctor 확인: {report.get('doctor_markdown_path', '미정')}",
        "",
        "## 2. 대표 미팅 확인",
    ]

    featured_meetings = report.get("featured_meetings", [])
    if not featured_meetings:
        lines.append("- 대표 미팅 없음")
    else:
        for item in featured_meetings:
            lines.extend(
                [
                    f"- {item.get('name', 'unknown')} | {item.get('meeting_id', 'unknown')} | {item.get('title', '미정')}",
                    f"  1) 상태 확인: {item.get('status_command', '')}",
                    f"  2) 산출물 확인: {item.get('bundle_command', '')}",
                ]
            )

    lines.extend(
        [
            "",
            "## 3. 운영 점검",
            f"- doctor 재확인: python3 -m src.cli doctor --save {report.get('doctor_markdown_path', 'doctor_snapshot.md')}",
            f"- list 확인: python3 -m src.cli list --limit 10",
            "",
            "## 4. 다음 액션",
        ]
    )

    for item in report.get("next_steps", []):
        lines.append(f"- {item}")

    return "\n".join(lines).rstrip()

if __name__ == "__main__":
    asyncio.run(main())
