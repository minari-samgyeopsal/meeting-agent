"""
캐싱 유틸리티

업체 정보, 인물 정보, 웹 검색 결과를 로컬 파일 기반으로 캐싱합니다.
7일 이상 경과 시 갱신이 필요합니다.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class Cache:
    """캐싱 관리자"""
    
    def __init__(self):
        self.cache_dir = Path(Config.CACHE_DIR) / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_file(self, cache_type: str, key: str) -> Path:
        """캐시 파일 경로 반환"""
        # 파일명: cache_type_key.json
        # 예: company_acme.json, person_john_doe.json
        safe_key = key.replace(" ", "_").replace("@", "_")
        filename = f"{cache_type}_{safe_key}.json"
        return self.cache_dir / filename
    
    def get(self, cache_type: str, key: str) -> Optional[Dict[str, Any]]:
        """캐시에서 데이터 조회"""
        cache_file = self._get_cache_file(cache_type, key)
        
        if not cache_file.exists():
            logger.debug(f"Cache miss: {cache_type}:{key}")
            return None
        
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 캐시 유효성 확인 (7일)
            cached_at = datetime.fromisoformat(data.get("cached_at", datetime.now().isoformat()))
            if datetime.now() - cached_at > timedelta(days=7):
                logger.debug(f"Cache expired: {cache_type}:{key}")
                cache_file.unlink()  # 파일 삭제
                return None
            
            logger.debug(f"Cache hit: {cache_type}:{key}")
            return data
        
        except Exception as e:
            logger.warning(f"Error reading cache {cache_type}:{key}: {e}")
            return None
    
    def set(self, cache_type: str, key: str, data: Dict[str, Any]) -> bool:
        """캐시에 데이터 저장"""
        cache_file = self._get_cache_file(cache_type, key)
        
        try:
            # 타임스탐프 추가
            data["cached_at"] = datetime.now().isoformat()
            
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"Cache saved: {cache_type}:{key}")
            return True
        
        except Exception as e:
            logger.error(f"Error saving cache {cache_type}:{key}: {e}")
            return False
    
    def delete(self, cache_type: str, key: str) -> bool:
        """캐시 삭제"""
        cache_file = self._get_cache_file(cache_type, key)
        
        try:
            if cache_file.exists():
                cache_file.unlink()
                logger.debug(f"Cache deleted: {cache_type}:{key}")
            return True
        
        except Exception as e:
            logger.error(f"Error deleting cache {cache_type}:{key}: {e}")
            return False
    
    def clear_all(self) -> bool:
        """모든 캐시 삭제"""
        try:
            import shutil
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info("All cache cleared")
            return True
        
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """캐시 통계"""
        stats = {
            "cache_dir": str(self.cache_dir),
            "total_files": 0,
            "total_size_mb": 0,
            "by_type": {},
        }
        
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                stats["total_files"] += 1
                stats["total_size_mb"] += cache_file.stat().st_size / (1024 * 1024)
                
                # 타입별 통계
                cache_type = cache_file.stem.split("_")[0]
                stats["by_type"][cache_type] = stats["by_type"].get(cache_type, 0) + 1
        
        except Exception as e:
            logger.warning(f"Error getting cache stats: {e}")
        
        return stats


# 글로벌 캐시 인스턴스
cache = Cache()
