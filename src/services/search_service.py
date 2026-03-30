"""
웹 검색 서비스 (DuckDuckGo 기반)

사용 가능한 메서드:
- search_company_news: 업체 뉴스 검색 (FR-B04)
- search_person_info: 인물 정보 검색 (FR-B05)
"""

from duckduckgo_search import DDGS
from typing import List, Dict
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SearchService:
    """웹 검색"""
    
    def __init__(self):
        self.ddgs = DDGS()
        self.results_limit = Config.SEARCH_RESULTS_COUNT
    
    def search_company_news(self, company_name: str, limit: int = 5) -> List[Dict]:
        """
        업체 뉴스 검색 (FR-B04)
        
        쿼리: "[업체명] 최근 뉴스 OR 투자 OR 신사업"
        
        Args:
            company_name: 업체명
            limit: 검색 결과 개수 (기본 5)
        
        Returns:
            검색 결과 리스트 [{"title": "", "url": "", "summary": ""}, ...]
        """
        try:
            query = f"{company_name} (블록체인 OR Web3 OR DID OR 스테이블코인 OR 인증 OR 온체인) 최근 뉴스"
            
            logger.info(f"Searching company news: {query}")
            
            results = []
            search_results = self.ddgs.text(query, max_results=limit)
            
            for result in search_results:
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "summary": result.get("body", ""),
                })
            
            logger.info(f"Found {len(results)} news articles for {company_name}")
            return results
        
        except Exception as e:
            logger.error(f"Error searching company news: {e}")
            return []
    
    def search_person_info(self, person_name: str, company_name: str = "", limit: int = 5) -> List[Dict]:
        """
        인물 정보 검색 (FR-B05)
        
        쿼리: "[이름] [회사명] site:linkedin.com OR 인터뷰 OR 발표"
        
        Args:
            person_name: 인물명
            company_name: 회사명 (옵션)
            limit: 검색 결과 개수 (기본 5)
        
        Returns:
            검색 결과 리스트 [{"title": "", "url": "", "summary": ""}, ...]
        """
        try:
            if company_name:
                query = f"{person_name} {company_name} site:linkedin.com OR 인터뷰 OR 발표"
            else:
                query = f"{person_name} site:linkedin.com OR 인터뷰 OR 발표"
            
            logger.info(f"Searching person info: {query}")
            
            results = []
            search_results = self.ddgs.text(query, max_results=limit)
            
            for result in search_results:
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "summary": result.get("body", ""),
                })
            
            logger.info(f"Found {len(results)} results for {person_name}")
            return results
        
        except Exception as e:
            logger.error(f"Error searching person info: {e}")
            return []
    
    def search_general(self, query: str, limit: int = None) -> List[Dict]:
        """
        일반 웹 검색
        
        Args:
            query: 검색 쿼리
            limit: 결과 개수 (기본 설정값)
        
        Returns:
            검색 결과 리스트
        """
        try:
            if limit is None:
                limit = self.results_limit
            
            logger.debug(f"General search: {query}")
            
            results = []
            search_results = self.ddgs.text(query, max_results=limit)
            
            for result in search_results:
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "summary": result.get("body", ""),
                })
            
            return results
        
        except Exception as e:
            logger.error(f"Error in general search: {e}")
            return []
