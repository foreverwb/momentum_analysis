"""Timing utilities for structured logging."""

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Dict, Iterator


@contextmanager
def timed(log, event: str, **fields: object) -> Iterator[Dict[str, object]]:
    """Measure elapsed time and log a structured event.

    Yields a dict that can be mutated to add fields or override status before exit.
    """
    start = perf_counter()
    details: Dict[str, object] = dict(fields)
    try:
        yield details
    except Exception:
        elapsed_ms = (perf_counter() - start) * 1000
        log.exception(event, status="fail", elapsed_ms=elapsed_ms, **details)
        raise
    else:
        elapsed_ms = (perf_counter() - start) * 1000
        status = details.pop("status", "ok")
        log.info(event, status=status, elapsed_ms=elapsed_ms, **details)
