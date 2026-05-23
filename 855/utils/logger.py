"""结构化日志支持"""

import json
import logging
import sys
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """JSON 结构化日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exc"] = str(record.exc_info[1])
        return json.dumps(entry, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """彩色终端日志格式化器"""

    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        return f"{color}[{record.name}]{self.RESET} {record.getMessage()}"


def setup_logging(level: str = "INFO", fmt: str = "console") -> logging.Logger:
    """配置并返回 mimodoc 根 logger"""
    logger = logging.getLogger("mimodoc")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.DEBUG)

    if fmt == "structured":
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())

    logger.addHandler(handler)
    return logger
