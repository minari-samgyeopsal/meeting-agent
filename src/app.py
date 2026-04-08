"""
Slack 앱 진입점

현재는 수동 트리거 중심으로 Before / During / After 에이전트를
Slack Slash Command와 멘션 텍스트로 호출하는 최소 구현입니다.
"""

import asyncio
import json
import re
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union

import requests
from anthropic import Anthropic
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from src.agents.after_agent import AfterAgent
from src.agents.before_agent import BeforeAgent
from src.agents.channel_monitor_agent import ChannelMonitorAgent
from src.agents.during_agent import DuringAgent
from src.cli import _build_dashboard, _build_doctor_report, _build_meeting_bundle, _list_meeting_states
from src.services.drive_service import DriveService
from src.utils.config import Config
from src.utils.logger import get_logger
from src.utils.meeting_state import resolve_auto_rerun_stage
from src.utils.ops_formatter import (
    format_dashboard_snapshot,
    format_doctor_summary,
    format_recent_meetings,
)
from src.utils.status_formatter import format_meeting_status

logger = get_logger(__name__)
_RECENT_EVENT_KEYS = deque(maxlen=200)
_PENDING_TRANSCRIPT_UPLOADS = {}
_PENDING_AFTER_PIPELINES = {}


def _build_app() -> App:
    if not Config.validate(
        [
            "SLACK_BOT_TOKEN",
            "SLACK_SIGNING_SECRET",
            "SLACK_APP_TOKEN",
            "ANTHROPIC_API_KEY",
        ]
    ):
        raise SystemExit(1)

    app = App(
        token=Config.SLACK_BOT_TOKEN,
        signing_secret=Config.SLACK_SIGNING_SECRET,
    )

    @app.command("/meetagain")
    def handle_meetagain_command(ack, respond, command):
        ack()
        text = (command.get("text") or "").strip()
        try:
            response = asyncio.run(dispatch_text_command(text))
        except Exception:
            logger.exception("Slash command handling failed")
            response = "명령 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        respond(response)

    @app.event("app_mention")
    def handle_app_mention(event, say):
        if _is_duplicate_event(event):
            return
        text = (event.get("text") or "").strip()
        cleaned = _strip_bot_mention(text)
        try:
            response = asyncio.run(dispatch_text_command(cleaned))
        except Exception:
            logger.exception("App mention handling failed")
            response = "멘션 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        _emit_say_response(say, response)

    @app.event("message")
    def handle_message_event(event, say, client):
        if _is_duplicate_event(event):
            return
        subtype = event.get("subtype")
        if subtype in {"bot_message", "message_changed", "message_deleted"}:
            return

        try:
            response = asyncio.run(dispatch_message_event(event, client))
        except Exception:
            logger.exception("Message event handling failed")
            response = "메시지 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

        if response:
            _emit_say_response(say, response)

    @app.event("file_shared")
    def handle_file_shared_event(event, client):
        if _is_duplicate_event(event):
            return
        try:
            asyncio.run(_handle_file_shared_event(event, client))
        except Exception:
            logger.exception("file_shared handling failed")

    @app.action("trello_register")
    def handle_trello_register(ack, body, respond):
        ack()
        meeting_id = ((body.get("actions") or [{}])[0]).get("value", "")
        try:
            success = asyncio.run(_register_trello_for_meeting(meeting_id))
            if success:
                summary = _format_trello_registration_summary(meeting_id)
                respond(
                    {
                        "text": summary,
                        "replace_original": False,
                        "response_type": "ephemeral",
                    }
                )
            else:
                respond(
                    {
                        "text": "Trello 등록 중 문제가 발생했습니다.",
                        "replace_original": False,
                        "response_type": "ephemeral",
                    }
                )
        except Exception:
            logger.exception("Trello register action failed")
            respond(
                {
                    "text": "Trello 등록 중 오류가 발생했습니다.",
                    "replace_original": False,
                    "response_type": "ephemeral",
                }
            )

    @app.action("trello_skip")
    def handle_trello_skip(ack, respond):
        ack()
        respond(
            {
                "text": "알겠습니다. 이번에는 Trello 등록을 건너뒀어요.",
                "replace_original": False,
                "response_type": "ephemeral",
            }
        )

    @app.action("archive_register")
    def handle_archive_register(ack, body, respond, client):
        try:
            asyncio.run(ChannelMonitorAgent().handle_archive_action(ack, body, client, respond=respond))
        except Exception:
            logger.exception("Archive register action failed")
            respond(
                {
                    "text": "아카이빙 등록 처리 중 오류가 발생했습니다.",
                    "replace_original": False,
                    "response_type": "ephemeral",
                }
            )

    @app.action("archive_change_card")
    def handle_archive_change_card(ack, body, respond, client):
        try:
            asyncio.run(ChannelMonitorAgent().handle_archive_action(ack, body, client, respond=respond))
        except Exception:
            logger.exception("Archive change card action failed")
            respond(
                {
                    "text": "카드 변경 처리 중 오류가 발생했습니다.",
                    "replace_original": False,
                    "response_type": "ephemeral",
                }
            )

    @app.action("archive_skip")
    def handle_archive_skip(ack, body, respond, client):
        try:
            asyncio.run(ChannelMonitorAgent().handle_archive_action(ack, body, client, respond=respond))
        except Exception:
            logger.exception("Archive skip action failed")
            respond(
                {
                    "text": "아카이빙 건너뛰기 처리 중 오류가 발생했습니다.",
                    "replace_original": False,
                    "response_type": "ephemeral",
                }
            )

    @app.action("archive_select_card")
    def handle_archive_select_card(ack, body, respond, client):
        try:
            asyncio.run(ChannelMonitorAgent().handle_archive_action(ack, body, client, respond=respond))
        except Exception:
            logger.exception("Archive select card action failed")
            respond(
                {
                    "text": "카드 선택 처리 중 오류가 발생했습니다.",
                    "replace_original": False,
                    "response_type": "ephemeral",
                }
            )

    return app


