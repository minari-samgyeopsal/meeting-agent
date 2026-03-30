from pathlib import Path

from src.agents.during_agent import DuringAgent


def test_load_transcript_from_file(tmp_path):
    transcript_file = tmp_path / "transcript.txt"
    transcript_file.write_text("회의 transcript", encoding="utf-8")

    agent = DuringAgent.__new__(DuringAgent)
    loaded = agent.load_transcript_from_file(str(transcript_file))

    assert loaded == "회의 transcript"


def test_render_client_notes_contains_decisions_and_actions():
    agent = DuringAgent.__new__(DuringAgent)
    structured = {
        "meeting_title": "카카오 미팅",
        "attendees": ["홍길동", "김민환"],
        "agenda": ["서비스 소개", "다음 단계 협의"],
        "decisions": ["파일럿 진행"],
        "action_items": [
            {
                "title": "레퍼런스 전달",
                "assignee": "홍길동",
                "due_date": "2026-03-30",
            }
        ],
    }

    rendered = agent._render_client_notes(structured)

    assert "[클라이언트용] 카카오 미팅" in rendered
    assert "- 파일럿 진행" in rendered
    assert "- [홍길동] 레퍼런스 전달 / 기한: 2026-03-30" in rendered


def test_render_internal_notes_contains_agenda_status_and_internal_notes():
    agent = DuringAgent.__new__(DuringAgent)
    structured = {
        "meeting_title": "카카오 미팅",
        "attendees": ["홍길동"],
        "agenda": ["서비스 소개"],
        "decisions": [],
        "action_items": [],
        "discussion_points": ["광고 데이터 검증 니즈 확인"],
        "agenda_status": [{"item": "서비스 소개", "status": "논의됨"}],
        "internal_notes": ["예산 논의는 다음 미팅으로 이월"],
        "next_steps": ["레퍼런스 전달"],
    }

    rendered = agent._render_internal_notes(structured)

    assert "## 어젠다 달성 체크" in rendered
    assert "- 서비스 소개: 논의됨" in rendered
    assert "- 예산 논의는 다음 미팅으로 이월" in rendered
    assert "- 레퍼런스 전달" in rendered
