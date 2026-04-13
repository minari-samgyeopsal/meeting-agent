"""
Google Drive 서비스 (gws CLI 기반)

사용 가능한 메서드:
- load_company_contact: Contacts/Companies/업체명.md 로드 (FR-B03)
- load_person_contact: Contacts/People/이름.md 로드 (FR-B03)
- load_company_knowledge: company_knowledge.md 로드 (FR-B06)
- save_company_knowledge: company_knowledge.md 저장 (FR-B13)
- save_contact: Contacts 폴더에 저장 (FR-B15)
- search_contacts: Contacts 폴더 검색
"""

import json
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

import requests

from src.auth.google_auth_service import GoogleAuthService
from src.models.contact import Company, Person
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DriveService:
    """Google Drive 조작 (Contacts, 회의록 등)"""
    
    def __init__(self):
        self.cmd_prefix = [Config.gws_bin(), "drive"]
        self.google_auth_svc = GoogleAuthService()
        self.contacts_folder = Config.CONTACTS_FOLDER
        self.company_knowledge_file = Config.COMPANY_KNOWLEDGE_FILE
        self.transcripts_folder = Config.MEETING_TRANSCRIPTS_FOLDER
        self.meeting_notes_folder = Config.MEETING_NOTES_FOLDER
        self.generated_drafts_folder = Config.GENERATED_DRAFTS_FOLDER
        self.meeting_state_folder = Config.MEETING_STATE_FOLDER
        self.runtime_tmp_root = Path(Config.CACHE_DIR) / "gws_runtime"
        self.drive_link_cache_file = self.runtime_tmp_root / "drive_links.json"
    
    def load_company_contact(self, company_name: str) -> Optional[Company]:
        """
        업체 정보 로드 (FR-B03)
        
        경로: Drive/Contacts/Companies/업체명.md
        
        Args:
            company_name: 업체명
        
        Returns:
            Company 객체 또는 None
        """
        try:
            filepath = f"{self.contacts_folder}/Companies/{company_name}.md"

            content = self._read_text_file(filepath)
            if not content:
                logger.debug(f"Company contact not found: {company_name}")
                return None

            data = json.loads(content)
            company = Company(
                name=company_name,
                domain=data.get("domain"),
                main_email=data.get("main_email"),
                main_phone=data.get("main_phone"),
                description=data.get("description", ""),
                industry=data.get("industry"),
                size=data.get("size"),
                recent_news=data.get("recent_news", []),
                service_touchpoints=data.get("service_touchpoints", []),
                key_contact=data.get("key_contact"),
                meeting_history_count=data.get("meeting_history_count", 0),
            )
            
            logger.debug(f"Company contact loaded: {company_name}")
            return company
        
        except Exception as e:
            logger.error(f"Error loading company contact {company_name}: {e}")
            return None
    
    def load_person_contact(self, person_name: str) -> Optional[Person]:
        """
        인물 정보 로드 (FR-B03)
        
        경로: Drive/Contacts/People/이름.md
        
        Args:
            person_name: 인물명
        
        Returns:
            Person 객체 또는 None
        """
        try:
            filepath = f"{self.contacts_folder}/People/{person_name}.md"

            content = self._read_text_file(filepath)
            if not content:
                logger.debug(f"Person contact not found: {person_name}")
                return None

            data = json.loads(content)
            person = Person(
                name=person_name,
                title=data.get("title"),
                company=data.get("company"),
                email=data.get("email"),
                phone=data.get("phone"),
                linkedin_url=data.get("linkedin_url"),
                bio=data.get("bio", ""),
                sns_profiles=data.get("sns_profiles", []),
                notes=data.get("notes", ""),
                is_internal=data.get("is_internal", False),
            )
            
            logger.debug(f"Person contact loaded: {person_name}")
            return person
        
        except Exception as e:
            logger.error(f"Error loading person contact {person_name}: {e}")
            return None
    
    def load_company_knowledge(self) -> Optional[str]:
        """
        회사 정보 문서 로드 (FR-B06)
        
        경로: Drive/company_knowledge.md
        
        Returns:
            파일 내용 문자열 또는 None
        """
        try:
            content = self._read_text_file(self.company_knowledge_file)
            if not content:
                logger.warning("company_knowledge.md not found")
                return None

            logger.debug("company_knowledge.md loaded")
            return content
        
        except Exception as e:
            logger.error(f"Error loading company_knowledge.md: {e}")
            return None
    
    def save_company_knowledge(self, content: str) -> bool:
        """
        회사 정보 문서 저장 (FR-B13)
        
        Args:
            content: 저장할 콘텐츠
        
        Returns:
            성공 여부
        """
        try:
            return self._write_text_file(self.company_knowledge_file, content)
        
        except Exception as e:
            logger.error(f"Error saving company_knowledge.md: {e}")
            return False
    
    def save_contact(self, contact_type: str, name: str, data: Dict) -> bool:
        """
        연락처 저장 (FR-B15)
        
        경로: Drive/Contacts/Companies/업체명.md 또는 Contacts/People/이름.md
        
        Args:
            contact_type: "company" 또는 "person"
            name: 업체명 또는 인물명
            data: 저장할 데이터 딕셔너리
        
        Returns:
            성공 여부
        """
        try:
            folder = "Companies" if contact_type == "company" else "People"
            filepath = f"{self.contacts_folder}/{folder}/{name}.md"
            content = json.dumps(data, ensure_ascii=False, indent=2)

            return self._write_text_file(filepath, content)
        
        except Exception as e:
            logger.error(f"Error saving {contact_type} contact: {e}")
            return False

    def load_meeting_transcript(self, meeting_id: str) -> Optional[str]:
        """
        미팅 transcript 로드

        경로: Drive/MeetingTranscripts/{meeting_id}.txt
        """
        filepath = f"{self.transcripts_folder}/{meeting_id}.txt"
        return self._read_text_file(filepath)

    def save_meeting_transcript(self, meeting_id: str, content: str) -> bool:
        """
        미팅 transcript 저장

        경로: Drive/MeetingTranscripts/{meeting_id}.txt
        """
        filepath = f"{self.transcripts_folder}/{meeting_id}.txt"
        return self._write_text_file(filepath, content)

    def load_meeting_notes(self, meeting_id: str, version: str = "internal") -> Optional[str]:
        """
        미팅 회의록 로드

        경로: Drive/MeetingNotes/{meeting_id}_{version}.md
        """
        filepath = self._meeting_note_path(meeting_id, version)
        return self._read_text_file(filepath)

    def save_meeting_notes(self, meeting_id: str, client_notes: str, internal_notes: str) -> bool:
        """
        미팅 회의록 2종 저장
        """
        client_path = self._meeting_note_path(meeting_id, "client")
        internal_path = self._meeting_note_path(meeting_id, "internal")

        client_ok = self._write_text_file(client_path, client_notes)
        internal_ok = self._write_text_file(internal_path, internal_notes)
        return client_ok and internal_ok

    def save_generated_draft(self, meeting_id: str, draft_type: str, content: str) -> bool:
        """
        생성된 제안서/리서치 초안 저장
        """
        filepath = f"{self.generated_drafts_folder}/{meeting_id}_{draft_type}.md"
        return self._write_text_file(filepath, content)

    def load_generated_draft(self, meeting_id: str, draft_type: str) -> Optional[str]:
        """
        생성된 draft 로드
        """
        filepath = f"{self.generated_drafts_folder}/{meeting_id}_{draft_type}.md"
        return self._read_text_file(filepath)

    def load_text_file(self, filepath: str) -> Optional[str]:
        """
        임의 경로의 텍스트 파일 로드
        """
        return self._read_text_file(filepath)

    def get_drive_web_link(self, filepath: str) -> Optional[str]:
        """
        저장 경로 기준 Google Drive 웹 링크 조회
        """
        try:
            if Config.DRY_RUN:
                return None
            cached = self._load_drive_link_cache().get(filepath)
            if cached:
                return f"https://drive.google.com/file/d/{cached}/view"
            file_id = self._find_drive_file_id(filepath)
            if not file_id:
                return None
            self._store_drive_file_id(filepath, file_id)
            return f"https://drive.google.com/file/d/{file_id}/view"
        except Exception as e:
            logger.debug(f"Error resolving Drive link for {filepath}: {e}")
            return None

    def load_meeting_state(self, meeting_id: str) -> Dict:
        """
        미팅 상태 파일 로드
        """
        content = self._read_text_file(self._meeting_state_path(meeting_id))
        if not content:
            return {}

        try:
            return json.loads(content)
        except Exception as e:
            logger.warning(f"Error parsing meeting state {meeting_id}: {e}")
            return {}

    def save_meeting_state(self, meeting_id: str, data: Dict) -> bool:
        """
        미팅 상태 파일 저장
        """
        data = dict(data)
        artifacts = data.get("artifacts", []) or []
        company_contact_paths = [
            item.get("path")
            for item in artifacts
            if item.get("type") == "company_contact" and item.get("path")
        ]
        person_contact_paths = [
            item.get("path")
            for item in artifacts
            if item.get("type") == "person_contact" and item.get("path")
        ]
        if company_contact_paths or person_contact_paths:
            data["contact_document_count"] = len(company_contact_paths) + len(person_contact_paths)
            data["company_contact"] = company_contact_paths[0] if company_contact_paths else data.get("company_contact")
            data["person_contact"] = person_contact_paths[0] if person_contact_paths else data.get("person_contact")
            data["person_contacts"] = person_contact_paths
        if data.get("after_completed"):
            data["phase"] = "after"
        data["updated_at"] = datetime.now().isoformat()
        filepath = self._meeting_state_path(meeting_id)
        content = json.dumps(data, ensure_ascii=False, indent=2)
        return self._write_text_file(filepath, content)

    def update_meeting_state(self, meeting_id: str, patch: Dict) -> bool:
        """
        미팅 상태 일부 업데이트
        """
        current = self.load_meeting_state(meeting_id)
        merged_patch = {
            key: value
            for key, value in patch.items()
            if value is not None
        }

        if current.get("after_completed") and merged_patch.get("phase") == "during":
            merged_patch["phase"] = current.get("phase", "after")

        current.update(merged_patch)
        current["updated_at"] = datetime.now().isoformat()
        return self.save_meeting_state(meeting_id, current)

    def append_meeting_artifact(self, meeting_id: str, artifact_type: str, path: str) -> bool:
        """
        미팅 상태에 산출물 정보 추가
        """
        current = self.load_meeting_state(meeting_id)
        artifacts = current.get("artifacts", [])
        entry = {"type": artifact_type, "path": path}

        if entry not in artifacts:
            artifacts.append(entry)

        current["artifacts"] = artifacts
        current["updated_at"] = datetime.now().isoformat()
        return self.save_meeting_state(meeting_id, current)

    def list_meeting_states(self) -> List[Dict]:
        """
        저장된 미팅 상태 목록 조회
        """
        try:
            state_root = self._dry_run_path(self.meeting_state_folder)
            if state_root.exists():
                states = []
                for filepath in sorted(state_root.glob("*.json")):
                    try:
                        data = json.loads(filepath.read_text(encoding="utf-8"))
                    except Exception as e:
                        logger.warning(f"Error parsing local meeting state {filepath}: {e}")
                        continue

                    if "meeting_id" not in data:
                        data["meeting_id"] = filepath.stem
                    states.append(data)

                if states:
                    return sorted(
                        states,
                        key=lambda item: item.get("updated_at", ""),
                        reverse=True,
                    )

            if not Config.DRY_RUN:
                logger.warning("No local meeting state cache found in live mode")
            return []

        except Exception as e:
            logger.error(f"Error listing meeting states: {e}")
            return []

    def _meeting_note_path(self, meeting_id: str, version: str) -> str:
        return f"{self.meeting_notes_folder}/{meeting_id}_{version}.md"

    def _meeting_state_path(self, meeting_id: str) -> str:
        return f"{self.meeting_state_folder}/{meeting_id}.json"

    def _read_text_file(self, filepath: str) -> Optional[str]:
        try:
            local_path = self._dry_run_path(filepath)

            # Live 모드에서도 write 시 항상 local mirror를 남긴다.
            # read는 이 local mirror를 우선 사용해야 gws read flaky 이슈와
            # keyring/internal error에 덜 흔들리고, 파이프라인도 더 일관된다.
            if local_path.exists():
                return local_path.read_text(encoding="utf-8")

            if Config.DRY_RUN:
                logger.debug(f"Dry-run Drive file not found: {filepath}")
                return None

            oauth_content = self._read_text_file_via_google_oauth(filepath)
            if oauth_content is not None:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_text(oauth_content, encoding="utf-8")
                return oauth_content

            file_id = self._find_drive_file_id(filepath)
            if not file_id:
                return None

            output_path = self._workspace_tmp_file(filepath)

            try:
                cmd = self.cmd_prefix + [
                    "files",
                    "download",
                    "--params",
                    json.dumps({"fileId": file_id}),
                    "--output",
                    output_path,
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    env=Config.build_subprocess_env(),
                )

                if result.returncode != 0:
                    logger.warning(f"Drive read failed for {filepath}, falling back to local cache: {result.stderr}")
                    return None

                content = Path(output_path).read_text(encoding="utf-8")
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_text(content, encoding="utf-8")
                return content
            finally:
                try:
                    Path(output_path).unlink(missing_ok=True)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Error reading Drive file {filepath}: {e}")
            return None

    def _write_text_file(self, filepath: str, content: str) -> bool:
        try:
            if Config.DRY_RUN:
                local_path = self._dry_run_path(filepath)
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_text(content, encoding="utf-8")
                logger.info(f"[DRY RUN] Drive file saved locally: {local_path}")
                return True

            if self._write_text_file_via_google_oauth(filepath, content):
                local_path = self._dry_run_path(filepath)
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_text(content, encoding="utf-8")
                logger.info(f"Drive file saved via Google OAuth: {filepath}")
                return True

            file_id = self._find_drive_file_id(filepath)
            mime_type = "text/markdown" if filepath.endswith(".md") else "text/plain"

            upload_path = self._workspace_tmp_file(filepath)
            Path(upload_path).write_text(content, encoding="utf-8")

            try:
                if file_id:
                    cmd = self.cmd_prefix + [
                        "files",
                        "update",
                        "--params",
                        json.dumps({"fileId": file_id, "supportsAllDrives": True}),
                        "--upload",
                        upload_path,
                        "--upload-content-type",
                        mime_type,
                    ]
                else:
                    cmd = self.cmd_prefix + [
                        "files",
                        "create",
                        "--json",
                        json.dumps(
                            {
                                "name": Path(filepath).name,
                                "appProperties": {"meetagain_path": filepath},
                            }
                        ),
                        "--params",
                        json.dumps({"supportsAllDrives": True}),
                        "--upload",
                        upload_path,
                        "--upload-content-type",
                        mime_type,
                    ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    env=Config.build_subprocess_env(),
                )

                if result.returncode != 0:
                    logger.warning(f"gws drive write failed for {filepath}, falling back to local cache: {result.stderr}")
                    local_path = self._dry_run_path(filepath)
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_text(content, encoding="utf-8")
                    logger.info(f"[LOCAL FALLBACK] Drive file saved locally: {local_path}")
                    return True

                resolved_file_id = file_id or self._extract_file_id_from_output(result.stdout)
                if resolved_file_id:
                    self._store_drive_file_id(filepath, resolved_file_id)
                # Keep a local mirror even in live mode so reads can fall back safely.
                local_path = self._dry_run_path(filepath)
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_text(content, encoding="utf-8")
                logger.info(f"Drive file saved: {filepath}")
                return True
            finally:
                try:
                    Path(upload_path).unlink(missing_ok=True)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Error writing Drive file {filepath}: {e}")
            return False

    def _dry_run_path(self, filepath: str) -> Path:
        root = Path(Config.CACHE_DIR) / "dry_run_drive"
        sanitized_parts = [part for part in filepath.split("/") if part and part not in (".", "..")]
        return root.joinpath(*sanitized_parts)

    def _workspace_tmp_file(self, filepath: str) -> str:
        self.runtime_tmp_root.mkdir(parents=True, exist_ok=True)
        suffix = Path(filepath).suffix or ".txt"
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
            dir=self.runtime_tmp_root,
        ) as tmp:
            return tmp.name

    def _extract_file_id_from_output(self, stdout: str) -> Optional[str]:
        try:
            payload = json.loads(stdout or "{}")
            return payload.get("id")
        except Exception:
            return None

    def _load_drive_link_cache(self) -> Dict[str, str]:
        try:
            if not self.drive_link_cache_file.exists():
                return {}
            return json.loads(self.drive_link_cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _store_drive_file_id(self, filepath: str, file_id: str) -> None:
        try:
            self.runtime_tmp_root.mkdir(parents=True, exist_ok=True)
            cache = self._load_drive_link_cache()
            cache[filepath] = file_id
            self.drive_link_cache_file.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug(f"Error caching Drive file id for {filepath}: {e}")

    def _find_drive_file_id(self, filepath: str) -> Optional[str]:
        """appProperties에 저장한 가상 경로 기준으로 Drive 파일 조회"""
        try:
            file_id = self._find_drive_file_id_via_google_oauth(filepath)
            if file_id:
                return file_id

            query = (
                "appProperties has "
                "{ key='meetagain_path' and value='%s' } and trashed = false"
            ) % filepath.replace("'", "\\'")

            cmd = self.cmd_prefix + [
                "files",
                "list",
                "--params",
                json.dumps(
                    {
                        "q": query,
                        "pageSize": 1,
                        "fields": "files(id,name,appProperties)",
                        "supportsAllDrives": True,
                    }
                ),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=Config.build_subprocess_env(),
            )
            if result.returncode != 0:
                logger.debug(f"Drive lookup failed for {filepath}: {result.stderr}")
                return None

            payload = json.loads(result.stdout or "{}")
            files = payload.get("files", [])
            if not files:
                return None
            return files[0].get("id")
        except Exception as e:
            logger.debug(f"Error finding Drive file id for {filepath}: {e}")
            return None

    def _read_text_file_via_google_oauth(self, filepath: str) -> Optional[str]:
        try:
            file_id = self._find_drive_file_id_via_google_oauth(filepath)
            if not file_id:
                return None
            response = self._google_drive_request(
                "GET",
                f"/files/{file_id}",
                params={"alt": "media"},
                raw=True,
            )
            if response is None:
                return None
            return response.text
        except Exception as e:
            logger.warning(f"Google OAuth Drive read failed, falling back to gws: {e}")
            return None

    def _write_text_file_via_google_oauth(self, filepath: str, content: str) -> bool:
        try:
            file_id = self._find_drive_file_id_via_google_oauth(filepath)
            mime_type = "text/markdown" if filepath.endswith(".md") else "text/plain"
            if file_id:
                response = self._google_drive_upload(
                    method="PATCH",
                    file_id=file_id,
                    metadata=None,
                    content=content,
                    mime_type=mime_type,
                )
            else:
                response = self._google_drive_upload(
                    method="POST",
                    metadata={"name": Path(filepath).name, "appProperties": {"meetagain_path": filepath}},
                    content=content,
                    mime_type=mime_type,
                )
            if not response:
                return False
            resolved_file_id = response.get("id")
            if resolved_file_id:
                self._store_drive_file_id(filepath, resolved_file_id)
            return True
        except Exception as e:
            logger.warning(f"Google OAuth Drive write failed, falling back to gws: {e}")
            return False

    def _find_drive_file_id_via_google_oauth(self, filepath: str) -> Optional[str]:
        try:
            access_token = self.google_auth_svc.get_valid_access_token()
            if not access_token:
                return None
            query = (
                "appProperties has "
                "{ key='meetagain_path' and value='%s' } and trashed = false"
            ) % filepath.replace("'", "\\'")
            payload = self._google_drive_request(
                "GET",
                "/files",
                params={
                    "q": query,
                    "pageSize": 1,
                    "fields": "files(id,name,appProperties,webViewLink)",
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                },
            )
            files = (payload or {}).get("files", [])
            if not files:
                return None
            return files[0].get("id")
        except Exception as e:
            logger.warning(f"Google OAuth Drive lookup failed, falling back to gws: {e}")
            return None

    def _google_drive_request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        raw: bool = False,
    ):
        access_token = self.google_auth_svc.get_valid_access_token()
        if not access_token:
            return None
        response = requests.request(
            method,
            f"https://www.googleapis.com/drive/v3{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            json=json_body,
            timeout=20,
        )
        response.raise_for_status()
        if raw:
            return response
        if not response.text:
            return {}
        return response.json()

    def _google_drive_upload(
        self,
        method: str,
        content: str,
        mime_type: str,
        metadata: Optional[dict] = None,
        file_id: Optional[str] = None,
    ) -> Optional[dict]:
        access_token = self.google_auth_svc.get_valid_access_token()
        if not access_token:
            return None

        if method == "PATCH" and file_id:
            url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}"
            if metadata is None:
                response = requests.request(
                    method,
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": mime_type,
                    },
                    params={"uploadType": "media", "supportsAllDrives": "true"},
                    data=content.encode("utf-8"),
                    timeout=20,
                )
                response.raise_for_status()
                if not response.text:
                    return {}
                return response.json()
        else:
            url = "https://www.googleapis.com/upload/drive/v3/files"

        boundary = "meetagain-drive-boundary"
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        body = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadata_json}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime_type}\r\n\r\n"
            f"{content}\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")

        response = requests.request(
            method,
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            params={"uploadType": "multipart", "supportsAllDrives": "true"},
            data=body,
            timeout=20,
        )
        response.raise_for_status()
        if not response.text:
            return {}
        return response.json()
