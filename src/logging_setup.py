"""Logging and run instrumentation.

Both challenge sections require the time taken to be logged. Timings go to two
places deliberately: the log, so an operator watching the run sees progress, and
a JSON run manifest, so the numbers are machine-readable afterwards. A timing
that exists only in a log line cannot be asserted on in a test or compared
between runs.
"""

from __future__ import annotations

import json
import logging
import platform
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from src import config

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging. Idempotent."""
    root = logging.getLogger()
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)

    # botocore logs every request at INFO, which drowns the run.
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


class RunManifest:
    """Collects timings, metrics and verdicts for one pipeline run.

    Written to ``data/quality/run_manifest.json`` so that results are queryable
    and diffable rather than buried in log output.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "timings_seconds": {},
            "metrics": {},
            "verdicts": {},
        }

    def record_timing(self, name: str, seconds: float) -> None:
        self._data["timings_seconds"][name] = round(seconds, 4)

    def record_metric(self, name: str, value: Any) -> None:
        self._data["metrics"][name] = value

    def record_verdict(self, name: str, passed: bool, detail: str = "") -> None:
        self._data["verdicts"][name] = {"passed": passed, "detail": detail}

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def write(self, path: Path | None = None) -> Path:
        path = path or config.quality_path("run_manifest")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._data["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        with path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2, default=str)
        return path


# Module-level manifest: one run, one manifest.
MANIFEST = RunManifest()


@contextmanager
def timed(name: str, logger: logging.Logger | None = None) -> Iterator[None]:
    """Time a block, logging the result and recording it in the manifest.

    The timing is recorded even when the block raises, so a failed run still
    reports how long it got before failing -- which is usually the interesting
    number when diagnosing a timeout.
    """
    log = logger or logging.getLogger(__name__)
    log.info("START  %s", name)
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        MANIFEST.record_timing(name, elapsed)
        log.info("FINISH %s -- %.3fs", name, elapsed)


def human_bytes(n: float) -> str:
    """Format a byte count for log output."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"
