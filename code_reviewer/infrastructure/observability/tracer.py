"""Recording a review as it happens.

The only stateful object in the tracing story. Everything it produces is
:mod:`code_reviewer.domain.trace` values, and everything interesting about
those — the tree, self time, the critical path — is decided there.

Identifiers are dotted counters rather than UUIDs. Forty spans in one process
need identity that is unique within the trace and comparable by eye: `1.4.2`
beats a hex string nobody can diff, and it makes the tree's shape visible in a
flat log line (decision D-6).

Nothing here can fail a review. A clock that goes backwards is clamped, a span
finished twice is logged and ignored, and an exception inside a span is
recorded and re-raised — tracing observes, it does not handle (contracts C-5,
C-7).
"""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from code_reviewer.application.tracing import NullTracer, Tracer
from code_reviewer.domain.trace import Span, SpanKind, SpanStatus, Trace

logger = logging.getLogger(__name__)


def _monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


class SpanRecorder(Tracer):
    """Records spans for one review.

    Args:
        trace_id: Names this run. Appears on every log record.
        clock: Milliseconds, monotonic. Injected so a test is not timing-bound.
    """

    def __init__(self, trace_id: str = "review", clock: Callable[[], int] | None = None):
        self.trace_id = trace_id
        self._clock = clock or _monotonic_ms
        self._spans: list[Span] = []
        self._open: dict[str, tuple[SpanKind, str, int, dict[str, Any]]] = {}
        self._stack: list[str] = []
        self._counters: dict[str, int] = {}

    # -- api ----------------------------------------------------------------

    @property
    def current_span_id(self) -> str:
        """The innermost open span, or the empty string outside all of them."""
        return self._stack[-1] if self._stack else ""

    @contextmanager
    def span(self, kind: SpanKind, name: str, **attributes: Any) -> Iterator[str]:
        """Times a block, and records what it was.

        An exception marks the span `ERROR`, records the exception's type, and
        propagates — the caller's error handling is the caller's.
        """
        span_id = self.start(kind, name, **attributes)
        try:
            yield span_id
        except Exception as error:
            self.finish(span_id, error_type=type(error).__name__)
            raise
        else:
            self.finish(span_id)

    def start(self, kind: SpanKind, name: str, **attributes: Any) -> str:
        """Opens a span beneath the current one and returns its identifier."""
        parent = self.current_span_id
        self._counters[parent] = self._counters.get(parent, 0) + 1
        ordinal = self._counters[parent]
        span_id = f"{parent}.{ordinal}" if parent else str(ordinal)

        self._open[span_id] = (kind, name, self._clock(), dict(attributes))
        self._stack.append(span_id)
        return span_id

    def finish(self, span_id: str, error_type: str = "") -> None:
        """Closes a span. Closing one twice is logged and ignored."""
        opened = self._open.pop(span_id, None)
        if opened is None:
            logger.warning("Span %s was finished twice, or was never started", span_id)
            return

        kind, name, started, attributes = opened
        # Clamped: a clock that moved backwards is not evidence of negative
        # work, and a `Span` refuses to be built from one.
        ended = max(started, self._clock())

        if span_id in self._stack:
            self._stack.remove(span_id)

        self._spans.append(
            Span(
                span_id=span_id,
                parent_id=span_id.rsplit(".", 1)[0] if "." in span_id else "",
                kind=kind,
                name=name,
                started_ms=started,
                ended_ms=ended,
                status=SpanStatus.ERROR if error_type else SpanStatus.OK,
                error_type=error_type,
                attributes=attributes,
            )
        )

    def annotate(self, span_id: str, **attributes: Any) -> None:
        """Adds attributes to an open span. Unknown ids are ignored."""
        opened = self._open.get(span_id)
        if opened is not None:
            opened[3].update(attributes)

    def trace(self) -> Trace:
        """Everything recorded so far, in the order it finished."""
        return Trace(trace_id=self.trace_id, spans=tuple(self._spans))


# -- the ambient tracer ------------------------------------------------------
#
# The tool layer holds its workspace and its retriever in module globals for
# one reason: a LangChain tool is a plain function with nowhere for a
# dependency to live. The tracer joins them rather than inventing a second
# pattern (decision D-3). Everything above the tools receives a tracer through
# its constructor, as everything else in this project does.

_tracer: Tracer = NullTracer()


def set_tracer(tracer: Tracer | None) -> None:
    """Sets the tracer the tool layer and the log filter read."""
    global _tracer
    _tracer = tracer or NullTracer()


def get_tracer() -> Tracer:
    return _tracer


def current_trace_context() -> tuple[str, str]:
    """``(trace_id, span_id)``, or two empty strings outside any span.

    Empty rather than a placeholder: a log record outside a review should carry
    no trace fields at all, not fields that say "none".
    """
    span_id = _tracer.current_span_id
    return (_tracer.trace_id, span_id) if span_id else ("", "")