async def dispatch_text_command(text: str, prefer_help: bool = True) -> Optional[Union[str, dict]]:
    original = " ".join(text.split())
    natural_create = _parse_korean_create_request(original)
    if natural_create:
        agent = BeforeAgent()
        meeting = await agent.create_meeting_with_briefing(
            title=natural_create["title"],
            start_time=natural_create["start_time"],
            end_time=natural_create["end_time"],
            attendees=natural_create["attendees"],
            agenda=natural_create["agenda"],
            template=natural_create.get("template"),
        )
        return _format_meeting_created_response(meeting, natural_create["agenda"]) if meeting else "미팅 생성 실패"

    normalized = original
    normalized = _normalize_natural_command(normalized)
    compact = re.sub(r"\s+", "", original.lower())

    if not normalized:
        return _help_text() if prefer_help else None

    if normalized in {"help", "도움말"}:
        return _help_text()

    if normalized.startswith("before"):
        demo_friendly = "브리핑" in compact and not original.lower().startswith("before")
        return await _run_before_command(demo_friendly=demo_friendly)

    if normalized.startswith("create "):
        parsed = _parse_create_command(normalized)
        if not parsed:
            return (
                "형식:\n"
                "- /meetagain create <title>|<start_iso>|<end_iso>|<attendee1,attendee2>|<agenda>\n"
                "- /meetagain create 내일 15:00 카카오 미팅 with user@kakao.com, me@parametacorp.com about 서비스 소개\n"
                "- /meetagain create 내일 오후 3:00 카카오 미팅 with user@kakao.com about 서비스 소개"
            )

        agent = BeforeAgent()
        meeting = await agent.create_meeting_with_briefing(
            title=parsed["title"],
            start_time=parsed["start_time"],
            end_time=parsed["end_time"],
            attendees=parsed["attendees"],
            agenda=parsed["agenda"],
            template=parsed.get("template"),
        )
        return _format_meeting_created_response(meeting, parsed["agenda"]) if meeting else "미팅 생성 실패"

    if normalized.startswith("update-company-knowledge"):
        agent = BeforeAgent()
        success = await agent.update_company_knowledge()
        return "company_knowledge 갱신 완료" if success else "company_knowledge 갱신 실패"

    if normalized.startswith("during "):
        meeting_id = _resolve_meeting_reference(normalized.split(maxsplit=1)[1].strip())
        if not meeting_id:
            return "최근 미팅이 없습니다. 먼저 미팅을 생성하거나 실행해 주세요."
        agent = DuringAgent()
        success = await agent.process_meeting(meeting_id)
        return f"During Agent 실행 완료: {meeting_id}" if success else f"During Agent 실행 실패: {meeting_id}"

    if normalized.startswith("status "):
        meeting_id = _resolve_meeting_reference(normalized.split(maxsplit=1)[1].strip())
        if not meeting_id:
            return "최근 미팅이 없습니다. 먼저 미팅을 생성하거나 실행해 주세요."
        agent = DuringAgent()
        state = agent.drive_svc.load_meeting_state(meeting_id)
        if not state:
            return f"상태 정보 없음: {meeting_id}"
        if "상태" in compact and ("방금" in compact or "최근" in compact):
            return _format_demo_status(state)
        return format_meeting_status(state)

    if normalized.startswith("bundle "):
        meeting_id = _resolve_meeting_reference(normalized.split(maxsplit=1)[1].strip())
        if not meeting_id:
            return "최근 미팅이 없습니다. 먼저 미팅을 생성하거나 실행해 주세요."
        if any(keyword in compact for keyword in ["결과", "번들", "bundle"]):
            drive_svc = DuringAgent().drive_svc
            state = drive_svc.load_meeting_state(meeting_id)
            if not state.get("after_completed"):
                success = await DuringAgent().process_meeting(meeting_id, trigger_after_agent=True)
                if not success:
                    return "회의록 및 후속 처리 실행 실패"
        bundle = _build_meeting_bundle(meeting_id)
        if not bundle:
            return f"bundle 정보 없음: {meeting_id}"
        if any(keyword in compact for keyword in ["결과", "번들", "bundle"]):
            return _format_demo_result_payload(bundle)
        return _format_bundle_summary(bundle)

    if normalized == "list" or normalized.startswith("list "):
        parts = normalized.split()
        limit, filters = _parse_ops_arguments(parts[1:], default_limit=5)
        entries = _list_meeting_states(limit=limit, **filters)
        decorated = _decorate_recent_entries(entries)
        return format_recent_meetings(decorated, limit=limit)

    if normalized == "dashboard" or normalized.startswith("dashboard "):
        parts = normalized.split()
        limit, filters = _parse_ops_arguments(parts[1:], default_limit=10)
        entries = _list_meeting_states(limit=limit, **filters)
        dashboard = _build_dashboard(entries)
        return format_dashboard_snapshot(dashboard)

    if normalized == "doctor" or normalized.startswith("doctor "):
        parts = normalized.split()
        limit, filters = _parse_ops_arguments(parts[1:], default_limit=5)
        report = _build_doctor_report(limit=limit, **filters)
        return format_doctor_summary(report)

    if normalized.startswith("agenda "):
        parts = normalized.split(maxsplit=2)
        if len(parts) < 3:
            return "형식: /meetagain agenda <meeting_id> <agenda>"

        meeting_id = _resolve_meeting_reference(parts[1].strip())
        if not meeting_id:
            return "최근 미팅이 없습니다. 먼저 미팅을 생성하거나 실행해 주세요."
        agenda = parts[2].strip()
        agent = BeforeAgent()
        success = await agent.register_agenda(meeting_id, agenda)
        if not success:
            return "어젠다 등록 실패"
        return (
            "📝 어젠다 등록 완료\n"
            "Google Calendar 이벤트 설명란에도 반영했어요."
        )

    if normalized.startswith("after "):
        meeting_id = _resolve_meeting_reference(normalized.split(maxsplit=1)[1].strip())
        if not meeting_id:
            return "최근 미팅이 없습니다. 먼저 미팅을 생성하거나 실행해 주세요."
        agent = AfterAgent()
        success = await agent.process_meeting(meeting_id)
        return f"After Agent 실행 완료: {meeting_id}" if success else f"After Agent 실행 실패: {meeting_id}"

    if normalized.startswith("pipeline "):
        meeting_id = _resolve_meeting_reference(normalized.split(maxsplit=1)[1].strip())
        if not meeting_id:
            return "최근 미팅이 없습니다. 먼저 미팅을 생성하거나 실행해 주세요."
        agent = DuringAgent()
        success = await agent.process_meeting(meeting_id, trigger_after_agent=True)
        if not success:
            return "회의록 및 후속 처리 실행 실패"
        return _format_pipeline_completion(meeting_id)

    if normalized.startswith("rerun "):
        parts = normalized.split()
        if len(parts) < 2:
            return "형식: /meetagain rerun <meeting_id> [before|during|after|pipeline|auto]"

        meeting_id = _resolve_meeting_reference(parts[1].strip())
        if not meeting_id:
            return "최근 미팅이 없습니다. 먼저 미팅을 생성하거나 실행해 주세요."
        stage = parts[2].strip() if len(parts) > 2 else "auto"

        success = await _rerun_meeting_from_slack(meeting_id, stage)
        return f"재실행 완료: {meeting_id} ({stage})" if success else f"재실행 실패: {meeting_id} ({stage})"

    llm_routed = await _route_with_llm(original)
    if llm_routed:
        routed_response = await _dispatch_routed_intent(llm_routed)
        if routed_response:
            return routed_response

    if prefer_help:
        return _help_text()
    return await _chat_fallback_reply(original)


async def dispatch_message_event(event: dict, client) -> Optional[Union[str, dict]]:
    channel_monitor_response = await dispatch_channel_message_event(event, client)
    if channel_monitor_response:
        return channel_monitor_response

    text = (event.get("text") or "").strip()
    files = event.get("files") or []
    pending_key = _pending_upload_key(event)
    if files:
        logger.info(
            "Slack file event received: channel=%s channel_type=%s subtype=%s files=%s text=%s",
            event.get("channel"),
            event.get("channel_type"),
            event.get("subtype"),
            [file.get("name") for file in files],
            text,
        )

    if not files and text and _should_bypass_pending_flow(text):
        return await dispatch_text_command(_strip_bot_mention(text), prefer_help=False)

    if not files and text and pending_key in _PENDING_AFTER_PIPELINES:
        return await _resolve_pending_after_confirm(event, client)

    if not files and text and pending_key in _PENDING_TRANSCRIPT_UPLOADS:
        return await _resolve_pending_transcript_upload(event, client)

    if files and (_looks_like_meeting_file_request(text, files) or _contains_supported_meeting_file(files)):
        return await _process_uploaded_file(event, client)

    if event.get("channel_type") == "im" and text:
        return await dispatch_text_command(text, prefer_help=False)

    return None


def _emit_say_response(say, response: Union[str, dict]) -> None:
    """Slack Bolt say()에 문자열/딕셔너리 응답을 안전하게 전달"""
    if isinstance(response, dict):
        say(**response)
        return
    say(response)


async def dispatch_channel_message_event(event: dict, client=None) -> Optional[dict]:
    """채널 메시지용 channel monitor 진입점"""
    agent = ChannelMonitorAgent()
    return await agent.handle_channel_message(event, client=client)


def _should_bypass_pending_flow(text: str) -> bool:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return False
    compact = re.sub(r"\s+", "", normalized.lower())
    if normalized.startswith("<@"):
        return True
    bypass_keywords = [
        "미팅 잡아줘",
        "미팅일정 잡아줘",
        "일정 잡아줘",
        "회의 잡아줘",
        "약속 잡아줘",
        "브리핑해줘",
        "결과 보여줘",
        "상태 보여줘",
        "운영 상태",
        "캘린더 등록",
    ]
    return any(keyword.replace(" ", "") in compact for keyword in [item.replace(" ", "") for item in bypass_keywords])


async def _handle_file_shared_event(event: dict, client) -> None:
    file_id = event.get("file_id")
    channel_id = event.get("channel_id") or event.get("channel")
    user_id = event.get("user_id") or event.get("user")
    if not file_id or not channel_id:
        logger.info("Ignoring file_shared without file_id/channel_id: %s", event)
        return

    response = client.files_info(file=file_id)
    file_info = response.get("file") or {}
    file_kind = _classify_uploaded_file(file_info)
    logger.info(
        "file_shared received: channel=%s user=%s file=%s kind=%s",
        channel_id,
        user_id,
        file_info.get("name"),
        file_kind,
    )

    if file_kind != "text":
        return
    payload = _download_slack_text_file(file_info, client)
    if not payload:
        client.chat_postMessage(
            channel=channel_id,
            text="업로드한 텍스트 파일을 읽지 못했어요. txt, md, srt, vtt 형식인지 확인해주세요.",
        )
        return

    candidates = _list_meeting_states(limit=5)
    if not candidates:
        client.chat_postMessage(
            channel=channel_id,
            text="업로드한 파일은 접수했지만 연결할 최근 미팅이 없어요. 먼저 미팅을 만들거나 meeting_id를 알려주세요.",
        )
        return

    pending_key = channel_id or user_id or "default"
    _PENDING_TRANSCRIPT_UPLOADS[pending_key] = {
        "file_kind": file_kind,
        "transcript": payload,
        "candidates": candidates[:5],
        "filename": file_info.get("name") or "업로드 파일",
    }

    client.chat_postMessage(
        channel=channel_id,
        text=_format_pending_transcript_prompt(file_info.get("name") or "업로드 파일", candidates[:5]),
    )


def _is_duplicate_event(event: dict) -> bool:
    key = event.get("client_msg_id") or event.get("event_ts") or event.get("ts")
    if not key:
        return False
    if key in _RECENT_EVENT_KEYS:
        return True
    _RECENT_EVENT_KEYS.append(key)
    return False


def _strip_bot_mention(text: str) -> str:
    parts = [part for part in text.split() if not part.startswith("<@")]
    return " ".join(parts).strip()


