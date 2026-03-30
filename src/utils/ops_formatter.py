"""
운영 요약 포맷터
"""


def _to_slack_action(command: str) -> str:
    if not command:
        return command

    if command.startswith("python3 -m src.cli rerun --meeting-id "):
        payload = command.replace("python3 -m src.cli rerun --meeting-id ", "", 1)
        meeting_id, _, stage_part = payload.partition(" --stage ")
        if meeting_id and stage_part:
            return f"/meetagain rerun {meeting_id.strip()} {stage_part.strip()}"

    if command.startswith("python3 -m src.cli bundle --meeting-id "):
        meeting_id = command.replace("python3 -m src.cli bundle --meeting-id ", "", 1).strip()
        if meeting_id:
            return f"/meetagain bundle {meeting_id}"

    return command


def format_recent_meetings(entries: list, limit: int = 5) -> str:
    lines = ["최근 미팅", ""]
    if not entries:
        lines.append("- 최근 meeting state가 없습니다.")
        return "\n".join(lines)

    for entry in entries[:limit]:
        meeting_id = entry.get("meeting_id", "unknown")
        lines.append(
            f"- {meeting_id} | {entry.get('title', '미정')} | phase={entry.get('phase', '미정')} | next={entry.get('next_stage', '미정')}"
        )
        meta = []
        if entry.get("template"):
            meta.append(f"template={entry['template']}")
        if entry.get("updated_at"):
            meta.append(f"updated_at={entry['updated_at']}")
        if "artifact_count" in entry:
            meta.append(f"artifacts={entry['artifact_count']}")
        if entry.get("agenda_progress"):
            meta.append(f"agenda={entry['agenda_progress']}")
        if meta:
            lines.append(f"  {' | '.join(meta)}")
        if entry.get("attention_flags"):
            lines.append(f"  flags: {', '.join(entry['attention_flags'])}")
        if entry.get("status_command"):
            lines.append(f"  status: {entry['status_command']}")
        if entry.get("recommended_command"):
            lines.append(f"  action: {entry['recommended_command']}")

    return "\n".join(lines)


def format_dashboard_snapshot(dashboard: dict) -> str:
    lines = [
        "대시보드 요약",
        "",
        f"- 전체 미팅 수: {dashboard.get('total_meetings', 0)}",
        f"- After 완료율: {dashboard.get('completion_rate', '0/0 (0%)')}",
        f"- After 확인 필요 수: {dashboard.get('needs_after_count', 0)}",
        f"- 어젠다 체크 지연 수: {dashboard.get('stalled_agenda_count', 0)}",
        f"- 후속 미팅 필요 수: {dashboard.get('follow_up_needed_count', 0)}",
    ]

    recent_meetings = dashboard.get("recent_meetings", [])
    if recent_meetings:
        lines.extend(["", "최근 미팅"])
        for item in recent_meetings[:3]:
            lines.append(
                f"- {item.get('meeting_id', 'unknown')} | {item.get('title', '미정')} | phase={item.get('phase', '미정')}"
            )
            lines.append(f"  status: /meetagain status {item.get('meeting_id', 'unknown')}")
            if item.get("recommended_command"):
                lines.append(f"  action: {_to_slack_action(item['recommended_command'])}")

    needs_after = dashboard.get("needs_after", [])
    if needs_after:
        lines.extend(["", "After 확인 필요"])
        for item in needs_after[:3]:
            lines.append(
                f"- {item.get('meeting_id', 'unknown')} | {item.get('title', '미정')} | {item.get('reason', '')}"
            )
            if item.get("recommended_command"):
                lines.append(f"  action: {_to_slack_action(item['recommended_command'])}")

    stalled = dashboard.get("stalled_agenda", [])
    if stalled:
        lines.extend(["", "어젠다 체크 지연"])
        for item in stalled[:3]:
            lines.append(
                f"- {item.get('meeting_id', 'unknown')} | {item.get('title', '미정')} | progress={item.get('agenda_progress', '0/0')}"
            )
            if item.get("recommended_command"):
                lines.append(f"  action: {_to_slack_action(item['recommended_command'])}")

    recommendations = []
    if dashboard.get("needs_after_count", 0) > 0:
        recommendations.append("/meetagain doctor 5 needs-after")
    if dashboard.get("stalled_agenda_count", 0) > 0:
        recommendations.append("/meetagain dashboard 10 stalled-agenda")
    if dashboard.get("follow_up_needed_count", 0) > 0:
        recommendations.append("/meetagain doctor 5 follow-up")

    if recommendations:
        lines.extend(["", "추천 작업"])
        for item in recommendations:
            lines.append(f"- {item}")

    return "\n".join(lines)


def format_doctor_summary(report: dict) -> str:
    env = report.get("env", {})
    filesystem = report.get("filesystem", {})
    latest = report.get("latest_meeting", {})
    live_checks = report.get("live_checks", {})

    lines = [
        "운영 점검",
        "",
        f"- 모드: {report.get('mode', 'unknown')}",
        f"- meeting state 수: {report.get('meeting_state_count', 0)}",
        f"- DRY_RUN: {env.get('DRY_RUN', False)}",
        f"- Calendar live: {live_checks.get('calendar_live', False)}",
        f"- Trello live: {live_checks.get('trello_live', False)}",
        f"- Slack 준비: {live_checks.get('slack_ready', False)}",
        f"- Trello 준비: {live_checks.get('trello_ready', False)}",
        f"- Anthropic 준비: {live_checks.get('anthropic_ready', False)}",
        f"- gws CLI 준비: {live_checks.get('gws_cli_ready', False)}",
        f"- Live 핵심 준비: {live_checks.get('core_live_ready', False)}",
        f"- cache_dir_exists: {filesystem.get('cache_dir_exists', False)}",
        f"- dry_run_drive_exists: {filesystem.get('dry_run_drive_exists', False)}",
        f"- 최신 미팅: {latest.get('meeting_id') or '없음'} / {latest.get('phase') or '없음'}",
    ]

    latest_meeting_id = latest.get("meeting_id")
    if latest_meeting_id:
        lines.append(f"  status: /meetagain status {latest_meeting_id}")
        lines.append(f"  action: /meetagain bundle {latest_meeting_id}")

    recommendations = report.get("recommendations", [])
    if recommendations:
        lines.extend(["", "추천 작업"])
        for item in recommendations[:3]:
            lines.append(f"- {_to_slack_action(item)}")

    return "\n".join(lines)
