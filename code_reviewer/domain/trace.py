"""What a review did, as a tree, and where its time went.

Level 15 turned one agent into as many as five per file; Level 13 put a
retrieval pipeline in front of them and Level 14 a memory beside them. What
existed to see into that was structured logging and an OpenMetrics export, and
both are flat: nothing said which agent made a tool call, and
`code_review_duration_ms` could not tell four model calls apart from one
retrieval that scanned the wrong tree (capability C-12).

The model is here and the clock is not. What a span is, how a tree is built
from a flat list, what self time means and how a cycle is broken are all
arithmetic over values — including every case that would otherwise be
discovered in production.

Three properties are load-bearing.

**Nothing is lost.** An orphan attaches to the root, a cycle is broken, a
second root is adopted — each recorded as an anomaly rather than hidden.
Dropping a span because its parent is missing loses exactly the information
somebody is looking for, and a tracer that hangs on its own output is worse
than no tracer.

**Self time, not duration.** A parent's duration includes everything below it.
The number that answers "where did the time go" is its own share, floored at
zero because a clock that moved backwards is not evidence of negative work.

**Attributes are identifiers.** A path, a rule, an agent, a count, a budget —
never a diff, a file's contents or a model's prose. Enforced by a length cap at
construction rather than by advice, because a trace is written to an artefact
anyone with pipeline access can read and a diff may contain a secret
(decision D-5).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

#: Longest a text attribute may be. Generous for a path or a rule id, far too
#: short for a diff — which is the point.
MAX_ATTRIBUTE_CHARS = 200

_NO_ATTRIBUTES: Mapping[str, Any] = MappingProxyType({})


class SpanKind(Enum):
    """What a span is timing."""

    REVIEW = "review"
    FILE = "file"
    ANALYSIS = "analysis"
    RETRIEVAL = "retrieval"
    MEMORY = "memory"
    AGENT = "agent"
    MODEL = "model"
    TOOL = "tool"


class SpanStatus(Enum):
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True)
class Span:
    """One timed step of a review."""

    span_id: str
    kind: SpanKind
    name: str
    started_ms: int
    ended_ms: int | None = None
    parent_id: str = ""
    status: SpanStatus = SpanStatus.OK
    error_type: str = ""
    attributes: Mapping[str, Any] = field(default_factory=lambda: _NO_ATTRIBUTES)

    def __post_init__(self) -> None:
        if self.ended_ms is not None and self.ended_ms < self.started_ms:
            raise ValueError(f"Span '{self.span_id}' ends before it starts.")
        if self.status is SpanStatus.ERROR and not self.error_type:
            raise ValueError(f"Span '{self.span_id}' failed without saying what failed.")
        if self.status is SpanStatus.OK and self.error_type:
            raise ValueError(f"Span '{self.span_id}' is not an error but names one.")

        for key, value in self.attributes.items():
            if isinstance(value, str) and len(value) > MAX_ATTRIBUTE_CHARS:
                raise ValueError(
                    f"Attribute '{key}' on span '{self.span_id}' is {len(value)} characters. "
                    f"A trace carries identifiers, not content (limit {MAX_ATTRIBUTE_CHARS})."
                )

        if not isinstance(self.attributes, MappingProxyType):
            object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))

    def __hash__(self) -> int:
        # `attributes` is a mapping and mappings do not hash. Equality still
        # considers it; the hash uses what identifies a span in practice.
        return hash((self.span_id, self.kind, self.name, self.started_ms, self.ended_ms))

    @property
    def is_finished(self) -> bool:
        return self.ended_ms is not None

    @property
    def duration_ms(self) -> int | None:
        """How long it took, or ``None`` while it is still running.

        ``None`` rather than zero: "not finished" and "took no time" are
        different facts, and only one of them should be graphed.
        """
        return None if self.ended_ms is None else self.ended_ms - self.started_ms


@dataclass(frozen=True)
class TraceNode:
    """A span and what happened inside it."""

    span: Span
    children: tuple["TraceNode", ...] = ()

    def walk(self):
        """This node and every node below it, depth first."""
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class Trace:
    """Every span of one review, and the answers derived from them."""

    trace_id: str
    spans: tuple[Span, ...] = ()

    def __len__(self) -> int:
        return len(self.spans)

    # -- structure ----------------------------------------------------------

    def tree(self) -> TraceNode | None:
        """The spans as one tree, or ``None`` when there are none."""
        return self._build()[0]

    @property
    def anomalies(self) -> tuple[str, ...]:
        """What was wrong with the recorded spans, stated rather than hidden."""
        return self._build()[1]

    def _build(self) -> tuple[TraceNode | None, tuple[str, ...]]:
        if not self.spans:
            return None, ()

        by_id = {span.span_id: span for span in self.spans}
        anomalies: list[str] = []
        parents: dict[str, str] = {}

        for span in self.spans:
            parents[span.span_id] = _resolve_parent(span, by_id, anomalies)

        roots = sorted(
            (span for span in self.spans if not parents[span.span_id]),
            key=_order,
        )
        root = roots[0]
        for extra in roots[1:]:
            # A second root is a bug in the recorder, not a reason to lose half
            # the spans.
            anomalies.append(f"span '{extra.span_id}' is a second root; attached to '{root.span_id}'")
            parents[extra.span_id] = root.span_id

        children: dict[str, list[Span]] = {}
        for span in self.spans:
            parent = parents[span.span_id]
            if parent:
                children.setdefault(parent, []).append(span)

        return _node(root, children), tuple(anomalies)

    # -- timing -------------------------------------------------------------

    @property
    def duration_ms(self) -> int | None:
        root = self.tree()
        return root.span.duration_ms if root else None

    def self_time(self, span_id: str) -> int | None:
        """A span's own share of the clock: its duration, less its children's.

        Floored at zero. Children that overlap, or a clock that moved
        backwards, would otherwise produce a negative share of the time, which
        is not a fact about anything.
        """
        for node in self._nodes():
            if node.span.span_id == span_id:
                return _self_time(node)
        return None

    @property
    def by_kind(self) -> dict[SpanKind, int]:
        """Self time totalled per kind.

        What makes "40 % of this review was tool calls" a sentence the system
        can produce rather than a thing somebody estimates from a log.
        """
        totals: dict[SpanKind, int] = {}
        for node in self._nodes():
            own = _self_time(node)
            if own is not None:
                totals[node.span.kind] = totals.get(node.span.kind, 0) + own
        return totals

    @property
    def critical_path(self) -> tuple[Span, ...]:
        """Root to leaf, taking the longest child at each step.

        Ties resolve by start time and then by id, so the same trace always
        names the same path.
        """
        root = self.tree()
        if root is None:
            return ()

        path = [root.span]
        node = root
        while node.children:
            node = max(
                node.children,
                key=lambda child: (child.span.duration_ms or 0, -child.span.started_ms),
            )
            path.append(node.span)
        return tuple(path)

    # -- internals ----------------------------------------------------------

    def _nodes(self) -> list[TraceNode]:
        root = self.tree()
        return list(root.walk()) if root else []


def _resolve_parent(span: Span, by_id: Mapping[str, Span], anomalies: list[str]) -> str:
    """The parent this span may keep, after orphans and cycles are dealt with."""
    parent = span.parent_id
    if not parent:
        return ""

    if parent not in by_id:
        anomalies.append(f"span '{span.span_id}' is an orphan: parent '{parent}' was never recorded")
        return ""

    # Walk up. A chain that revisits a span is a cycle, and following it is how
    # a tracer hangs on its own output.
    seen = {span.span_id}
    current = parent
    while current:
        if current in seen:
            anomalies.append(f"span '{span.span_id}' is in a parent cycle; detached")
            return ""
        seen.add(current)
        current = by_id[current].parent_id if current in by_id else ""

    return parent


def _order(span: Span) -> tuple[int, str]:
    return (span.started_ms, span.span_id)


def _node(span: Span, children: Mapping[str, Sequence[Span]]) -> TraceNode:
    return TraceNode(
        span=span,
        children=tuple(
            _node(child, children) for child in sorted(children.get(span.span_id, ()), key=_order)
        ),
    )


def _self_time(node: TraceNode) -> int | None:
    if node.span.duration_ms is None:
        return None
    inside = sum(child.span.duration_ms or 0 for child in node.children)
    return max(0, node.span.duration_ms - inside)
