"""The port the workflow records itself through.

Declared here rather than in `ports.py` because it comes with a null object,
and a null object is not a port — it is the default that makes instrumentation
free for a caller who does not want it.

The architecture test found this module. `ReviewService` imported the recorder
from `infrastructure` directly, which is the one direction the dependency rule
forbids, and the check that parses every module's imports said so before a
human did. The recorder stayed where it was; the interface moved here.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from code_reviewer.domain.trace import SpanKind, Trace


class Tracer(ABC):
    """Records what a review did, as it does it.

    ``trace_id`` names the run and appears on every log record, which is the
    join between a log line and a trace.

    Nothing here may raise for an ordinary failure, and nothing may swallow
    the caller's exceptions: an observability feature that can break the thing
    it observes is a liability (Level 16, contract C-7).
    """

    #: Names this run. The empty string when nothing is being recorded.
    trace_id: str = ""

    @abstractmethod
    def span(self, kind: SpanKind, name: str, **attributes: Any) -> Any:
        """Context manager timing a block, yielding the new span's identifier.

        An exception inside marks the span as failed, records the exception's
        type, and propagates — tracing observes, it does not handle.
        """

    @abstractmethod
    def bind(self, parent_span_id: str) -> Any:
        """Context manager attaching this thread's spans to ``parent_span_id``.

        Used by a worker: the span that submitted its work is passed in at
        submission, because the worker's own stack is empty and knows nothing
        about who queued it (Level 17, decision D-4). Binding to the empty
        string is a no-op, so a caller need not branch on whether tracing is
        on.
        """

    @abstractmethod
    def start(self, kind: SpanKind, name: str, **attributes: Any) -> str:
        """Opens a span beneath the current one."""

    @abstractmethod
    def finish(self, span_id: str, error_type: str = "") -> None:
        """Closes a span. Closing one twice is logged and ignored."""

    @abstractmethod
    def annotate(self, span_id: str, **attributes: Any) -> None:
        """Adds attributes to an *open* span. Unknown identifiers are ignored."""

    @abstractmethod
    def trace(self) -> Trace:
        """Everything recorded so far."""

    @property
    @abstractmethod
    def current_span_id(self) -> str:
        """The innermost open span, or the empty string outside all of them."""


class TraceExporter(ABC):
    """Somewhere a finished trace can be written.

    A port because OpenTelemetry is the obvious answer this level does not
    take: the SDK plus an exporter is a large dependency tree in a process
    whose whole job is to be trustworthy. An OTLP adapter is a sibling of the
    JSON one, and nothing in the review path changes to gain it
    (Level 16, decision D-2).
    """

    @abstractmethod
    def export(self, trace: Trace) -> None:
        """Writes the trace. Never raises: a failed export is a log line."""


class NullTracer(Tracer):
    """A tracer that records nothing.

    The default everywhere, so an uninstrumented caller pays a function frame
    per span and nothing else — which is what lets the instrumentation be
    unconditional rather than wrapped in `if tracer is not None`.
    """

    trace_id = ""

    @contextmanager
    def span(self, kind: SpanKind, name: str, **attributes: Any) -> Iterator[str]:
        yield ""

    @contextmanager
    def bind(self, parent_span_id: str) -> Iterator[None]:
        yield

    def start(self, kind: SpanKind, name: str, **attributes: Any) -> str:
        return ""

    def finish(self, span_id: str, error_type: str = "") -> None:
        return None

    def annotate(self, span_id: str, **attributes: Any) -> None:
        return None

    def trace(self) -> Trace:
        return Trace(trace_id="", spans=())

    @property
    def current_span_id(self) -> str:
        return ""
