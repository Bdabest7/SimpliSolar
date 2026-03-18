"""Logging configuration for SimpliSolar.

Call ``configure_logging()`` once at startup.  All backend modules should use::

    import logging
    log = logging.getLogger(__name__)

Log level can be overridden with the ``LOG_LEVEL`` environment variable
(default: INFO).
"""

from __future__ import annotations

import logging
import os
import sys


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%H:%M:%S"

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        stream=sys.stdout,
        force=True,
    )

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("skyfield").setLevel(logging.WARNING)
