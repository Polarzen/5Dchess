"""
5D Chess - 日志模块
"""
import logging
import sys
from pathlib import Path
from src.config import LOG_DIR, LOG_LEVEL


def setup_logger(name: str = "chess_5d") -> logging.Logger:
    """创建并配置日志器"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件
    file_handler = logging.FileHandler(
        LOG_DIR / "chess_5d.log", encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# 全局日志器
logger = setup_logger()