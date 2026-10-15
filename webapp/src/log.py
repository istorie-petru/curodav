"""The app's one logging helper.

Every module gets its logger from `get_logger`. Lines go to the console (the
service journal under systemd) and to an in-memory ring that the live log view
in Settings reads, so both show the same stream at the same four levels:
all (debug), important (info), warnings and errors.
"""

from __future__ import annotations

import itertools
import logging
import re
import sys
import threading
from collections import deque

ROOT_NAME = "curodav"
LEVELS = {"all": logging.DEBUG, "important": logging.INFO, "warnings": logging.WARNING, "errors": logging.ERROR}
RING_SIZE = 2000

_SECRET = re.compile(r"(?i)\b(password|passwd|token|secret|recovery|session|cookie|authorization)(\s*[=:]\s*)\S+")
_ring: deque[dict] = deque(maxlen=RING_SIZE)
_ids = itertools.count(1)
_lock = threading.Lock()
_ready = False


def scrub(text: str) -> str:
    """Hide the value after any secret-looking name, so a careless log line cannot leak one."""
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[hidden]", text)


class _RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + logging.Formatter().formatException(record.exc_info)
            entry = {
                "time": record.created,
                "level": record.levelname.lower(),
                "component": record.name.removeprefix(ROOT_NAME + "."),
                "message": scrub(message),
            }
            with _lock:
                entry["id"] = next(_ids)
                _ring.append(entry)
        except Exception:  # a logging failure must never break a request
            self.handleError(record)


def _console_handler() -> logging.Handler:
    try:
        from systemd.journal import JournalHandler  # type: ignore[import-not-found]

        return JournalHandler(SYSLOG_IDENTIFIER=ROOT_NAME)
    except ImportError:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.setLevel(logging.INFO)
        return handler


def setup() -> None:
    """Attach the console and ring handlers once."""
    global _ready
    if _ready:
        return
    root = logging.getLogger(ROOT_NAME)
    root.setLevel(logging.DEBUG)
    root.propagate = False
    root.addHandler(_console_handler())
    root.addHandler(_RingHandler())
    _ready = True


def get_logger(name: str) -> logging.Logger:
    """The logger for a module: `log = get_logger(__name__)`."""
    setup()
    return logging.getLogger(f"{ROOT_NAME}.{name.removeprefix('src.')}")


def entries(level: str = "important", after: int = 0, limit: int = 500) -> list[dict]:
    """Ring entries at or above the named level, newer than `after`, oldest first."""
    floor = LEVELS.get(level, logging.INFO)
    with _lock:
        snapshot = list(_ring)
    return [e for e in snapshot if e["id"] > after and logging.getLevelName(e["level"].upper()) >= floor][-limit:]
