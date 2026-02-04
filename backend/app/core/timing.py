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
        event_override = details.pop("event_override", None)
        summary = details.pop("summary", None)
        event_text = event_override if isinstance(event_override, str) and event_override else event
        if isinstance(summary, str) and summary:
            event_text = f"{event_text}\n{summary}"
        log.exception(event_text, status="fail", elapsed_ms=elapsed_ms, **details)
        raise
    else:
        elapsed_ms = (perf_counter() - start) * 1000
        status = details.pop("status", "ok")
        event_override = details.pop("event_override", None)
        summary = details.pop("summary", None)
        event_text = event_override if isinstance(event_override, str) and event_override else event
        if isinstance(summary, str) and summary:
            event_text = f"{event_text}\n{summary}"
        log.info(event_text, status=status, elapsed_ms=elapsed_ms, **details)