def _normalize_natural_command(text: str) -> str:
    normalized = text.strip()
    lowered = normalized.lower()
    compact = re.sub(r"\s+", "", lowered)

    if (
        lowered in {"오늘 미팅 일정 브리핑해줘", "오늘 미팅 브리핑해줘", "브리핑해줘", "오늘 일정 브리핑해줘"}
        or ("브리핑" in compact and "오늘" in compact and ("미팅" in compact or "일정" in compact))
        or compact == "브리핑해줘"
    ):
        return "before"

    if (
        lowered in {"방금 미팅 정리해줘", "방금 회의 정리해줘", "최근 미팅 정리해줘", "회의록 정리해줘"}
        or (("방금" in compact or "최근" in compact) and ("미팅" in compact or "회의" in compact) and ("정리" in compact or "회의록" in compact))
        or compact == "회의록정리해줘"
    ):
        return "pipeline latest"

    if (
        lowered in {"방금 미팅 상태 보여줘", "최근 미팅 상태 보여줘", "방금 상태 보여줘"}
        or (("방금" in compact or "최근" in compact) and "상태" in compact and ("미팅" in compact or compact == "방금상태보여줘"))
    ):
        return "status latest"

    if (
        lowered in {"방금 미팅 결과 보여줘", "최근 미팅 결과 보여줘", "방금 bundle 보여줘", "방금 번들 보여줘"}
        or (("방금" in compact or "최근" in compact) and ("결과" in compact or "번들" in compact or "bundle" in compact))
    ):
        return "bundle latest"

    if (
        lowered in {"오늘 운영 상태 보여줘", "운영 상태 보여줘", "지금 상태 점검해줘"}
        or ("운영" in compact and "상태" in compact)
        or ("상태점검" in compact)
    ):
        return "doctor"

    return normalized


def _help_text() -> str:
    return (
        "사용 가능한 명령:\n"
        "- `/meetagain help`\n"
        "- `/meetagain before`\n"
        "- `/meetagain create <title>|<start_iso>|<end_iso>|<attendee1,attendee2>|<agenda>|[template]`\n"
        "- `/meetagain update-company-knowledge`\n"
        "- `/meetagain during <meeting_id>`\n"
        "- `/meetagain status <meeting_id>`\n"
        "- `/meetagain bundle <meeting_id>`\n"
        "- `/meetagain list [limit]`\n"
        "- `/meetagain dashboard [limit] [needs-after|stalled-agenda|follow-up]`\n"
        "- `/meetagain doctor [limit] [needs-after|stalled-agenda|follow-up]`\n"
        "- `/meetagain rerun <meeting_id> [stage]`\n"
        "- `/meetagain agenda <meeting_id> <agenda>`\n"
        "- `/meetagain after <meeting_id>`\n"
        "- `/meetagain pipeline <meeting_id>`\n"
        "\n"
        "참고:\n"
        "- `<meeting_id>` 대신 `latest`, `최근`, `방금` 사용 가능"
    )


def _looks_like_meeting_file_request(text: str, files: list) -> bool:
    normalized = " ".join((text or "").split()).strip().lower()
    keywords = ["회의록", "정리", "트랜스크립트", "transcript", "요약", "이 파일로", "이걸로"]
    if any(keyword in normalized for keyword in keywords):
        return True

    allowed_suffixes = (".txt", ".md", ".markdown", ".srt", ".vtt")
    for file in files:
        name = (file.get("name") or "").lower()
        mimetype = (file.get("mimetype") or "").lower()
        if name.endswith(allowed_suffixes) or mimetype.startswith("text/"):
            return True
    return False


def _contains_supported_meeting_file(files: list) -> bool:
    for file in files:
        if _classify_uploaded_file(file) == "text":
            return True
    return False


def _classify_uploaded_file(file_info: dict) -> str:
    name = (file_info.get("name") or "").lower()
    mimetype = (file_info.get("mimetype") or "").lower()
    if name.endswith((".txt", ".md", ".markdown", ".srt", ".vtt")) or mimetype.startswith("text/"):
        return "text"
    return "unknown"


async def _process_uploaded_file(event: dict, client) -> Union[str, dict]:
    files = event.get("files") or []
    if not files:
        return "업로드된 파일을 찾지 못했습니다."
    primary_file = files[0]
    file_kind = _classify_uploaded_file(primary_file)
    if file_kind != "text":
        return "지원하지 않는 파일 형식입니다. transcript(txt/md/srt/vtt) 파일을 올려주세요."

    transcript = _download_slack_text_file(primary_file, client)
    if not transcript:
        return "업로드된 텍스트 파일을 읽지 못했습니다. txt, md, srt, vtt 형식으로 다시 올려주세요."

    text = (event.get("text") or "").strip()
    meeting_ref = _extract_meeting_reference_from_text(text)
    meeting_id = _resolve_meeting_reference(meeting_ref) if meeting_ref else None
    if not meeting_id:
        candidates = _match_recent_meetings_from_text(text)
        if len(candidates) == 1:
            meeting_id = candidates[0].get("meeting_id")
        else:
            candidates = candidates or _list_meeting_states(limit=5)
            if not candidates:
                return "연결할 미팅을 찾지 못했습니다. 먼저 미팅을 만들거나 meeting_id/미팅명을 함께 적어주세요."
            _PENDING_TRANSCRIPT_UPLOADS[_pending_upload_key(event)] = {
                "file_kind": file_kind,
                "transcript": transcript,
                "candidates": candidates[:5],
                "filename": (primary_file.get("name") or "업로드 파일"),
            }
            return _format_pending_transcript_prompt(primary_file.get("name") or "업로드 파일", candidates[:5])

    if not meeting_id:
        return "최근 미팅이 없습니다. 먼저 미팅을 만들거나 meeting_id를 함께 적어주세요."

    return await _run_transcript_pipeline(meeting_id, transcript, pending_key=_pending_upload_key(event))


def _download_slack_text_file(file_info: dict, client) -> Optional[str]:
    if not file_info:
        return None

    try:
        detailed = file_info
        file_id = file_info.get("id")
        if file_id:
            response = client.files_info(file=file_id)
            detailed = response.get("file", file_info)

        name = (detailed.get("name") or "").lower()
        mimetype = (detailed.get("mimetype") or "").lower()
        allowed_suffixes = (".txt", ".md", ".markdown", ".srt", ".vtt")
        if not (name.endswith(allowed_suffixes) or mimetype.startswith("text/")):
            return None

        download_url = detailed.get("url_private_download") or detailed.get("url_private")
        if not download_url:
            return None

        response = requests.get(
            download_url,
            headers={"Authorization": f"Bearer {Config.SLACK_BOT_TOKEN}"},
            timeout=30,
        )
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        return response.text
    except Exception as e:
        logger.error(f"Error downloading Slack file: {e}")
        return None


def _extract_meeting_reference_from_text(text: str) -> Optional[str]:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return None
    match = re.search(r"\b([a-z0-9]{16,})\b", normalized)
    if match:
        return match.group(1)
    if any(token in normalized for token in ["방금", "최근", "latest"]):
        return "latest"
    return None


def _pending_upload_key(event: dict) -> str:
    return event.get("channel") or event.get("user") or "default"


def _match_recent_meetings_from_text(text: str) -> list:
    normalized = " ".join((text or "").split()).strip().lower()
    if not normalized:
        return []

    entries = _list_meeting_states(limit=10)
    matches = []
    for entry in entries:
        title = (entry.get("title") or "").strip()
        title_lower = title.lower()
        company = title.split(" 미팅", 1)[0].split(" 회의", 1)[0].strip().lower() if title else ""
        if title_lower and title_lower in normalized:
            matches.append(entry)
            continue
        if company and company in normalized:
            matches.append(entry)
    return matches


def _format_pending_transcript_prompt(filename: str, candidates: list) -> str:
    lines = [
        "🎧 음성 파일 업로드 완료",
        "",
        "파일명",
        filename,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📌 연결할 미팅을 선택해주세요",
        "",
    ]
    for idx, entry in enumerate(candidates, start=1):
        title = entry.get("title", "미팅")
        start = _format_human_datetime(entry.get("start_time"))
        lines.append(f"{idx}. {title} ({start})")
    lines.extend(
        [
            "",
            "👉 번호 또는 meeting_id 입력",
            "",
            '(취소: "취소")',
        ]
    )
    return "\n".join(lines)


