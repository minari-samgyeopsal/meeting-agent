"""
공통 헬퍼 함수

이메일 조회, 도메인 확인 등 여러 모듈에서 사용되는 함수들
"""

from typing import Optional, List
from src.utils.config import Config
from src.utils.logger import get_logger

logger = get_logger(__name__)


def extract_domain(email: str) -> Optional[str]:
    """이메일에서 도메인 추출"""
    try:
        return email.split("@")[1]
    except IndexError:
        logger.warning(f"Invalid email format: {email}")
        return None


def is_internal_email(email: str) -> bool:
    """내부 이메일 확인"""
    domain = extract_domain(email)
    return domain in Config.INTERNAL_DOMAINS if domain else False


def is_external_email(email: str) -> bool:
    """외부 이메일 확인"""
    return not is_internal_email(email)


def classify_emails(emails: List[str]) -> tuple:
    """이메일 목록을 내부/외부로 분류
    
    Returns:
        (internal_emails, external_emails)
    """
    internal = [e for e in emails if is_internal_email(e)]
    external = [e for e in emails if is_external_email(e)]
    return internal, external


def clean_email_list(emails: List[str]) -> List[str]:
    """이메일 목록 정제 (중복 제거, 유효성 확인)"""
    cleaned = []
    seen = set()
    
    for email in emails:
        email = email.strip().lower()
        if email and "@" in email and email not in seen:
            cleaned.append(email)
            seen.add(email)
    
    return cleaned


def extract_meeting_domain(attendees: List[str]) -> Optional[str]:
    """미팅 참석자 이메일에서 외부 업체 도메인 추출"""
    external = [e for e in attendees if is_external_email(e)]
    
    if not external:
        return None
    
    # 가장 많은 이메일의 도메인을 대표 도메인으로
    domains = [extract_domain(e) for e in external]
    if domains:
        from collections import Counter
        counter = Counter(domains)
        return counter.most_common(1)[0][0]
    
    return None


def format_email_list(emails: List[str], max_count: int = 3) -> str:
    """이메일 목록을 가독성 있게 포맷팅
    
    Args:
        emails: 이메일 목록
        max_count: 표시할 최대 개수 (초과 시 "외 N명" 표시)
    
    Returns:
        포맷된 문자열
    """
    if not emails:
        return "(없음)"
    
    if len(emails) <= max_count:
        return ", ".join(emails)
    
    displayed = emails[:max_count]
    remaining = len(emails) - max_count
    return f"{', '.join(displayed)} 외 {remaining}명"


def safe_get(data: dict, key: str, default=None):
    """딕셔너리에서 안전하게 값 추출"""
    try:
        return data.get(key, default)
    except (AttributeError, TypeError):
        return default
