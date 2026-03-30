"""
로깅 설정

모든 모듈에서 일관된 로징을 사용합니다.
"""

import logging
import sys
from pathlib import Path
from src.utils.config import Config

# 로그 출력 포맷
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """
    로거 인스턴스 반환
    
    Args:
        name: 모듈명 (보통 __name__)
    
    Returns:
        logging.Logger 인스턴스
    """
    logger = logging.getLogger(name)
    
    # 이미 설정되었으면 반환
    if logger.handlers:
        return logger
    
    # 로그 레벨 설정
    log_level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # 파일 핸들러 (optional)
    log_dir = Path(Config.CACHE_DIR) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    file_handler = logging.FileHandler(log_dir / "app.log")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(console_formatter)
    logger.addHandler(file_handler)
    
    return logger


# 메인 로거
logger = get_logger("meetagain")