async def _resolve_pending_transcript_upload(event: dict, client) -> Optional[Union[str, dict]]:
    key = _pending_upload_key(event)
    pending = _PENDING_TRANSCRIPT_UPLOADS.get(key)
    if not pending:
        return None

    text = " ".join(((event.get("text") or "").split())).strip()
    if not text:
        return "번호나 meeting_id로 답장해주세요."

    if text in {"취소", "cancel", "그만"}:
        _PENDING_TRANSCRIPT_UPLOADS.pop(key, None)
        return "알겠습니다. 업로드한 transcript 연결을 취소했어요."

    meeting_id = None
    if text.isdigit():
        index = int(text) - 1
        candidates = pending.get("candidates") or []
        if 0 <= index < len(candidates):
            meeting_id = candidates[index].get("meeting_id")
    else:
        explicit_ref = _extract_meeting_reference_from_text(text)
        if explicit_ref:
            meeting_id = _resolve_meeting_reference(explicit_ref)
        if not meeting_id:
            matches = _match_recent_meetings_from_text(text)
            if len(matches) == 1:
                meeting_id = matches[0].get("meeting_id")

    if not meeting_id:
        return "어느 미팅인지 못 찾았어요. 번호나 meeting_id로 다시 알려주세요."

    _PENDING_TRANSCRIPT_UPLOADS.pop(key, None)
    return await _run_transcript_pipeline(
        meeting_id,
        pending.get("transcript", ""),
        pending_key=_pending_upload_key(event),
    )


async def _run_transcript_pipeline(meeting_id: str, transcript: str, pending_key: Optional[str] = None) -> Union[str, dict]:
    success = await DuringAgent().process_meeting(
        meeting_id,
        trigger_after_agent=False,
        transcript_text=transcript,
    )
    if not success:
        return "업로드한 transcript 처리에 실패했습니다. 파일 형식과 내용을 확인해주세요."
    drive_svc = DriveService()
    state = drive_svc.load_meeting_state(meeting_id) or {}
    key = pending_key or meeting_id
    _PENDING_AFTER_PIPELINES[key] = {"meeting_id": meeting_id}
    return _format_notes_ready_message(meeting_id, state, drive_svc)


def _format_human_datetime(value: Optional[str]) -> str:
    if not value:
        return "미정"
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime("%m/%d %H:%M")
    except Exception:
        return str(value)


def _format_processing_status(stage_label: str) -> str:
    return (
        "🔄 진행 상태\n\n"
        "현재 단계\n"
        f"→ {stage_label}\n\n"
        "예상 작업\n"
        "- 회의록 생성\n"
        "- 액션아이템 추출\n\n"
        "⏳ 잠시만 기다려주세요"
    )


def _response_to_text(response: Union[str, dict]) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        return response.get("text") or "처리가 완료됐어요."
    return "처리가 완료됐어요."


def _format_notes_ready_message(meeting_id: str, state: dict, drive_svc: DriveService) -> str:
    title = state.get("title") or meeting_id
    client_path = f"{Config.MEETING_NOTES_FOLDER}/{meeting_id}_client.md"
    internal_path = f"{Config.MEETING_NOTES_FOLDER}/{meeting_id}_internal.md"
    client_link = _format_artifact_reference(drive_svc, client_path, "클라이언트용 회의록")
    internal_link = _format_artifact_reference(drive_svc, internal_path, "내부용 회의록")
    return "\n".join(
        [
            "✅ 회의록 생성 완료",
            "",
            "대상 미팅",
            title,
            "",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "생성된 파일",
            f"• {client_link}",
            f"• {internal_link}",
            "",
            "다음 작업",
            "- Slack 요약 Draft 생성",
            "- Trello 업데이트 준비",
            "- 제안서/Contacts 업데이트",
            "",
            "👉 추가 작업을 진행하시겠어요?",
            "진행: `후속 진행`",
            "중지: `여기까지`",
        ]
    )


async def _resolve_pending_after_confirm(event: dict, client) -> Optional[Union[str, dict]]:
    key = _pending_upload_key(event)
    pending = _PENDING_AFTER_PIPELINES.get(key)
    if not pending:
        return None

    text = " ".join(((event.get("text") or "").split())).strip()
    if not text:
        return "추가 작업을 진행하려면 `후속 진행`, 중지하려면 `여기까지`라고 답장해주세요."

    if text in {"여기까지", "중지", "취소"}:
        _PENDING_AFTER_PIPELINES.pop(key, None)
        return "알겠습니다. 회의록까지만 생성하고 후속 작업은 진행하지 않을게요."

    if text not in {"후속 진행", "진행", "계속", "추가 작업 진행"}:
        return "후속 작업을 진행하려면 `후속 진행`, 중지하려면 `여기까지`라고 답장해주세요."

    meeting_id = pending.get("meeting_id")
    _PENDING_AFTER_PIPELINES.pop(key, None)
    _start_background_task(_continue_after_pipeline(meeting_id, event.get("channel"), client))
    return "\n".join(
        [
            "🔄 진행 상태",
            "",
            "현재 단계",
            "→ 후속 작업 생성 중",
            "",
            "예상 작업",
            "- Slack 요약 Draft 생성",
            "- Trello 업데이트 준비",
            "- 제안서/Contacts 업데이트",
            "",
            "⏳ 잠시만 기다려주세요",
        ]
    )


async def _continue_after_pipeline(meeting_id: str, channel: Optional[str], client) -> None:
    success = await AfterAgent().process_meeting(meeting_id)
    if not success:
        _post_background_message(client, channel, "후속 작업 생성에 실패했어요. 잠시 후 다시 시도해주세요.")
        return

    bundle = _build_meeting_bundle(meeting_id)
    if bundle:
        payload = _format_demo_result_payload(bundle)
        _post_background_message(client, channel, _response_to_text(payload))
    else:
        _post_background_message(client, channel, f"후속 작업을 완료했어요: {meeting_id}")


