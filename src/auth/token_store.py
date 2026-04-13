"""
파일 기반 OAuth 토큰 저장소
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from src.utils.config import Config


class TokenStore:
    """로컬 JSON 파일에 provider별 OAuth 토큰을 저장"""

    def __init__(self, path: Optional[str] = None):
        target = path or Config.OAUTH_TOKEN_STORE_PATH
        self.path = Path(target)

    def get_token(self, provider: str, owner_id: str = "default") -> Optional[Dict]:
        return self._load_all().get(self._key(provider, owner_id))

    def save_token(self, provider: str, owner_id: str, token: Dict) -> Dict:
        payload = self._load_all()
        record = dict(token)
        record["provider"] = provider
        record["owner_id"] = owner_id
        payload[self._key(provider, owner_id)] = record
        self._write_all(payload)
        return record

    def delete_token(self, provider: str, owner_id: str = "default") -> bool:
        payload = self._load_all()
        removed = payload.pop(self._key(provider, owner_id), None)
        self._write_all(payload)
        return removed is not None

    def list_tokens(self, provider: Optional[str] = None) -> List[Dict]:
        records = list(self._load_all().values())
        if provider:
            records = [item for item in records if item.get("provider") == provider]
        return records

    def _load_all(self) -> Dict[str, Dict]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_all(self, payload: Dict[str, Dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)

    @staticmethod
    def _key(provider: str, owner_id: str) -> str:
        return f"{provider}:{owner_id}"

