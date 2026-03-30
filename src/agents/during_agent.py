"""
During Agent - 미팅 진행 중 지원 에이전트

역할: 미팅 종료 후 transcript 기반 회의록 생성 (FR-D01~D06 중심)

참고:
- 1단계: Google Meet transcript 기반 종료 후 처리
- 2단계: 실시간 피드백은 추후 확장
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from anthropic import Anthropic

from src.services.drive_service import DriveService
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DuringAgent:
    """미팅 transcript 기반 회의록 생성 에이전트"""
    
    def __init__(self):
        """초기화"""
        self.drive_svc = DriveService()
        self.claude_client = Anthropic() if Config.ANTHROPIC_API_KEY else None
        logger.info("DuringAgent initialized")
    
    async def process_meeting(
        self,
        meeting_id: str,
        trigger_after_agent: bool = False,
        transcript_text: Optional[str] = None,
    ) -> bool:
        """
        transcript 수집부터 회의록 저장까지 처리
        """
        try:
            transcript = transcript_text or await self.collect_transcript(meeting_id)
            if not transcript and (Config.DRY_RUN or Config.ALLOW_TRANSCRIPT_FALLBACK):
                transcript = self._build_fallback_transcript(meeting_id)
                self.drive_svc.save_meeting_transcript(meeting_id, transcript)
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "transcript",
                    f"{Config.MEETING_TRANSCRIPTS_FOLDER}/{meeting_id}.txt",
                )
                self.drive_svc.update_meeting_state(
                    meeting_id,
                    {
                        "meeting_id": meeting_id,
                        "phase": "during",
                        "transcript_collected": True,
                    },
                )

            if not transcript:
                logger.warning(f"No transcript found for meeting {meeting_id}")
                return False

            if transcript_text:
                self.drive_svc.save_meeting_transcript(meeting_id, transcript_text)
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "transcript",
                    f"{Config.MEETING_TRANSCRIPTS_FOLDER}/{meeting_id}.txt",
                )
                self.drive_svc.update_meeting_state(
                    meeting_id,
                    {
                        "meeting_id": meeting_id,
                        "phase": "during",
                        "transcript_collected": True,
                    },
                )

            saved = await self.generate_meeting_notes(meeting_id, transcript)
            if not saved:
                return False

            if trigger_after_agent:
                from src.agents.after_agent import AfterAgent

                after_agent = AfterAgent()
                return await after_agent.process_meeting(meeting_id)

            return True

        except Exception as e:
            logger.error(f"DuringAgent.process_meeting error: {e}")
            return False

    async def collect_transcript(self, meeting_id: str) -> Optional[str]:
        """
        Transcript 수집 (FR-D01)
        
        Google Meet 종료 후 Drive에서 자동 수집
        
        Args:
            meeting_id: Calendar 이벤트 ID
        
        Returns:
            transcript 텍스트 또는 None
        """
        transcript = self.drive_svc.load_meeting_transcript(meeting_id)
        if transcript:
            logger.info(f"Transcript loaded for meeting {meeting_id}")
            self.drive_svc.update_meeting_state(
                meeting_id,
                {
                    "meeting_id": meeting_id,
                    "phase": "during",
                    "transcript_collected": True,
                },
            )
        else:
            logger.warning(f"Transcript not found for meeting {meeting_id}")
        return transcript
    
    async def generate_meeting_notes(self, meeting_id: str, transcript: str) -> bool:
        """
        회의록 생성 (FR-D02~D04)
        
        - 클라이언트용 (어젠다 + 결론 + To Do)
        - 내부용 (클라이언트용 + 내부 의견 섹션)
        
        Args:
            meeting_id: Calendar 이벤트 ID
            transcript: 회의 트랜스크립트
        
        Returns:
            성공 여부
        """
        try:
            logger.info(f"Generating meeting notes for {meeting_id}")

            state = self.drive_svc.load_meeting_state(meeting_id)
            registered_agenda = self._extract_registered_agenda(state)
            structured = await self._structure_transcript(transcript, registered_agenda)
            if not structured:
                return False

            client_notes = self._render_client_notes(structured)
            internal_notes = self._render_internal_notes(structured)

            saved = self.drive_svc.save_meeting_notes(
                meeting_id=meeting_id,
                client_notes=client_notes,
                internal_notes=internal_notes,
            )
            if saved:
                logger.info(f"Meeting notes saved for {meeting_id}")
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "meeting_note_client",
                    f"{Config.MEETING_NOTES_FOLDER}/{meeting_id}_client.md",
                )
                self.drive_svc.append_meeting_artifact(
                    meeting_id,
                    "meeting_note_internal",
                    f"{Config.MEETING_NOTES_FOLDER}/{meeting_id}_internal.md",
                )
                self.drive_svc.update_meeting_state(
                    meeting_id,
                    {
                        "meeting_id": meeting_id,
                        "phase": "during",
                        "notes_generated": True,
                        "action_item_count": len(structured.get("action_items", [])),
                        "decision_count": len(structured.get("decisions", [])),
                        "registered_agenda_count": len(registered_agenda),
                        "agenda_status_count": len(structured.get("agenda_status", [])),
                    },
                )
            return saved

        except Exception as e:
            logger.error(f"DuringAgent.generate_meeting_notes error: {e}")
            return False
    
    async def extract_action_items(self, transcript: str) -> list:
        """
        액션 아이템 추출 (FR-D05)
        
        - 담당자
        - 업무
        - 기한
        
        Args:
            transcript: 회의 트랜스크립트
        
        Returns:
            액션 아이템 리스트
        """
        structured = await self._structure_transcript(transcript)
        return structured.get("action_items", []) if structured else []

    def load_transcript_from_file(self, filepath: str) -> Optional[str]:
        """
        로컬 transcript 파일 로드
        """
        try:
            path = Path(filepath)
            if not path.exists():
                logger.warning(f"Transcript file not found: {filepath}")
                return None

            return path.read_text(encoding="utf-8")

        except Exception as e:
            logger.error(f"DuringAgent.load_transcript_from_file error: {e}")
            return None

    def _build_fallback_transcript(self, meeting_id: str) -> str:
        state = self.drive_svc.load_meeting_state(meeting_id) or {}
        title = state.get("title", f"Meeting {meeting_id}")
        agenda = self._extract_registered_agenda(state)

        lines = [
            f"회의명: {title}",
            "참석자: owner@parametacorp.com, guest@example.com",
            "요약: DRY_RUN fallback transcript generated automatically.",
        ]

        if agenda:
            lines.append("어젠다:")
            lines.extend(f"- {item}" for item in agenda)

        lines.extend(
            [
                "논의:",
                "- 주요 안건을 검토했고 다음 단계 진행에 합의했습니다.",
                "- 필요한 후속 조치와 일정 공유를 진행합니다.",
            ]
        )
        return "\n".join(lines)

    async def _structure_transcript(self, transcript: str, registered_agenda: Optional[List[str]] = None) -> Dict:
        """
        transcript를 회의록 구조로 정리
        """
        try:
            if Config.DRY_RUN:
                return self._build_dry_run_structure(transcript, registered_agenda)

            registered_agenda = registered_agenda or []
            agenda_context = "\n".join(f"- {item}" for item in registered_agenda) if registered_agenda else "없음"

            prompt = f"""
