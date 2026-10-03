"""统一日志：控制台彩色输出 + 落盘到 reports/run.log。

测试报告里能看到完整请求/响应链路，是排查接口问题最有效的手段。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False

LEVEL_COLOR = {
    "DEBUG": "\033[37m",
    "INFO": "\033[36m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[41m",
}
RESET = "\033[0m"


class _ColorFormatter(logging.Formatter):
    """Windows 终端也已支持 ANSI，若不支持会自动降级为纯文本。"""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if not sys.stdout.isatty():
            return text
        color = LEVEL_COLOR.get(record.levelname, "")
        return f"{color}{text}{RESET}" if color else text


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> logging.Logger:
    """初始化根日志，重复调用不会重复添加 handler。"""
    global _CONFIGURED
    logger = logging.getLogger("docqa-test")
    if _CONFIGURED:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_ColorFormatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(console)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s",
        ))
        logger.addHandler(file_handler)

    _CONFIGURED = True
    return logger


def get_logger(name: str = "docqa-test") -> logging.Logger:
    """获取子日志器，继承根配置。"""
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(name if name.startswith("docqa-test") else f"docqa-test.{name}")
