"""
미팅 상태 출력 포맷터
"""

from src.utils.meeting_state import get_follow_up_needed


def format_meeting_status(state: dict) -> str:
    artifact_summary = _summarize_artifacts(state.get("artifacts", []))
    agenda_progress = _format_agenda_progress(
        state.get("registered_agenda_count", 0),
        state.get("agenda_status_count", 0),
    )
    lines = [
        f"미팅 상태: {state.get('meeting_id', 'unknown')}",
        f"- 제목: {state.get('title', '미정')}",
        f"- 현재 단계: {state.get('phase', '미정')}",
        f"- 마지막 갱신: {state.get('updated_at', '미정')}",
        f"- 템플릿: {state.get('template') or '없음'}",
        f"- 템플릿 출처: {state.get('template_source') or '없음'}",
        f"- 브리핑 발송: {state.get('briefing_sent', False)}",
        f"- 브리핑 초안 생성: {state.get('before_briefing_created', False)}",
        f"- 채널 공유 초안 생성: {state.get('channel_share_created', False)}",
        f"- 어젠다 등록: {state.get('agenda_registered', False)}",
        f"- transcript 수집: {state.get('transcript_collected', False)}",
        f"- 회의록 생성: {state.get('notes_generated', False)}",
        f"- After 완료: {state.get('after_completed', False)}",
        f"- 등록 어젠다 수: {state.get('registered_agenda_count', 0)}",
        f"- 어젠다 체크 수: {state.get('agenda_status_count', 0)}",
        f"- 어젠다 진행률: {agenda_progress}",
        f"- 액션아이템 수: {state.get('action_item_count', 0)}",
        f"- 결정사항 수: {state.get('decision_count', 0)}",
        f"- 담당자 DM 수: {state.get('assignee_dm_count', 0)}",
        f"- 리마인더 수: {state.get('reminder_count', 0)}",
        f"- Contacts 업데이트 수: {state.get('contact_update_count', 0)}",
        f"- 제안서 초안 생성: {state.get('proposal_draft_created', False)}",
        f"- 리서치 초안 생성: {state.get('research_draft_created', False)}",
        f"- 후속 미팅 필요: {state.get('follow_up_needed', state.get('has_follow_up_meeting', False))}",
        f"- 후속 미팅 초안 생성: {state.get('follow_up_draft_created', False)}",
        f"- 후속 미팅 캘린더 초안 생성: {state.get('follow_up_calendar_created', False)}",
        f"- 산출물 요약: {artifact_summary}",
    ]

    artifacts = state.get("artifacts", [])
    if artifacts:
        lines.append("- 산출물:")
        for artifact in artifacts:
            lines.append(f"  - [{artifact.get('type', 'unknown')}] {artifact.get('path', '')}")

    lines.append(f"- 다음 권장 작업: {_recommend_next_action(state)}")

    return "\n".join(lines)


def _recommend_next_action(state: dict) -> str:
    artifacts = {artifact.get("type") for artifact in state.get("artifacts", [])}
    registered_agenda_count = state.get("registered_agenda_count", 0)
    agenda_status_count = state.get("agenda_status_count", 0)

    if not state.get("briefing_sent") and state.get("is_external"):
        return "Before 브리핑을 다시 실행하세요"

    if not state.get("agenda_registered"):
        return "어젠다를 등록하거나 최신 어젠다를 확인하세요"

    if not state.get("transcript_collected"):
        return "transcript를 업로드하거나 During를 재실행하세요"

    if not state.get("notes_generated"):
        return "During 회의록 생성을 재실행하세요"

    if registered_agenda_count > 0 and agenda_status_count < registered_agenda_count:
        return "어젠다 달성 체크를 검토하고 During를 다시 실행하세요"

    if not state.get("after_completed"):
        return "After 또는 pipeline 재실행으로 후속 처리를 완료하세요"

    if "slack_summary" not in artifacts:
        return "Slack 요약 초안을 확인하거나 After를 다시 실행하세요"

    if state.get("contact_update_count", 0) > 0 and "contact_updates" not in artifacts:
        return "Contacts 업데이트 초안을 다시 생성하세요"

    follow_up_needed = get_follow_up_needed(state)
    if follow_up_needed:
        if "follow_up_meeting" not in artifacts:
            return "후속 미팅 초안을 다시 생성하세요"
        if not state.get("follow_up_calendar_created", False):
            return "후속 미팅 캘린더 초안을 다시 생성하거나 검토하세요"
        return "후속 미팅 초안과 캘린더 초안을 검토하세요"

    return "상태상 주요 후속 작업은 완료되었습니다"


def _summarize_artifacts(artifacts: list) -> str:
    if not artifacts:
        return "없음"

    counts = {}
    for artifact in artifacts:
        artifact_type = artifact.get("type", "unknown")
        counts[artifact_type] = counts.get(artifact_type, 0) + 1

    ordered_keys = sorted(counts.keys())
    return ", ".join(f"{key} {counts[key]}개" for key in ordered_keys)


def _format_agenda_progress(registered_count: int, checked_count: int) -> str:
    if registered_count <= 0:
        return "등록된 어젠다 없음"

    if checked_count < 0:
        checked_count = 0

    percentage = min(int((checked_count / registered_count) * 100), 100)
    return f"{checked_count}/{registered_count} ({percentage}%)"