def _render_transcript_text(segments: list, fallback: str = "") -> str:
    lines = []
    for segment in segments:
        speaker = (segment.get("speaker") or "Speaker").strip()
        text = (segment.get("text") or "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines) or fallback


async def _route_with_llm(text: str) -> Optional[dict]:
    if not text or not Config.ANTHROPIC_API_KEY:
        return None

    try:
        client = Anthropic()
        now = datetime.now()
        prompt = f"""
사용자 Slack 메시지를 Meetagain 액션으로 라우팅하세요.
오늘 날짜: {now.date().isoformat()}
현재 시각대: Asia/Seoul

반드시 JSON만 반환하세요.

가능한 action:
- create_meeting
- before
- bundle
- status
- doctor
- agenda
- help
- none

규칙:
- create_meeting 이면 title, date(YYYY-MM-DD), time(HH:MM), duration_minutes, agenda 를 채우세요.
- 회사명이 있으면 title은 "<회사명> 미팅" 형식으로 만드세요.
- 참석자는 비워두세요. 기본 참석자는 시스템이 채웁니다.
- 사용자의 의도가 불명확하면 action을 none으로 하세요.

예시 출력:
{{"action":"create_meeting","title":"카카오 미팅","date":"2026-03-27","time":"17:30","duration_minutes":60,"agenda":"poc 제안"}}

사용자 메시지:
\"\"\"{text}\"\"\"
"""

        response = client.messages.create(
            model=Config.ANTHROPIC_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        payload = response.content[0].text.strip()
        json_match = re.search(r"\{.*\}", payload, re.DOTALL)
        if not json_match:
            return None
        data = json.loads(json_match.group(0))
        if not isinstance(data, dict):
            return None
        return data
    except Exception as e:
        logger.debug(f"LLM router skipped: {e}")
        return None


async def _dispatch_routed_intent(intent: dict) -> Optional[Union[str, dict]]:
    action = (intent.get("action") or "").strip().lower()
    if action in {"", "none"}:
        return None

    if action == "before":
        return await _run_before_command(demo_friendly=True)
    if action == "bundle":
        return await dispatch_text_command("bundle latest")
    if action == "status":
        return await dispatch_text_command("status latest")
    if action == "doctor":
        return await dispatch_text_command("doctor")
    if action == "agenda":
        agenda = (intent.get("agenda") or "").strip()
        if not agenda:
            return None
        return await dispatch_text_command(f"agenda latest {agenda}")
    if action == "help":
        return _help_text()
    if action != "create_meeting":
        return None

    try:
        title = (intent.get("title") or "").strip()
        date_str = (intent.get("date") or "").strip()
        time_str = (intent.get("time") or "").strip()
        agenda = (intent.get("agenda") or "").strip() or "미팅 목적 정리 및 다음 단계 논의"
        duration_minutes = int(intent.get("duration_minutes") or 60)
        if not title or not date_str or not time_str:
            return None

        start_time = datetime.fromisoformat(f"{date_str}T{time_str}:00")
        end_time = start_time + timedelta(minutes=duration_minutes)
        meeting = await BeforeAgent().create_meeting_with_briefing(
            title=title,
            start_time=start_time,
            end_time=end_time,
            attendees=_infer_demo_attendees(title),
            agenda=agenda,
            template="client",
        )
        return _format_meeting_created_response(meeting, agenda) if meeting else "미팅 생성 실패"
    except Exception as e:
        logger.debug(f"Routed create intent failed: {e}")
        return None


async def _chat_fallback_reply(text: str) -> Optional[str]:
    lowered = text.strip().lower()
    if lowered in {"아하", "오케이", "오키", "고마워", "감사", "알겠어", "알겠어요", "ㅇㅋ", "ok"}:
        return "좋아요. 미팅 생성, 브리핑, 회의 결과 정리, transcript 파일 처리까지 도와드릴 수 있어요."

    if not Config.ANTHROPIC_API_KEY:
        return (
            "도와드릴게요. 미팅 생성, 브리핑, 회의 결과 정리, transcript 파일 처리를 할 수 있어요.\n"
            "예: '내일 오전 10시에 LG전자와 회의 잡아줘' 또는 '이 파일로 회의록 정리해줘'"
        )

    try:
        client = Anthropic()
        prompt = f"""
너는 Slack 안에서 동작하는 미팅 비서다.
사용자 메시지에 짧고 자연스럽게 답하라.
가능하면 사용자가 다음 작업으로 이어가도록 도와라:
- 미팅 생성
- 오늘/내일 미팅 브리핑
- 방금 미팅 결과 보기
- 업로드한 transcript 파일 처리

규칙:
- 한국어로 답한다
- 2문장 이내로 짧게
- 명령어 목록을 길게 나열하지 않는다

사용자 메시지:
\"\"\"{text}\"\"\"
"""
        response = client.messages.create(
            model=Config.ANTHROPIC_MODEL,
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.debug(f"Chat fallback skipped: {e}")
        return "도와드릴게요. 미팅 생성, 브리핑, 회의 결과 정리, transcript 파일 처리 중 하나를 말씀해 주세요."


def _parse_create_command(text: str):
    payload = text.replace("create", "", 1).strip()

    # structured format
    if "|" in payload:
        parts = [part.strip() for part in payload.split("|")]
        if len(parts) < 5:
            return None

        try:
            return {
                "title": parts[0],
                "start_time": datetime.fromisoformat(parts[1]),
                "end_time": datetime.fromisoformat(parts[2]),
                "attendees": [item.strip() for item in parts[3].split(",") if item.strip()],
                "agenda": parts[4],
                "template": parts[5] if len(parts) > 5 and parts[5] else None,
            }
        except ValueError:
            return None

    # semi-natural format:
    # "내일 15:00 카카오 미팅 with a@b.com, c@d.com about agenda"
    # "내일 오후 3:00 카카오 미팅 with a@b.com about agenda"
    pattern = re.compile(
        r"^(?P<day>오늘|내일)\s+"
        r"(?:(?P<ampm>오전|오후)\s+)?"
        r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s+"
        r"(?P<title>.+?)\s+with\s+"
        r"(?P<attendees>.+?)"
        r"(?:\s+about\s+(?P<agenda>.+?))?"
        r"(?:\s+template\s+(?P<template>internal|client|review))?$"
    )
    match = pattern.match(payload)
    if not match:
        return None

    now = datetime.now()
    target_date = now.date()
    if match.group("day") == "내일":
        target_date = (now + timedelta(days=1)).date()

    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    ampm = match.group("ampm")

    if ampm == "오후" and hour < 12:
        hour += 12
    elif ampm == "오전" and hour == 12:
        hour = 0

    start_time = datetime.combine(target_date, datetime.min.time()).replace(hour=hour, minute=minute)
    end_time = start_time + timedelta(hours=1)

    attendees = [item.strip() for item in match.group("attendees").split(",") if item.strip()]
    agenda = (match.group("agenda") or "").strip()

    if not attendees:
        return None

    return {
        "title": match.group("title").strip(),
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees,
        "agenda": agenda,
        "template": match.group("template"),
    }


def _parse_korean_create_request(text: str):
    normalized = " ".join(text.split()).strip().rstrip(".!?")
    compact = re.sub(r"\s+", "", normalized.lower())
    if "잡아줘" not in compact and "만들어줘" not in compact and "생성해줘" not in compact:
        return None
    if not any(keyword in normalized for keyword in ["미팅", "일정", "회의", "약속"]):
        return None

    match = re.search(
        r"(?P<day>오늘|내일)\s*"
        r"(?:(?P<ampm>오전|오후)\s*)?"
        r"(?P<hour>\d{1,2})시(?:(?P<minute>\d{1,2})분?|(?P<half>반))?(?:에)?",
        normalized,
    )
    if not match:
        return None

    now = datetime.now()
    target_date = now.date()
    if match.group("day") == "내일":
        target_date = (now + timedelta(days=1)).date()

    hour = int(match.group("hour"))
    minute = 30 if match.group("half") else int(match.group("minute") or 0)
    ampm = match.group("ampm")
    if ampm == "오후" and hour < 12:
        hour += 12
    elif ampm == "오전" and hour == 12:
        hour = 0
    elif ampm is None and hour <= 7:
        hour += 12

    start_time = datetime.combine(target_date, datetime.min.time()).replace(hour=hour, minute=minute)
    end_time = start_time + timedelta(hours=1)

    remainder = normalized[match.end():].strip()
    company = ""
    purpose = ""

    company_match = re.search(r"(?P<company>[가-힣A-Za-z0-9_/·&\-\s]+?)(?:와|과|이랑|랑)\s*(?:미팅|미팅일정|일정|회의|약속)", remainder)
    if company_match:
        company = company_match.group("company").strip().strip(",.")
    else:
        company_match = re.search(r"(?P<company>[가-힣A-Za-z0-9_/·&\-\s]+?)\s*(?:와|과)?\s*(?:미팅|미팅일정|일정|회의|약속)", remainder)
        if company_match:
            company = company_match.group("company").strip().strip(",.")

    purpose_match = re.search(r"(?:목적은|목적:|안건은|안건:|내용은|내용:)\s*(?P<purpose>.+?)(?:이야|야|입니다|이에요|예요)?$", normalized)
    if purpose_match:
        purpose = purpose_match.group("purpose").strip().rstrip(".")

    if not company:
        return _parse_compact_korean_create_request(compact)

    attendees = _infer_demo_attendees(company)
    title = f"{company} 미팅"
    if "/" in company:
        title = company

    agenda = purpose or "미팅 목적 정리 및 다음 단계 논의"
    template = "client"

    return {
        "title": title,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees,
        "agenda": agenda,
        "template": template,
    }


def _parse_compact_korean_create_request(compact: str):
    match = re.search(
        r"(?P<day>오늘|내일)"
        r"(?:(?P<ampm>오전|오후))?"
        r"(?P<hour>\d{1,2})시(?:(?P<minute>\d{1,2})분?|(?P<half>반))?(?:에)?"
        r"(?P<company>.+?)(?:와|과|이랑|랑)?(?:미팅|일정|회의|약속)"
        r"(?:잡아줘|만들어줘|생성해줘)"
        r"(?:목적은|목적:|안건은|안건:|내용은|내용:)?"
        r"(?P<purpose>.*)",
        compact,
    )
    if not match:
        return None

    now = datetime.now()
    target_date = now.date()
    if match.group("day") == "내일":
        target_date = (now + timedelta(days=1)).date()

    hour = int(match.group("hour"))
    minute = 30 if match.group("half") else int(match.group("minute") or 0)
    ampm = match.group("ampm")
    if ampm == "오후" and hour < 12:
        hour += 12
    elif ampm == "오전" and hour == 12:
        hour = 0
    elif ampm is None and hour <= 7:
        hour += 12

    start_time = datetime.combine(target_date, datetime.min.time()).replace(hour=hour, minute=minute)
    end_time = start_time + timedelta(hours=1)

    company = match.group("company").strip("/ ")
    if not company:
        return None

    purpose = (match.group("purpose") or "").strip()
    purpose = re.sub(r"(이야|야|입니다|이에요|예요)$", "", purpose).strip()
    agenda = purpose or "미팅 목적 정리 및 다음 단계 논의"

    return {
        "title": f"{company} 미팅",
        "start_time": start_time,
        "end_time": end_time,
        "attendees": _infer_demo_attendees(company),
        "agenda": agenda,
        "template": "client",
    }


def _infer_demo_attendees(company: str) -> list:
    return ["mincircle@parametacorp.com"]


async def _rerun_meeting_from_slack(meeting_id: str, stage: str) -> bool:
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


def _parse_optional_limit(value: Optional[str], default: int) -> int:
    if value is None:
        return default

    try:
        parsed = int(value)
    except ValueError:
        return default

    return parsed if parsed > 0 else default


def _parse_ops_arguments(parts: list, default_limit: int) -> tuple[int, dict]:
    limit = default_limit
    filters = {
        "needs_after": False,
        "stalled_agenda": False,
        "follow_up_needed": False,
    }

    remaining = list(parts)
    if remaining:
        candidate = _parse_optional_limit(remaining[0], default=-1)
        if candidate > 0:
            limit = candidate
            remaining = remaining[1:]

    for token in remaining:
        if token == "needs-after":
            filters["needs_after"] = True
        elif token == "stalled-agenda":
            filters["stalled_agenda"] = True
        elif token in {"follow-up", "follow-up-needed"}:
            filters["follow_up_needed"] = True

    return limit, filters


async def _run_before_command(demo_friendly: bool = False) -> str:
    agent = BeforeAgent()
    if demo_friendly:
        selected_meeting = _resolve_demo_briefing_meeting(agent)
        if not selected_meeting:
            meetings = agent.calendar_svc.get_upcoming_meetings(hours=24)
            external_meetings = [meeting for meeting in meetings if meeting.is_external]
            if not external_meetings:
                return "오늘 브리핑 대상 외부 미팅이 없습니다."
            selected_meeting = _select_demo_meeting(external_meetings)

        success = await agent.send_briefing(selected_meeting)
        if not success:
            return "오늘 브리핑 생성에 실패했습니다."

        draft = agent.drive_svc.load_generated_draft(selected_meeting.id, "before_briefing") or ""
        return draft or "오늘 브리핑이 준비됐어요."

    success = await agent.run_daily_briefing()
    if not success:
        return "Before Agent 실행 실패"

    entries = _list_meeting_states(limit=5)
    briefings = [entry for entry in entries if entry.get("before_briefing_created")]
    if not briefings:
        return (
            "Before Agent 실행 완료\n\n"
            "- 오늘 기준 브리핑 대상 외부 미팅이 없거나\n"
            "- 아직 생성된 브리핑 초안이 없습니다."
        )

    if demo_friendly:
        deduped = _dedupe_briefing_entries(briefings)
        selected = _select_demo_briefing_entry(deduped)
        meeting_id = selected.get("meeting_id", "unknown")
        draft = agent.drive_svc.load_generated_draft(meeting_id, "before_briefing") or ""
        return draft or "오늘 브리핑이 준비됐어요."

    deduped = _dedupe_briefing_entries(briefings)
    lines = [
        "오늘 브리핑 요약",
        f"- 브리핑 생성 수: {len(deduped)}",
    ]

    for entry in deduped[:3]:
        meeting_id = entry.get("meeting_id", "unknown")
        title = entry.get("title", "미정")
        start_time = entry.get("start_time", "미정")
        draft = agent.drive_svc.load_generated_draft(meeting_id, "before_briefing") or ""
        preview = _summarize_preview_text(draft, limit=220)
        lines.extend(
            [
                "",
                f"- {title}",
                f"  시간: {_format_human_datetime(start_time)}",
                f"  미리보기: {preview or '브리핑 초안 생성됨'}",
            ]
        )

    return "\n".join(lines)


def _resolve_demo_briefing_meeting(agent: BeforeAgent):
    recent_entries = _list_meeting_states(limit=20)
    candidates = []
    today = datetime.now().date()

    for entry in recent_entries:
        title = (entry.get("title") or "").strip()
        attendees = entry.get("attendees", []) or []
        start_raw = entry.get("start_time")
        if not title or not start_raw:
            continue

        try:
            start_time = datetime.fromisoformat(start_raw).date()
        except ValueError:
            start_time = None

        score = 0
        if start_time == today:
            score += 3
        if entry.get("is_external", True):
            score += 2
        if "데모" not in title:
            score += 1
        candidates.append((score, entry.get("updated_at", ""), entry))

    if not candidates:
        return None

    selected = sorted(candidates, reverse=True)[0][2]
    return agent._build_meeting_from_state(selected)


def _select_demo_briefing_entry(briefings: list) -> dict:
    def _score(entry: dict) -> tuple[int, str]:
        title = (entry.get("title") or "").lower()
        score = 0
        if "데모" not in title:
            score += 2
        if entry.get("is_external"):
            score += 1
        return score, entry.get("updated_at", "")

    return sorted(briefings, key=_score, reverse=True)[0]


def _select_demo_meeting(meetings: list) -> object:
    def _score(meeting) -> tuple[int, str]:
        title = (getattr(meeting, "title", "") or "").lower()
        score = 0
        if "데모" not in getattr(meeting, "title", ""):
            score += 1
        return score, getattr(meeting, "id", "")

    return sorted(meetings, key=_score, reverse=True)[0]


def _dedupe_briefing_entries(briefings: list) -> list:
    deduped = []
    seen = set()
    for entry in briefings:
        title = (entry.get("title") or "").strip().lower()
        start_time = (entry.get("start_time") or "")[:16]
        key = (title, start_time)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _summarize_preview_text(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _format_meeting_created_response(meeting, agenda: str) -> str:
    attendee_text = ", ".join(meeting.attendees) if meeting.attendees else "미정"
    lines = [
        "📅 미팅을 생성했어요. 확인해주세요.",
        "",
        f"제목: {meeting.title}",
        f"일시: {_format_meeting_window(meeting.start_time, meeting.end_time)}",
        f"참석자: {attendee_text}",
        f"Google Meet 링크: {meeting.meet_url or meeting.calendar_url or '생성됨'}",
    ]
    if agenda:
        lines.extend(["", "📝 입력된 어젠다", agenda])
    lines.extend(
        [
            "",
            "✅ Google Calendar 등록이 완료됐어요.",
            "필요하면 이어서 어젠다를 추가할 수 있어요.",
        ]
    )
    return "\n".join(lines)


def _format_pipeline_completion(meeting_id: str) -> str:
    agent = DuringAgent()
    state = agent.drive_svc.load_meeting_state(meeting_id)
    title = state.get("title", "미팅")
    agenda_status = state.get("agenda_status_count", 0)
    agenda_total = state.get("registered_agenda_count", 0)
    decision_count = state.get("decision_count", 0)
    action_item_count = state.get("action_item_count", 0)
    contact_updates = state.get("contact_update_count", 0)
    follow_up_needed = state.get("follow_up_needed", state.get("has_follow_up_meeting", False))

    details = _extract_meeting_details(agent.drive_svc, meeting_id)

    lines = [
        f"✅ 회의록 생성 완료 — {title}",
        "",
        "📄 산출물",
        "• 클라이언트용 회의록 생성",
        "• 내부용 회의록 생성",
        "• Slack 요약 초안 생성",
        "",
        f"📌 어젠다 진행률: {agenda_status}/{agenda_total}" if agenda_total else "📌 어젠다 진행률: 확인 필요",
        "⚡ 주요 결정사항",
    ]
    if details["decisions"]:
        lines.extend([f"• {item}" for item in details["decisions"][:3]])
    else:
        lines.append(f"• {decision_count}개 정리됨")
    lines.append("")
    lines.append("📋 액션아이템")
    if details["todos"]:
        lines.extend([f"• {item}" for item in details["todos"][:3]])
    else:
        lines.append(f"• {action_item_count}개 정리됨")
    if contact_updates:
        lines.append(f"• Contacts 업데이트 후보: {contact_updates}건")
    if follow_up_needed:
        lines.append("• 후속 미팅 초안 생성")
    lines.extend(
        [
            "",
            "자세한 결과를 보려면:",
            "• @hackathon_meetingagent 방금 미팅 상태 보여줘",
            "• @hackathon_meetingagent 방금 미팅 결과 보여줘",
        ]
    )
    return "\n".join(lines)


def _format_meeting_window(start_time: datetime, end_time: datetime) -> str:
    start_label = start_time.strftime("%Y-%m-%d (%a) %p %I:%M")
    end_label = end_time.strftime("%p %I:%M")
    return f"{start_label} ~ {end_label}"


def _format_human_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        ampm = "오전" if parsed.hour < 12 else "오후"
        hour = parsed.hour % 12 or 12
        return f"{parsed.month}월 {parsed.day}일 {ampm} {hour}:{parsed.minute:02d}"
    except Exception:
        return value


def _format_demo_status(state: dict) -> str:
    lines = [
        f"📌 {state.get('title', '미팅')} 진행 상태",
        "",
        f"• 현재 단계: {state.get('phase', '미정')}",
        f"• 어젠다 진행률: {state.get('agenda_status_count', 0)}/{state.get('registered_agenda_count', 0)}",
        f"• 결정사항: {state.get('decision_count', 0)}개",
        f"• 액션아이템: {state.get('action_item_count', 0)}개",
        f"• 담당자 알림: {state.get('assignee_dm_count', 0)}건",
        f"• 리마인더: {state.get('reminder_count', 0)}건",
        f"• Contacts 업데이트 후보: {state.get('contact_update_count', 0)}건",
    ]
    if state.get("follow_up_needed", state.get("has_follow_up_meeting", False)):
        lines.append("• 후속 미팅 제안 준비 완료")
    return "\n".join(lines)


def _format_demo_result(bundle: dict) -> str:
    state = bundle.get("state", {}) or {}
    drive_svc = DuringAgent().drive_svc
    details = _extract_meeting_details(drive_svc, bundle.get("meeting_id", ""))
    meeting_id = bundle.get("meeting_id", "")
    artifacts = state.get("artifacts", []) or []
    updates = _extract_update_details(drive_svc, meeting_id)
    client_path = f"{Config.MEETING_NOTES_FOLDER}/{meeting_id}_client.md"
    internal_path = f"{Config.MEETING_NOTES_FOLDER}/{meeting_id}_internal.md"
    client_link = _format_artifact_reference(drive_svc, client_path, "클라이언트용 회의록")
    internal_link = _format_artifact_reference(drive_svc, internal_path, "내부용 회의록")
    company_doc_paths = [artifact.get("path") for artifact in artifacts if artifact.get("type") == "company_contact" and artifact.get("path")]
    person_doc_paths = [artifact.get("path") for artifact in artifacts if artifact.get("type") == "person_contact" and artifact.get("path")]
    if not company_doc_paths and state.get("company_contact"):
        company_doc_paths = [state.get("company_contact")]
    if not person_doc_paths:
        if state.get("person_contacts"):
            person_doc_paths = [path for path in state.get("person_contacts", []) if path]
        elif state.get("person_contact"):
            person_doc_paths = [state.get("person_contact")]
    lines = [
        f"✅ {state.get('title', '미팅')} 결과",
        "",
        "⚡ 결정사항",
    ]
    if details["decisions"]:
        lines.extend([f"• {item}" for item in details["decisions"][:3]])
    else:
        lines.append(f"• {state.get('decision_count', 0)}개 정리됨")
    lines.extend(["", "📋 액션아이템"])
    if details["todos"]:
        lines.extend([f"• {item}" for item in details["todos"][:3]])
    else:
        lines.append(f"• {state.get('action_item_count', 0)}개 정리됨")
    if updates["company"]:
        lines.extend(["", "🏢 회사 업데이트"])
        lines.extend([f"• {item}" for item in updates["company"][:3]])
    if updates["people"]:
        lines.extend(["", "👤 인물 업데이트"])
        lines.extend([f"• {item}" for item in updates["people"][:3]])
    lines.extend(
        [
            "",
            "📄 생성된 파일",
            f"• {client_link}",
            f"• {internal_link}",
        ]
    )
    if company_doc_paths or person_doc_paths:
        lines.extend(["", "🗂 문서 업데이트"])
        lines.extend(
            [
                f"• {_format_artifact_reference(drive_svc, path, _label_from_contact_path(path, '회사 문서'))}"
                for path in company_doc_paths[:3]
            ]
        )
        lines.extend(
            [
                f"• {_format_artifact_reference(drive_svc, path, _label_from_contact_path(path, '인물 문서'))}"
                for path in person_doc_paths[:3]
            ]
        )
    extra_artifacts = []
    for artifact in artifacts:
        artifact_type = artifact.get("type")
        artifact_path = artifact.get("path")
        if artifact_type in {"meeting_note_client", "meeting_note_internal"}:
            continue
        if artifact_type and artifact_path:
            extra_artifacts.append(
                f"• {_format_artifact_reference(drive_svc, artifact_path, _humanize_artifact_label(artifact_type, artifact_path))}"
            )
    if extra_artifacts:
        lines.extend(extra_artifacts[:5])
    lines.extend(
        [
            "",
            "📌 Trello에 액션아이템 등록할까요?",
            "✅ 등록  ❌ 건너뜀",
        ]
    )
    return "\n".join(lines)


def _format_demo_result_payload(bundle: dict) -> dict:
    text = _format_demo_result(bundle)
    state = bundle.get("state", {}) or {}
    meeting_id = bundle.get("meeting_id", "")
    drive_svc = DuringAgent().drive_svc
    details = _extract_meeting_details(drive_svc, meeting_id)
    updates = _extract_update_details(drive_svc, meeting_id)
    artifacts = state.get("artifacts", []) or []
    company_doc_lines = [
        f"• {_format_artifact_reference_mrkdwn(drive_svc, artifact.get('path'), _label_from_contact_path(artifact.get('path'), '회사 문서'))}"
        for artifact in artifacts
        if artifact.get("type") == "company_contact" and artifact.get("path")
    ]
    person_doc_lines = [
        f"• {_format_artifact_reference_mrkdwn(drive_svc, artifact.get('path'), _label_from_contact_path(artifact.get('path'), '인물 문서'))}"
        for artifact in artifacts
        if artifact.get("type") == "person_contact" and artifact.get("path")
    ]
    if not company_doc_lines and state.get("company_contact"):
        company_doc_lines = [
            f"• {_format_artifact_reference_mrkdwn(drive_svc, state.get('company_contact'), _label_from_contact_path(state.get('company_contact'), '회사 문서'))}"
        ]
    if not person_doc_lines:
        if state.get("person_contacts"):
            person_doc_lines = [
                f"• {_format_artifact_reference_mrkdwn(drive_svc, path, _label_from_contact_path(path, '인물 문서'))}"
                for path in state.get("person_contacts", [])
                if path
            ]
        elif state.get("person_contact"):
            person_doc_lines = [
                f"• {_format_artifact_reference_mrkdwn(drive_svc, state.get('person_contact'), _label_from_contact_path(state.get('person_contact'), '인물 문서'))}"
            ]
    artifact_lines = [
        f"• {_format_artifact_reference_mrkdwn(drive_svc, artifact.get('path'), _humanize_artifact_label(artifact.get('type'), artifact.get('path')))}"
        for artifact in artifacts
        if artifact.get("type")
        and artifact.get("path")
        and artifact.get("type") not in {"meeting_note_client", "meeting_note_internal", "company_contact", "person_contact"}
    ]

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*✅ {state.get('title', '미팅')} 결과*"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*⚡ 결정사항*\n"
                + ("\n".join(f"• {item}" for item in details["decisions"][:3]) if details["decisions"] else "• 정리된 결정사항이 없습니다."),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*📋 액션아이템*\n"
                + ("\n".join(f"• {item}" for item in details["todos"][:5]) if details["todos"] else "• 정리된 액션아이템이 없습니다."),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🏢 회사 업데이트*\n"
                + ("\n".join(f"• {item}" for item in updates["company"][:3]) if updates["company"] else "• 회사 업데이트 제안이 없습니다."),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*👤 인물 업데이트*\n"
                + ("\n".join(f"• {item}" for item in updates["people"][:3]) if updates["people"] else "• 인물 업데이트 제안이 없습니다."),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*📄 생성된 파일*\n"
                f"• {_format_artifact_reference_mrkdwn(drive_svc, Config.MEETING_NOTES_FOLDER + '/' + meeting_id + '_client.md', '클라이언트용 회의록')}\n"
                f"• {_format_artifact_reference_mrkdwn(drive_svc, Config.MEETING_NOTES_FOLDER + '/' + meeting_id + '_internal.md', '내부용 회의록')}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🗂 문서 업데이트*\n"
                + ("\n".join((company_doc_lines + person_doc_lines)[:6]) if (company_doc_lines or person_doc_lines) else "• 생성된 회사/인물 문서가 없습니다."),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*📦 추가 산출물*\n"
                + ("\n".join(artifact_lines[:5]) if artifact_lines else "• 추가 산출물이 없습니다."),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*📌 Trello에 액션아이템 등록할까요?*"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "등록"},
                    "style": "primary",
                    "action_id": "trello_register",
                    "value": meeting_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "건너뜀"},
                    "action_id": "trello_skip",
                    "value": meeting_id,
                },
            ],
        },
    ]
    return {"text": text, "blocks": blocks}


