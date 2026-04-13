"""
Google Calendar 서비스 (gws CLI 기반)

사용 가능한 메서드:
- get_upcoming_meetings: 향후 24시간 미팅 목록 조회 (FR-B01)
- parse_meeting: 미팅 정보 파싱 (FR-B02)
- create_meeting: 미팅 생성
- add_attendees: 참석자 추가
- update_agenda: 미팅 설명/어젠다 업데이트
"""

import subprocess
import json
import uuid
import re
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo
import requests

from src.auth.google_auth_service import GoogleAuthService
from src.models.meeting import Meeting
from src.utils.config import Config
from src.utils.logger import get_logger
from src.utils.helpers import classify_emails

logger = get_logger(__name__)


class CalendarService:
    """Google Calendar 조작"""

    EXTERNAL_TITLE_MARKERS = [
        "카카오", "kakao", "네이버", "naver", "라인", "line",
        "쿠팡", "coupang", "당근", "토스", "toss", "lg전자",
        "삼성전자", "현대", "신한", "국민", "우리", "하나",
    ]
    EXTERNAL_COMPANY_SUFFIXES = [
        "전자", "카드", "은행", "증권", "캐피탈", "보험", "생명",
        "화재", "건설", "물산", "그룹", "리츠", "게임즈", "테크",
        "랩스", "모빌리티", "바이오", "제약", "에너지", "스튜디오",
    ]
    INTERNAL_TITLE_MARKERS = [
        "집", "사무실", "휴가", "연차", "병원", "운동", "개인",
        "internal", "내부", "사내", "weekly sync", "weekly", "sync",
        "standup", "1:1", "one-on-one", "all hands", "타운홀", "회고",
    ]
    
    def __init__(self):
        self.cmd_prefix = [Config.gws_bin(), "calendar"]
        self.google_auth_svc = GoogleAuthService()

    def _local_timezone(self):
        try:
            return ZoneInfo(Config.TIMEZONE)
        except Exception:
            return datetime.now().astimezone().tzinfo

    def _as_rfc3339(self, value: datetime) -> str:
        tz = self._local_timezone()
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)
        else:
            value = value.astimezone(tz)
        return value.isoformat()

    def _looks_external_meeting(self, title: str, attendees: List[str]) -> bool:
        _, external = classify_emails(attendees)
        if external:
            return True

        normalized_title = (title or "").lower()
        if not normalized_title:
            return False

        if any(marker in normalized_title for marker in self.EXTERNAL_TITLE_MARKERS):
            return True

        if any(marker in normalized_title for marker in self.INTERNAL_TITLE_MARKERS):
            return False

        # 참석자 정보가 비어 있는 캘린더 이벤트는 제목에서 회사명처럼 보이는 토큰을 한 번 더 본다.
        for token in re.split(r"[\s/()\-_,]+", title or ""):
            cleaned = token.strip()
            if len(cleaned) < 2:
                continue
            if any(suffix in cleaned for suffix in self.EXTERNAL_COMPANY_SUFFIXES):
                return True

        return False
    
    def get_upcoming_meetings(self, hours: int = 24) -> List[Meeting]:
        """
        향후 N시간 내 미팅 목록 조회 (FR-B01)
        
        Args:
            hours: 조회 시간 (기본 24시간)
        
        Returns:
            Meeting 객체 리스트
        """
        try:
            if Config.DRY_RUN_CALENDAR:
                meetings = self._build_dry_run_upcoming_meetings(hours)
                logger.info(f"[DRY RUN] Found {len(meetings)} upcoming meetings in {hours}h")
                return meetings

            oauth_meetings = self._get_upcoming_meetings_via_google_oauth(hours)
            if oauth_meetings is not None:
                return oauth_meetings

            now = datetime.now(self._local_timezone())
            time_max = now + timedelta(hours=hours)

            cmd = self.cmd_prefix + [
                "events",
                "list",
                "--params",
                json.dumps(
                    {
                        "calendarId": "primary",
                        "timeMin": self._as_rfc3339(now),
                        "timeMax": self._as_rfc3339(time_max),
                        "singleEvents": True,
                        "orderBy": "startTime",
                    },
                    ensure_ascii=False,
                ),
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, env=Config.build_subprocess_env())
            
            if result.returncode != 0:
                logger.error(f"gws calendar list failed: {result.stderr}")
                return []
            
            payload = json.loads(result.stdout)
            events = payload.get("items", []) if isinstance(payload, dict) else payload
            meetings = [self._parse_event(event) for event in events]
            
            logger.info(f"Found {len(meetings)} upcoming meetings in {hours}h")
            return meetings
        
        except Exception as e:
            logger.error(f"Error fetching upcoming meetings: {e}")
            return []

    def _build_dry_run_upcoming_meetings(self, hours: int) -> List[Meeting]:
        drive_svc = getattr(self, "_drive_service", None)
        if drive_svc is None:
            from src.services.drive_service import DriveService

            drive_svc = DriveService()
            self._drive_service = drive_svc

        now = datetime.now(self._local_timezone())
        deadline = now + timedelta(hours=hours)
        meetings: List[Meeting] = []

        for state in drive_svc.list_meeting_states():
            start_time_raw = state.get("start_time")
            if not start_time_raw:
                continue

            try:
                start_time = datetime.fromisoformat(start_time_raw)
            except ValueError:
                continue

            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=self._local_timezone())

            if not (now <= start_time <= deadline):
                continue

            attendees = state.get("attendees", [])
            meetings.append(
                Meeting(
                    id=state.get("meeting_id", ""),
                    title=state.get("title", "DRY RUN 미팅"),
                    start_time=start_time,
                    end_time=datetime.fromisoformat(state.get("end_time", start_time.isoformat()))
                    if state.get("end_time")
                    else start_time + timedelta(hours=1),
                    organizer_email=state.get("organizer_email", f"bot@{Config.GWS_DOMAIN}"),
                    attendees=attendees,
                    description=state.get("description", ""),
                    is_external=state.get("is_external", True),
                    calendar_url=state.get("calendar_url", "dry-run://calendar-event"),
                )
            )

        demo_start = now.replace(hour=15, minute=0, second=0, microsecond=0)
        if demo_start < now:
            demo_start = demo_start + timedelta(days=1)
        demo_end = demo_start + timedelta(hours=1)

        has_demo_meeting = any(meeting.id.startswith("dry-run-") for meeting in meetings)

        if not any(meeting.is_external for meeting in meetings) or (Config.DRY_RUN and not has_demo_meeting):
            meetings.append(
                Meeting(
                    id="dry-run-daily-briefing",
                    title="오늘 외부 데모 미팅",
                    start_time=demo_start,
                    end_time=demo_end,
                    organizer_email=f"bot@{Config.GWS_DOMAIN}",
                    attendees=["mincircle@parametacorp.com", "partner@kakao.com"],
                    description="서비스 소개\n니즈 확인\n후속 일정 논의",
                    is_external=True,
                    calendar_url="dry-run://calendar-event",
                )
            )

        meetings.sort(key=lambda item: item.start_time)
        return meetings
    
    def _parse_event(self, event: dict) -> Meeting:
        """Calendar 이벤트를 Meeting 객체로 변환 (FR-B02)"""
        start_time = self._parse_event_datetime(event.get("start", {}))
        end_time = self._parse_event_datetime(event.get("end", {}), is_end=True)

        # 참석자 이메일 추출
        attendees = []
        if "attendees" in event:
            attendees = [a.get("email") for a in event["attendees"] if "email" in a]
        
        # 내부/외부 분류
        is_external = self._looks_external_meeting(event.get("summary", ""), attendees)
        
        # Meet 링크 확인
        is_google_meet = False
        meet_url = None
        if "conferenceData" in event:
            conf = event["conferenceData"]
            if conf.get("conferenceSolution", {}).get("key", {}).get("type") == "hangoutsMeet":
                is_google_meet = True
                meet_url = conf.get("entryPoints", [{}])[0].get("uri")
        
        meeting = Meeting(
            id=event.get("id", ""),
            title=event.get("summary", ""),
            start_time=start_time,
            end_time=end_time,
            organizer_email=event.get("organizer", {}).get("email", ""),
            attendees=attendees,
            description=event.get("description", ""),
            location=event.get("location", ""),
            is_external=is_external,
            is_google_meet=is_google_meet,
            meet_url=meet_url,
            calendar_url=event.get("htmlLink", ""),
        )
        
        return meeting

    def _parse_event_datetime(self, payload: dict, is_end: bool = False) -> datetime:
        date_time = payload.get("dateTime")
        if date_time:
            return datetime.fromisoformat(date_time.replace("Z", "+00:00"))

        date_only = payload.get("date")
        if date_only:
            base = datetime.fromisoformat(date_only)
            if is_end:
                return base.replace(hour=23, minute=59, second=59)
            return base.replace(hour=0, minute=0, second=0)

        return datetime.now(self._local_timezone())
    
    def create_meeting(self, title: str, start_time: datetime, end_time: datetime,
                      attendees: List[str], description: str = "") -> Optional[Meeting]:
        """
        새 미팅 생성 (FR-B09)
        
        Args:
            title: 미팅 제목
            start_time: 시작 시간
            end_time: 종료 시간
            attendees: 참석자 이메일 목록
            description: 미팅 설명
        
        Returns:
            생성된 Meeting 객체
        """
        try:
            if Config.DRY_RUN_CALENDAR:
                logger.info(f"[DRY RUN] Would create meeting: {title}")
                fake_meet_url = "https://meet.google.com/abc-defg-hij"
                return Meeting(
                    id=f"dry-run-{uuid.uuid4().hex[:8]}",
                    title=title,
                    start_time=start_time,
                    end_time=end_time,
                    organizer_email=f"bot@{Config.GWS_DOMAIN}",
                    attendees=attendees,
                    description=description,
                    is_external=self._looks_external_meeting(title, attendees),
                    is_google_meet=True,
                    meet_url=fake_meet_url,
                    calendar_url="dry-run://calendar-event",
                )

            oauth_meeting = self._create_meeting_via_google_oauth(title, start_time, end_time, attendees, description)
            if oauth_meeting is not None:
                return oauth_meeting
            
            body = {
                "summary": title,
                "description": description,
                "start": {"dateTime": self._as_rfc3339(start_time), "timeZone": Config.TIMEZONE},
                "end": {"dateTime": self._as_rfc3339(end_time), "timeZone": Config.TIMEZONE},
                "attendees": [{"email": attendee} for attendee in attendees],
                "conferenceData": {
                    "createRequest": {
                        "requestId": f"meetagain-{uuid.uuid4().hex[:12]}",
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                },
            }
            cmd = self.cmd_prefix + [
                "events",
                "insert",
                "--params",
                json.dumps(
                    {
                        "calendarId": "primary",
                        "sendUpdates": "all",
                        "conferenceDataVersion": 1,
                    },
                    ensure_ascii=False,
                ),
                "--json",
                json.dumps(body, ensure_ascii=False),
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, env=Config.build_subprocess_env())
            
            if result.returncode != 0:
                logger.error(f"gws calendar create failed: {result.stderr}")
                return None
            
            event = json.loads(result.stdout)
            meeting = self._parse_event(event)
            
            logger.info(f"Meeting created: {title} ({meeting.id})")
            return meeting
        
        except Exception as e:
            logger.error(f"Error creating meeting: {e}")
            return None

    def create_draft_meeting(
        self,
        title: str,
        suggested_date: str,
        attendees: List[str],
        agenda: List[str],
        notes: str = "",
    ) -> bool:
        """
        후속 미팅 캘린더 초안 생성 (FR-A13 부분 구현)

        suggested_date가 YYYY-MM-DD 형식이면 기본 10:00~11:00 시간대로 초안을 만듭니다.
        """
        try:
            if suggested_date in ("", "미정", None):
                logger.info("Skipping follow-up draft meeting creation: suggested_date is undecided")
                return False

            base_date = datetime.fromisoformat(suggested_date)
            start_time = base_date.replace(hour=10, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(hours=1)

            description_lines = []
            if agenda:
                description_lines.append("후속 미팅 어젠다:")
                description_lines.extend([f"- {item}" for item in agenda])
            if notes:
                description_lines.extend(["", f"메모: {notes}"])

            meeting = self.create_meeting(
                title=title,
                start_time=start_time,
                end_time=end_time,
                attendees=attendees,
                description="\n".join(description_lines).strip(),
            )

            return meeting is not None

        except Exception as e:
            logger.error(f"Error creating draft follow-up meeting: {e}")
            return False
    
    def add_attendees(self, meeting_id: str, attendees: List[str]) -> bool:
        """
        미팅에 참석자 추가 (FR-B10)
        
        Args:
            meeting_id: Calendar 이벤트 ID
            attendees: 추가할 참석자 이메일 목록
        
        Returns:
            성공 여부
        """
        try:
            if Config.DRY_RUN_CALENDAR:
                logger.info(f"[DRY RUN] Would add attendees to {meeting_id}: {attendees}")
                return True

            oauth_result = self._add_attendees_via_google_oauth(meeting_id, attendees)
            if oauth_result is not None:
                return oauth_result
            
            event = self._get_event(meeting_id)
            if not event:
                logger.error(f"Failed to fetch event before attendee update: {meeting_id}")
                return False

            current = event.get("attendees", [])
            existing = {item.get("email") for item in current if item.get("email")}
            merged = current + [{"email": attendee} for attendee in attendees if attendee not in existing]

            cmd = self.cmd_prefix + [
                "events",
                "patch",
                "--params",
                json.dumps({"calendarId": "primary", "eventId": meeting_id, "sendUpdates": "all"}, ensure_ascii=False),
                "--json",
                json.dumps({"attendees": merged}, ensure_ascii=False),
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, env=Config.build_subprocess_env())
            
            if result.returncode != 0:
                logger.error(f"gws calendar add-attendees failed: {result.stderr}")
                return False
            
            logger.info(f"Attendees added to {meeting_id}: {attendees}")
            return True
        
        except Exception as e:
            logger.error(f"Error adding attendees: {e}")
            return False
    
    def update_description(self, meeting_id: str, description: str) -> bool:
        """
        미팅 설명 업데이트 (FR-B08, FR-B11)
        
        Args:
            meeting_id: Calendar 이벤트 ID
            description: 새 설명 (어젠다)
        
        Returns:
            성공 여부
        """
        try:
            if Config.DRY_RUN_CALENDAR:
                logger.info(f"[DRY RUN] Would update description for {meeting_id}")
                return True

            oauth_result = self._update_description_via_google_oauth(meeting_id, description)
            if oauth_result is not None:
                return oauth_result
            
            cmd = self.cmd_prefix + [
                "events",
                "patch",
                "--params",
                json.dumps({"calendarId": "primary", "eventId": meeting_id, "sendUpdates": "all"}, ensure_ascii=False),
                "--json",
                json.dumps({"description": description}, ensure_ascii=False),
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, env=Config.build_subprocess_env())
            
            if result.returncode != 0:
                logger.error(f"gws calendar update failed: {result.stderr}")
                return False
            
            logger.info(f"Meeting description updated: {meeting_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error updating description: {e}")
            return False

    def _get_event(self, meeting_id: str) -> Optional[dict]:
        """이벤트 단건 조회"""
        try:
            oauth_event = self._get_event_via_google_oauth(meeting_id)
            if oauth_event is not None:
                return oauth_event

            cmd = self.cmd_prefix + [
                "events",
                "get",
                "--params",
                json.dumps({"calendarId": "primary", "eventId": meeting_id}, ensure_ascii=False),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, env=Config.build_subprocess_env())
            if result.returncode != 0:
                logger.error(f"gws calendar events.get failed: {result.stderr}")
                return None
            return json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Error getting event {meeting_id}: {e}")
            return None

    def _get_upcoming_meetings_via_google_oauth(self, hours: int) -> Optional[List[Meeting]]:
        try:
            payload = self._google_calendar_request(
                "GET",
                "/calendars/primary/events",
                params=self._build_events_list_params(hours),
            )
            if payload is None:
                return None
            events = payload.get("items", []) if isinstance(payload, dict) else []
            meetings = [self._parse_event(event) for event in events]
            logger.info(f"Found {len(meetings)} upcoming meetings in {hours}h via Google OAuth")
            return meetings
        except Exception as e:
            logger.warning(f"Google OAuth calendar list failed, falling back to gws: {e}")
            return None

    def _create_meeting_via_google_oauth(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendees: List[str],
        description: str,
    ) -> Optional[Meeting]:
        try:
            event = self._google_calendar_request(
                "POST",
                "/calendars/primary/events",
                params={"sendUpdates": "all", "conferenceDataVersion": 1},
                json_body={
                    "summary": title,
                    "description": description,
                    "start": {"dateTime": self._as_rfc3339(start_time), "timeZone": Config.TIMEZONE},
                    "end": {"dateTime": self._as_rfc3339(end_time), "timeZone": Config.TIMEZONE},
                    "attendees": [{"email": attendee} for attendee in attendees],
                    "conferenceData": {
                        "createRequest": {
                            "requestId": f"meetagain-{uuid.uuid4().hex[:12]}",
                            "conferenceSolutionKey": {"type": "hangoutsMeet"},
                        }
                    },
                },
            )
            if event is None:
                return None
            meeting = self._parse_event(event)
            logger.info(f"Meeting created via Google OAuth: {title} ({meeting.id})")
            return meeting
        except Exception as e:
            logger.warning(f"Google OAuth create meeting failed, falling back to gws: {e}")
            return None

    def _add_attendees_via_google_oauth(self, meeting_id: str, attendees: List[str]) -> Optional[bool]:
        try:
            event = self._get_event_via_google_oauth(meeting_id)
            if event is None:
                return None
            current = event.get("attendees", [])
            existing = {item.get("email") for item in current if item.get("email")}
            merged = current + [{"email": attendee} for attendee in attendees if attendee not in existing]
            result = self._google_calendar_request(
                "PATCH",
                f"/calendars/primary/events/{quote(meeting_id, safe='')}",
                params={"sendUpdates": "all"},
                json_body={"attendees": merged},
            )
            if result is None:
                return None
            logger.info(f"Attendees added via Google OAuth to {meeting_id}: {attendees}")
            return True
        except Exception as e:
            logger.warning(f"Google OAuth add attendees failed, falling back to gws: {e}")
            return None

    def _update_description_via_google_oauth(self, meeting_id: str, description: str) -> Optional[bool]:
        try:
            result = self._google_calendar_request(
                "PATCH",
                f"/calendars/primary/events/{quote(meeting_id, safe='')}",
                params={"sendUpdates": "all"},
                json_body={"description": description},
            )
            if result is None:
                return None
            logger.info(f"Meeting description updated via Google OAuth: {meeting_id}")
            return True
        except Exception as e:
            logger.warning(f"Google OAuth update description failed, falling back to gws: {e}")
            return None

    def _get_event_via_google_oauth(self, meeting_id: str) -> Optional[dict]:
        try:
            return self._google_calendar_request(
                "GET",
                f"/calendars/primary/events/{quote(meeting_id, safe='')}",
            )
        except Exception as e:
            logger.warning(f"Google OAuth get event failed, falling back to gws: {e}")
            return None

    def _build_events_list_params(self, hours: int) -> dict:
        now = datetime.now(self._local_timezone())
        time_max = now + timedelta(hours=hours)
        return {
            "timeMin": self._as_rfc3339(now),
            "timeMax": self._as_rfc3339(time_max),
            "singleEvents": "true",
            "orderBy": "startTime",
        }

    def _google_calendar_request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> Optional[dict]:
        access_token = self.google_auth_svc.get_valid_access_token()
        if not access_token:
            return None

        response = requests.request(
            method,
            f"https://www.googleapis.com/calendar/v3{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            json=json_body,
            timeout=20,
        )
        response.raise_for_status()
        if not response.text:
            return {}
        return response.json()
