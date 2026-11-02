"""Process plumbing: logging, the data folder and a single-instance lock."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from .config import Config


class AlreadyRunning(Exception):
    pass


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    for noisy in ("urllib3", "apprise", "mcp", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def db_path(cfg: Config) -> Path:
    return cfg.data_dir / "h2s-alerts.sqlite3"


class Lock:
    """Held while a watcher runs, so two of them never poll from the same data folder."""

    def __init__(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "watch.lock"
        self.file = None

    def __enter__(self):
        self.file = open(self.path, "a+")  # noqa: SIM115
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise AlreadyRunning(f"Another watcher already uses {self.path.parent}") from None
        self.file.seek(0)
        self.file.truncate()
        self.file.write(str(os.getpid()))
        self.file.flush()
        return self

    def __exit__(self, *exc):
        if self.file:
            self.file.close()
        return False