def _extract_meeting_details(drive_svc, meeting_id: str) -> dict:
    notes = drive_svc.load_meeting_notes(meeting_id, version="internal") or ""
    decisions = _extract_section_items(notes, "## 주요 결론")
    todos = _extract_section_items(notes, "## To Do")
    return {"decisions": decisions, "todos": todos}


def _format_artifact_reference(drive_svc, path: str, label: str) -> str:
    link_getter = getattr(drive_svc, "get_drive_web_link", None)
    if callable(link_getter):
        link = link_getter(path)
        if link:
            return f"{label} ({link})"
    return f"{label} ({path})"


def _format_artifact_reference_mrkdwn(drive_svc, path: str, label: str) -> str:
    link_getter = getattr(drive_svc, "get_drive_web_link", None)
    if callable(link_getter):
        link = link_getter(path)
        if link:
            return f"<{link}|{label}>"
    return f"{label} (`{path}`)"


def _label_from_contact_path(path: str, fallback_prefix: str) -> str:
    filename = (path or "").rsplit("/", 1)[-1]
    stem = filename.rsplit(".", 1)[0].strip()
    if not stem:
        return fallback_prefix
    return f"{fallback_prefix}: {stem}"


def _humanize_artifact_label(artifact_type: str, artifact_path: str) -> str:
    mapping = {
        "proposal": "제안서 초안",
        "transcript": "transcript",
        "slack_summary": "Slack 요약",
        "follow_up_meeting": "후속 미팅 초안",
        "contact_updates": "Contacts 업데이트 초안",
        "before_briefing": "브리핑 초안",
    }
    if artifact_type == "reminder":
        return _label_from_contact_path(artifact_path, "리마인더")
    return mapping.get(artifact_type, artifact_type)