다음 transcript를 분석해서 JSON만 반환해주세요.

사전에 등록된 어젠다가 있다면 이를 우선 참고해서 agenda와 agenda_status를 채워주세요.
등록된 어젠다:
{agenda_context}

반환 스키마:
{{
  "meeting_title": "문자열",
  "attendees": ["참석자"],
  "agenda": ["어젠다"],
  "summary": "회의 요약",
  "discussion_points": ["주요 논의사항"],
  "decisions": ["결정사항"],
  "action_items": [
    {{
      "title": "작업 제목",
      "assignee": "담당자명 또는 미정",
      "due_date": "YYYY-MM-DD 또는 미정",
      "description": "상세 설명"
    }}
  ],
  "next_steps": ["다음 단계"],
  "internal_notes": ["내부 메모 또는 리스크"],
  "agenda_status": [
    {{
      "item": "어젠다 항목",
      "status": "논의됨 또는 미논의"
    }}
  ]
}}

Transcript:
{transcript}
"""

            response = self.claude_client.messages.create(
                model=Config.ANTHROPIC_MODEL,
                max_tokens=3000,
                messages=[{"role": "user", "content": prompt}],
            )

            payload = response.content[0].text.strip()
            if "```json" in payload:
                payload = payload.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in payload:
                payload = payload.split("```", 1)[1].split("```", 1)[0].strip()

            data = json.loads(payload)
            data = self._normalize_agenda_status(data, registered_agenda)
            logger.info(
                "Transcript structured successfully: %s action items",
                len(data.get("action_items", [])),
            )
            return data

        except Exception as e:
            logger.error(f"DuringAgent._structure_transcript error: {e}")
            if Config.DRY_RUN:
                return self._build_dry_run_structure(transcript, registered_agenda)
            return self._build_structured_fallback_structure(transcript, registered_agenda)

    def _build_dry_run_structure(self, transcript: str, registered_agenda: Optional[List[str]] = None) -> Dict:
        snippet = transcript.strip().splitlines()
        summary = snippet[0] if snippet else "DRY RUN transcript"
        agenda = registered_agenda or [
            "파라메타 DID 솔루션 소개",
            "카카오 내부 인증 시스템 현황 파악",
            "파일럿 도입 범위 협의",
        ]
        return {
            "meeting_title": "카카오 미팅",
            "attendees": ["ryu.hyeokgon@parametacorp.com", "minwhan@kakao.com"],
            "agenda": agenda,
            "summary": "카카오 DID 솔루션 도입 논의를 진행했고 1단계 파일럿 범위와 검토 일정에 합의했습니다.",
            "discussion_points": [
                "카카오 사내 임직원 인증 모듈 대상으로 1단계 파일럿 범위를 검토했습니다.",
                "기술 검토 기간은 2주로 두고, 연동 문서 공유 후 내부 기술팀 검토를 진행하기로 했습니다.",
            ],
            "decisions": ["1단계 파일럿: 카카오 사내 임직원 인증 모듈 (500명)"],
            "action_items": [
                {
                    "title": "기술 연동 문서 발송",
                    "assignee": "류혁곤",
                    "due_date": "2026-03-31",
                    "description": "카카오 측 기술 검토를 위한 연동 문서와 레퍼런스 패키지를 전달합니다.",
                },
                {
                    "title": "내부 기술팀 검토 요청",
                    "assignee": "김민환",
                    "due_date": "2026-03-31",
                    "description": "카카오 내부 기술팀 검토와 파일럿 대상 범위 확인을 진행합니다.",
                },
            ],
            "next_steps": ["양사 다음 미팅 일정 확정", "파일럿 범위 및 기술 검토 일정 확정"],
            "internal_notes": [
                "파일럿 제안에 대해 긍정적 반응이 있었고, 숫자와 레퍼런스 근거를 중요하게 확인했습니다.",
                "다음 미팅 전 공공기관 레퍼런스와 기술 문서를 함께 전달하는 것이 유효합니다.",
            ],
            "agenda_status": self._build_dry_run_agenda_status(agenda, discussed_all=True),
        }

    def _build_structured_fallback_structure(self, transcript: str, registered_agenda: Optional[List[str]] = None) -> Dict:
        agenda = self._extract_section_items(transcript, "## 어젠다") or registered_agenda or []
        decisions = self._extract_section_items(transcript, "## 주요 결론")
        discussion_points = self._extract_section_items(transcript, "## 주요 논의사항")
        next_steps = self._extract_section_items(transcript, "## 다음 단계")
        internal_notes = self._extract_section_items(transcript, "## 내부 메모")
        todo_lines = self._extract_section_items(transcript, "## To Do")
        attendees = self._parse_attendee_section(transcript)
        title = self._extract_transcript_title(transcript)
        action_items = [item for item in (self._parse_action_item_line(line) for line in todo_lines) if item]
        summary = discussion_points[0] if discussion_points else (transcript.strip().splitlines()[0] if transcript.strip() else "회의 transcript")

        return {
            "meeting_title": title,
            "attendees": attendees,
            "agenda": agenda,
            "summary": summary,
            "discussion_points": discussion_points,
            "decisions": decisions,
            "action_items": action_items,
            "next_steps": next_steps,
            "internal_notes": internal_notes,
            "agenda_status": self._build_dry_run_agenda_status(agenda, discussed_all=bool(decisions or discussion_points)),
        }

    def _extract_transcript_title(self, transcript: str) -> str:
        for line in transcript.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(("참석", "##", "-", "*")):
                return stripped
        return "미팅"

    def _parse_attendee_section(self, transcript: str) -> List[str]:
        for line in transcript.splitlines():
            stripped = line.strip()
            if not stripped.startswith("참석"):
                continue

            raw_value = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            attendees = []
            for part in [chunk.strip() for chunk in raw_value.split(",") if chunk.strip()]:
                if "@" in part:
                    attendees.append(part)
                    continue
                name = re.sub(r"\s*\(.*?\)\s*", "", part).strip()
                if not name:
                    continue
                attendees.append(name)
            return attendees
        return []

    def _extract_section_items(self, text: str, header: str) -> List[str]:
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

    def _parse_action_item_line(self, line: str) -> Optional[Dict]:
        text = (line or "").strip()
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

    def _extract_registered_agenda(self, state: Dict) -> List[str]:
        agenda_text = (state or {}).get("latest_agenda") or (state or {}).get("description") or ""
        if not agenda_text:
            return []

        items = []
        for line in agenda_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            items.append(stripped.lstrip("-*• ").strip())

        return [item for item in items if item]

    def _normalize_agenda_status(self, data: Dict, registered_agenda: List[str]) -> Dict:
        agenda = data.get("agenda") or []
        agenda_status = data.get("agenda_status") or []

        if not registered_agenda:
            return data

        existing_map = {
            item.get("item", "").strip(): item.get("status", "미정")
            for item in agenda_status
            if item.get("item")
        }

        normalized = []
        for agenda_item in registered_agenda:
            normalized.append(
                {
                    "item": agenda_item,
                    "status": existing_map.get(agenda_item, "미논의"),
                }
            )

        if not agenda:
            data["agenda"] = registered_agenda
        data["agenda_status"] = normalized
        return data

    def _build_dry_run_agenda_status(self, agenda: List[str], discussed_all: bool = False) -> List[Dict]:
        if not agenda:
            return [{"item": "안건 확인", "status": "논의됨"}]

        return [
            {
                "item": agenda_item,
                "status": "논의됨" if discussed_all or index == 0 else "미논의",
            }
            for index, agenda_item in enumerate(agenda)
        ]

    def _render_client_notes(self, structured: Dict) -> str:
        agenda = structured.get("agenda", [])
        decisions = structured.get("decisions", [])
        action_items = structured.get("action_items", [])
        attendees = structured.get("attendees", [])

        lines = [
            f"# [클라이언트용] {structured.get('meeting_title', '미팅 회의록')}",
            "",
            f"참석: {', '.join(attendees) if attendees else '미정'}",
            "",
            "## 어젠다",
        ]

        if agenda:
            lines.extend([f"- {item}" for item in agenda])
        else:
            lines.append("- 미정")

        lines.extend(["", "## 주요 결론"])
        if decisions:
            lines.extend([f"- {item}" for item in decisions])
        else:
            lines.append("- 결정사항 없음")

        lines.extend(["", "## To Do"])
        if action_items:
            for item in action_items:
                assignee = item.get("assignee", "미정")
                due_date = item.get("due_date", "미정")
                title = item.get("title", "")
                lines.append(f"- [{assignee}] {title} / 기한: {due_date}")
        else:
            lines.append("- 액션 아이템 없음")

        return "\n".join(lines)

    def _render_internal_notes(self, structured: Dict) -> str:
        client_notes = self._render_client_notes(structured)
        discussion_points = structured.get("discussion_points", [])
        next_steps = structured.get("next_steps", [])
        internal_notes = structured.get("internal_notes", [])
        agenda_status = structured.get("agenda_status", [])

        lines = [
            client_notes,
            "",
            "## 주요 논의사항",
        ]

        if discussion_points:
            lines.extend([f"- {item}" for item in discussion_points])
        else:
            lines.append("- 기록 없음")

        lines.extend(["", "## 어젠다 달성 체크"])
        if agenda_status:
            for item in agenda_status:
                lines.append(f"- {item.get('item', '미정')}: {item.get('status', '미정')}")
        else:
            lines.append("- 체크 정보 없음")

        lines.extend(["", "## 내부 메모"])
        if internal_notes:
            lines.extend([f"- {item}" for item in internal_notes])
        else:
            lines.append("- 내부 의견 작성 전")

        lines.extend(["", "## 다음 단계"])
        if next_steps:
            lines.extend([f"- {item}" for item in next_steps])
        else:
            lines.append("- 추후 정리")

        return "\n".join(lines)
