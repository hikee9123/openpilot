# file_logger.py
from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
import sys
from typing import Literal



def setup_logger(
    name: str = "app",
    log_dir: str | Path = "logs",
    level: Literal["DEBUG","INFO","WARNING","ERROR","CRITICAL"] = "INFO",
    rotation: Literal["size","time"] = "size",     # "size"=용량 기준, "time"=일자 기준
    max_bytes: int = 5 * 1024 * 1024,              # rotation="size"일 때: 5MB
    backup_count: int = 5,                         # 보관 파일 개수
    when: str = "midnight",                        # rotation="time"일 때: 매 자정 회전
    encoding: str = "utf-8",
    console: bool = True,                          # 콘솔 출력도 함께 할지
) -> logging.Logger:
    """
    사용 예:
        logger = setup_logger("myapp", rotation="time")
        logger.info("Hello logging!")
    """
    # 디렉터리 준비
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logfile = log_dir / f"{name}.log"

    # 로거 생성 (중복 핸들러 방지)
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level))
    logger.propagate = False
    if logger.handlers:
        return logger

    # 포맷터 (시간, 레벨, 로거명, 라인번호, 메시지)
    fmt = "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    # 파일 핸들러 (회전 방식 선택)
    if rotation == "time":
        fh = TimedRotatingFileHandler(
            filename=str(logfile),
            when=when,           # "S","M","H","D","midnight","W0"~"W6"
            interval=1,
            backupCount=backup_count,
            encoding=encoding,
            utc=False,           # 로컬 시간 기준 회전
        )
    else:
        fh = RotatingFileHandler(
            filename=str(logfile),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding=encoding,
        )
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # 콘솔 핸들러 (선택)
    if console:
        ch = logging.StreamHandler(stream=sys.stdout)
        ch.setLevel(getattr(logging, level))
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    return logger


_LOGGER = None
def get_logger( _name: str = "selfdrive.modeld.modeld" ):
  global _LOGGER
  if _LOGGER is None:
    _LOGGER = setup_logger(name=_name, log_dir="/data/log", rotation="time")
  return _LOGGER

# 데모 실행
if __name__ == "__main__":
    log = setup_logger(
        name="demo",
        log_dir="logs",
        level="DEBUG",
        rotation="size",     # "time"으로 바꾸면 자정마다 회전
        max_bytes=1_000_000,
        backup_count=7,
    )

    log.debug("디버그 메시지")
    log.info("정보 메시지")
    log.warning("경고 메시지")
    try:
        1 / 0
    except Exception:
        # 예외 전체 스택을 로그로 남기기
        log.exception("에러 발생!")

    log.info("완료!")


"""
from file_logger import setup_logger
logger = setup_logger("app")   # 최초 1회 구성
sub = logging.getLogger("app.submodule")
sub.info("서브 모듈 로그")
"""