def _extract_update_details(drive_svc, meeting_id: str) -> dict:
    internal_notes = drive_svc.load_meeting_notes(meeting_id, version="internal") or ""
    contact_updates = drive_svc.load_generated_draft(meeting_id, "contact_updates") or ""
    state = drive_svc.load_meeting_state(meeting_id) or {}
    people = []
    company = []

    for line in contact_updates.splitlines():
        stripped = line.strip()
        if stripped.startswith("- 이름:"):
            people.append(stripped.replace("- 이름:", "", 1).strip())
        elif stripped.startswith("회사:"):
            company_name = stripped.replace("회사:", "", 1).strip()
            if company_name:
                company.append(f"{company_name} 관련 업데이트 필요")
        elif stripped.startswith("직책:") and people:
            people[-1] = f"{people[-1]} / {stripped.replace('직책:', '', 1).strip()}"
        elif stripped.startswith("메모:") and people:
            people[-1] = f"{people[-1]} / {stripped.replace('메모:', '', 1).strip()}"

    internal_lines = [line.strip("- ").strip() for line in internal_notes.splitlines() if line.strip().startswith("- ")]
    for line in internal_lines:
        if any(keyword in line for keyword in ["퇴사", "담당자", "후임", "전환", "인수인계"]):
            people.append(line)
        elif any(keyword in line for keyword in ["파트너", "모델", "POC", "수수료", "파일럿", "고투마켓", "도입"]):
            company.append(line)

    if not company:
        title = (state.get("title") or "").strip()
        if title:
            title_company = title.split(" 미팅", 1)[0].split(" 회의", 1)[0].strip()
            if title_company:
                company.append(f"{title_company} 관련 업데이트 필요")

    return {
        "people": _dedupe_preserve_order(people),
        "company": _dedupe_preserve_order(company),
    }


