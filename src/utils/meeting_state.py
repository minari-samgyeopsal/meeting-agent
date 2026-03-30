"""
미팅 상태 기반 공용 판단 유틸리티
"""


def get_follow_up_needed(state: dict) -> bool:
    return state.get("follow_up_needed", state.get("has_follow_up_meeting", False))


def resolve_auto_rerun_stage(state: dict) -> str:
    artifacts = {artifact.get("type") for artifact in state.get("artifacts", [])}
    follow_up_needed = get_follow_up_needed(state)
    needs_after = (
        state.get("notes_generated")
        and (
            not state.get("after_completed")
            or "slack_summary" not in artifacts
            or (state.get("contact_update_count", 0) > 0 and "contact_updates" not in artifacts)
            or (follow_up_needed and "follow_up_meeting" not in artifacts)
            or (follow_up_needed and not state.get("follow_up_calendar_created", False))
        )
    )

    if needs_after:
        return "after"

    if state.get("notes_generated"):
        return "after"

    if state.get("transcript_collected"):
        return "during"

    return "pipeline"
