from __future__ import annotations

import logging
import os
import sys
from typing import Optional

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_CONFIGURED = False


def _resolve_level(level: Optional[str] = None) -> int:
    raw = (level or os.getenv("LOG_LEVEL", "INFO")).strip().upper()
    return getattr(logging, raw, logging.INFO)


def configure_logging(level: Optional[str] = None) -> None:
    global _CONFIGURED

    log_level = _resolve_level(level)
    root_logger = logging.getLogger()

    if _CONFIGURED:
        root_logger.setLevel(log_level)
        for handler in root_logger.handlers:
            handler.setLevel(log_level)
        return

    root_logger.setLevel(log_level)

    if not root_logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        root_logger.addHandler(console_handler)
    else:
        for handler in root_logger.handlers:
            handler.setLevel(log_level)
            if handler.formatter is None:
                handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))

    _CONFIGURED = True


def setup_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    configure_logging(level=level)

    logger = logging.getLogger(name)
    logger.setLevel(_resolve_level(level))
    logger.propagate = True
    return logger


__all__ = ["configure_logging", "setup_logger"]