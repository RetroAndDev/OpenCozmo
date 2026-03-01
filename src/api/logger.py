import logging
import sys
from pathlib import Path

_FORMATS = {
    "default": "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    "simple":  "[%(levelname)s] %(message)s",
}

_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Loggers to exclude from output (only show OpenCozmo logs)
_EXCLUDED_LOGGERS = {
    "pycozmo",
    "websockets.client",
    "websockets.server",
    "websockets.protocol",
    "asyncio",
    "pillow",
}


class _ExcludeFilter(logging.Filter):
    """Filter to exclude logs from specific modules."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Include only logs from modules that don't match excluded patterns
        logger_name = record.name.lower()
        for excluded in _EXCLUDED_LOGGERS:
            if logger_name.startswith(excluded):
                return False
        return True


def setup(level: str = "INFO", simple: bool = False, output_dir: str | None = None) -> None:
    """
    Configure root logger for the whole API process.
    Call this once at startup, before any other import logs.

    Args:
        level:      Log level string ("DEBUG", "INFO", "WARNING", "ERROR").
        simple:     Use a shorter format (useful when running behind systemd).
        output_dir: Directory path for log files (latest.log, last.log).
                    If None, logs go to stdout only.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    handlers = []

    # Create filter to exclude specific loggers
    exclude_filter = _ExcludeFilter()

    # Console handler (always enabled)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(
        logging.Formatter(
            _FORMATS["simple"] if simple else _FORMATS["default"],
            datefmt=_DATE_FORMAT,
        )
    )
    console_handler.addFilter(exclude_filter)
    handlers.append(console_handler)

    # File handler with rotation (latest.log → last.log)
    if output_dir:
        output_path = Path(output_dir).expanduser()
        output_path.mkdir(parents=True, exist_ok=True)

        latest_log = output_path / "latest.log"
        last_log = output_path / "last.log"

        # Before opening latest.log, rotate old one
        if latest_log.exists():
            last_log.write_bytes(latest_log.read_bytes())

        file_handler = logging.FileHandler(latest_log, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(
            logging.Formatter(
                _FORMATS["default"],
                datefmt=_DATE_FORMAT,
            )
        )
        file_handler.addFilter(exclude_filter)
        handlers.append(file_handler)

    root = logging.getLogger()
    root.setLevel(numeric_level)
    # Avoid duplicate handlers if setup() is accidentally called twice
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)

    # Disable loggers from external libraries
    logging.getLogger("pycozmo").disabled = True
    logging.getLogger("websockets").setLevel(logging.CRITICAL)
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)
