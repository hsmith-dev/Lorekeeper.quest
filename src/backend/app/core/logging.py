import logging
import json
import sys
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Last ~2000 formatted log lines from THIS worker process, for the admin
# portal's quick log view and the support bundle. Per-process by nature (each
# gunicorn worker keeps its own), so it's the fallback view — the shared log
# file (LOG_FILE, written by every worker) is the authoritative one; this
# exists so log viewing still works when no file is configured (local dev).
RECENT_LOGS: deque[str] = deque(maxlen=2000)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if hasattr(record, "extra"):
            payload.update(record.extra)
        return json.dumps(payload)


class _RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            RECENT_LOGS.append(self.format(record))
        except Exception:
            pass


def configure_logging(level: str = "INFO", log_file: str | None = None) -> None:
    formatter = JSONFormatter()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    ring = _RingBufferHandler()
    ring.setFormatter(formatter)

    handlers: list[logging.Handler] = [handler, ring]

    if log_file:
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            # delay=True: don't open the file until the first record — matters
            # under gunicorn where configure_logging runs in every worker.
            # Rotation from multiple processes isn't perfectly clean, but for
            # a self-host support log a rare ragged rotation beats unbounded
            # growth; docker logs (stdout) remains the pristine copy.
            file_handler = RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=2, encoding="utf-8", delay=True
            )
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)
        except OSError as exc:
            # An unwritable log path must never take the app down — fall back
            # to stdout + ring buffer and say so once.
            handler.handle(
                logging.LogRecord(
                    "app.core.logging", logging.WARNING, __file__, 0,
                    f"LOG_FILE {log_file!r} is not writable ({exc}); file logging disabled", None, None,
                )
            )

    logging.root.handlers = handlers
    logging.root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Quiet noisy third-party loggers
    for noisy in ("uvicorn.access", "watchfiles.main", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