def _dedupe_preserve_order(items: list) -> list:
    seen = set()
    result = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _extract_section_items(text: str, header: str) -> list:
    if not text or header not in text:
        return []
    section = text.split(header, 1)[1]
    next_header = section.find("\n## ")
    if next_header != -1:
        section = section[:next_header]
    items = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def _format_trello_registration_summary(meeting_id: str) -> str:
    drive_svc = DuringAgent().drive_svc
    state = drive_svc.load_meeting_state(meeting_id) or {}
    title = state.get("title", "미팅")
    card_name = title.split(" 미팅", 1)[0].strip() or title
    action_count = state.get("action_item_count", 0)
    return "\n".join(
        [
            "📌 Trello에 액션아이템 등록 완료",
            f"- 보드: PARAMETA_Pipeline",
            f"- 리스트: Contact/Meeting",
            f"- 카드: {card_name}",
            f"- 체크리스트: Action Items",
            f"- 등록 항목 수: {action_count}",
        ]
    )


async def _register_trello_for_meeting(meeting_id: str) -> bool:
    if not meeting_id:
        return False

    agent = AfterAgent()
    parsed_data = _build_trello_payload_from_state(meeting_id)
    if not parsed_data:
        return False

    return await agent._update_trello(meeting_id, parsed_data)


def _build_trello_payload_from_state(meeting_id: str) -> Optional[dict]:
    drive_svc = DuringAgent().drive_svc
    state = drive_svc.load_meeting_state(meeting_id) or {}
    details = _extract_meeting_details(drive_svc, meeting_id)
    todos = details.get("todos", []) or []
    if not todos:
        return None

    action_items = []
    for todo in todos:
        parsed = _parse_todo_line(todo)
        if parsed:
            action_items.append(parsed)

    if not action_items:
        return None

    return {
        "topic": state.get("title", "미팅"),
        "attendees": state.get("attendees", []),
        "action_items": action_items,
    }


def _parse_todo_line(todo: str) -> Optional[dict]:
    text = (todo or "").strip()
    if not text:
        return None

    assignee = "미정"
    title = text
    due_date = "미정"

    if text.startswith("[") and "]" in text:
        assignee, remainder = text[1:].split("]", 1)
        title = remainder.strip()

    if " / 기한: " in title:
        title, due_date = title.split(" / 기한: ", 1)
        title = title.strip()
        due_date = due_date.strip()

    return {
        "title": title,
        "assignee": assignee.strip(),
        "due_date": due_date,
        "description": title,
    }


def _resolve_meeting_reference(reference: str) -> Optional[str]:
    normalized = reference.strip().lower()
    if normalized not in {"latest", "최근", "방금"}:
        return reference.strip()

    entries = _list_meeting_states(limit=1)
    if not entries:
        return None
    return entries[0].get("meeting_id")


def _decorate_recent_entries(entries: list) -> list:
    decorated = []
    for entry in entries:
        item = dict(entry)
        meeting_id = entry.get("meeting_id", "unknown")
        next_stage = resolve_auto_rerun_stage(entry)
        item["next_stage"] = next_stage
        item["artifact_count"] = len(entry.get("artifacts", []))
        item["attention_flags"] = _build_attention_flags(entry)
        registered_agenda_count = entry.get("registered_agenda_count", 0)
        agenda_status_count = entry.get("agenda_status_count", 0)
        if registered_agenda_count > 0:
            item["agenda_progress"] = f"{agenda_status_count}/{registered_agenda_count}"
        item["status_command"] = f"/meetagain status {meeting_id}"
        item["recommended_command"] = _build_slack_action_command(meeting_id, next_stage)
        decorated.append(item)
    return decorated


def _format_bundle_summary(bundle: dict) -> str:
    state = dict(bundle.get("state", {}) or {})
    notes = bundle.get("notes", {}) or {}
    artifacts = bundle.get("artifacts", []) or []
    if bundle.get("transcript") and "transcript_collected" not in state:
        state["transcript_collected"] = True
    if (notes.get("client") or notes.get("internal")) and "notes_generated" not in state:
        state["notes_generated"] = True
    artifact_type_list = sorted({artifact.get("type", "unknown") for artifact in artifacts})
    artifact_types = ", ".join(artifact_type_list) or "없음"
    agenda_progress = "없음"
    registered_agenda_count = state.get("registered_agenda_count", 0)
    agenda_status_count = state.get("agenda_status_count", 0)
    attention_flags = _build_attention_flags(state)
    next_stage = resolve_auto_rerun_stage(state)
    next_action = _build_slack_action_command(bundle.get("meeting_id", "unknown"), next_stage)
    if registered_agenda_count > 0:
        agenda_progress = f"{agenda_status_count}/{registered_agenda_count}"

    lines = [
        f"미팅 bundle 요약: {bundle.get('meeting_id', 'unknown')}",
        "",
        f"- 제목: {state.get('title', '미정')}",
        f"- 현재 단계: {state.get('phase', '미정')}",
        f"- transcript: {'있음' if bundle.get('transcript') else '없음'}",
        f"- client notes: {'있음' if notes.get('client') else '없음'}",
        f"- internal notes: {'있음' if notes.get('internal') else '없음'}",
        f"- 액션아이템 수: {state.get('action_item_count', 0)}",
        f"- 결정사항 수: {state.get('decision_count', 0)}",
        f"- 어젠다 진행률: {agenda_progress}",
        f"- Slack 요약 생성: {state.get('after_completed', False) or 'slack_summary' in artifact_type_list}",
        f"- 제안서 초안 생성: {state.get('proposal_draft_created', False)}",
        f"- 리서치 초안 생성: {state.get('research_draft_created', False)}",
        f"- 후속 미팅 필요: {state.get('follow_up_needed', state.get('has_follow_up_meeting', False))}",
        f"- 후속 미팅 초안 생성: {state.get('follow_up_draft_created', False)}",
        f"- 후속 미팅 캘린더 생성: {state.get('follow_up_calendar_created', False)}",
        f"- 산출물 수: {len(artifacts)}",
        f"- 산출물 타입: {artifact_types}",
        f"- 주의 플래그: {', '.join(attention_flags) if attention_flags else '없음'}",
        "",
        f"- 다음 권장 작업: {next_action}",
        f"- 자세한 상태: /meetagain status {bundle.get('meeting_id', 'unknown')}",
        f"- 전체 bundle 확인: python3 -m src.cli bundle --meeting-id {bundle.get('meeting_id', 'unknown')}",
    ]
    if artifact_type_list:
        lines.extend(
            [
                "",
                "주요 산출물",
                *[f"- {artifact_type}" for artifact_type in artifact_type_list[:5]],
            ]
        )
    return "\n".join(lines)


def _build_slack_action_command(meeting_id: str, next_stage: str) -> str:
    if next_stage == "pipeline":
        return f"/meetagain pipeline {meeting_id}"
    return f"/meetagain rerun {meeting_id} {next_stage}"


def _build_attention_flags(state: dict) -> list:
    flags = []

    if not state.get("transcript_collected"):
        flags.append("transcript 없음")

    if state.get("transcript_collected") and not state.get("notes_generated"):
        flags.append("회의록 없음")

    if state.get("notes_generated") and not state.get("after_completed"):
        flags.append("after 미완료")

    registered_agenda_count = state.get("registered_agenda_count", 0)
    agenda_status_count = state.get("agenda_status_count", 0)
    if registered_agenda_count > agenda_status_count:
        flags.append("어젠다 미완료")

    follow_up_needed = state.get("follow_up_needed", state.get("has_follow_up_meeting", False))
    if follow_up_needed and not state.get("follow_up_calendar_created", False):
        flags.append("후속 미팅 대기")

    return flags


def main():
    app = _build_app()
    handler = SocketModeHandler(app, Config.SLACK_APP_TOKEN)
    logger.info("Meetagain Slack app started")
    handler.start()


if __name__ == "__main__":
    main()
