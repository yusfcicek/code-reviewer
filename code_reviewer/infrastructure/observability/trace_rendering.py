"""A trace, for a person and for a machine.

The person gets an indented tree in the merge-request comment and the CI log:
what ran, how long it took, and how much of that was its own rather than its
children's. The machine gets JSON.

Neither is OpenTelemetry, which is the obvious answer this level does not take
(decision D-2). `TraceExporter` is the port; an OTLP adapter is a sibling
module and nothing in the review path changes to gain one.

The rendering is bounded by depth and by node count, and says what it left
out. A trace of four hundred spans pasted into a merge-request comment is a
comment nobody reads, and a truncated one that does not admit it is worse.
"""

import json
import logging
from pathlib import Path
from typing import Any

from code_reviewer.application.tracing import TraceExporter
from code_reviewer.domain.trace import Span, SpanKind, Trace, TraceNode

logger = logging.getLogger(__name__)

#: How deep the rendered tree goes before it stops descending.
DEFAULT_MAX_DEPTH = 4

#: How many nodes it prints before it stops.
DEFAULT_MAX_NODES = 60


def render_trace_tree(
    trace: Trace, max_depth: int = DEFAULT_MAX_DEPTH, max_nodes: int = DEFAULT_MAX_NODES
) -> str:
    """The trace as an indented tree, bounded and deterministic."""
    root = trace.tree()
    if root is None:
        return "_No trace was recorded._"

    lines: list[str] = []
    omitted = _render(root, trace, 0, max_depth, max_nodes, lines)

    if omitted:
        lines.append(f"… {omitted} further span(s) not shown (depth {max_depth}, {max_nodes} nodes).")

    summary = ", ".join(
        f"{kind.value} {total} ms" for kind, total in sorted(trace.by_kind.items(), key=_kind_order)
    )
    lines.append("")
    lines.append(f"Self time by kind: {summary or 'nothing recorded'}")

    if trace.anomalies:
        # An orphan span is a bug worth seeing, not a detail worth hiding.
        lines.append("")
        lines.append("Anomalies:")
        lines.extend(f"  - {note}" for note in trace.anomalies)

    return "\n".join(lines)


def trace_to_json(trace: Trace) -> dict[str, Any]:
    """The trace as plain data, ready for ``json.dumps``."""
    return {
        "trace_id": trace.trace_id,
        "duration_ms": trace.duration_ms,
        "spans": [_span_to_json(span, trace) for span in trace.spans],
        "by_kind": {kind.value: total for kind, total in trace.by_kind.items()},
        "critical_path": [span.span_id for span in trace.critical_path],
        "anomalies": list(trace.anomalies),
    }


class JsonTraceExporter(TraceExporter):
    """Writes the trace to a file, and never fails a review for it.

    Args:
        path: Where the JSON goes.
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)

    def export(self, trace: Trace) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(trace_to_json(trace), indent=2) + "\n", encoding="utf-8")
        except Exception as error:
            # An observability feature that can break the thing it observes is
            # a liability (contract C-7).
            logger.warning("Could not write the trace to %s: %s", self._path, error)


# -- internals --------------------------------------------------------------


def _render(
    node: TraceNode, trace: Trace, depth: int, max_depth: int, max_nodes: int, lines: list[str]
) -> int:
    """Appends this node and its children; returns how many were left out."""
    if len(lines) >= max_nodes:
        return _count(node)
    if depth > max_depth:
        return _count(node)

    lines.append(_line(node, trace, depth))

    omitted = 0
    for child in node.children:
        omitted += _render(child, trace, depth + 1, max_depth, max_nodes, lines)
    return omitted


def _line(node: TraceNode, trace: Trace, depth: int) -> str:
    span = node.span
    duration = "…" if span.duration_ms is None else f"{span.duration_ms} ms"
    own = trace.self_time(span.span_id)
    own_text = "" if own is None or not node.children else f" (self {own} ms)"
    status = "" if span.status.value == "ok" else f" ✗ {span.error_type}"
    attributes = _attributes(span)
    return (
        f"{'  ' * depth}{span.span_id} {span.kind.value}:{span.name} {duration}{own_text}{status}{attributes}"
    )


def _attributes(span: Span) -> str:
    if not span.attributes:
        return ""
    pairs = " ".join(f"{key}={value}" for key, value in sorted(span.attributes.items()) if value != "")
    return f"  [{pairs}]" if pairs else ""


def _count(node: TraceNode) -> int:
    return sum(1 for _ in node.walk())


def _kind_order(item: tuple[SpanKind, int]) -> tuple[int, str]:
    return (-item[1], item[0].value)


def _span_to_json(span: Span, trace: Trace) -> dict[str, Any]:
    return {
        "span_id": span.span_id,
        "parent_id": span.parent_id,
        "kind": span.kind.value,
        "name": span.name,
        "started_ms": span.started_ms,
        "ended_ms": span.ended_ms,
        "duration_ms": span.duration_ms,
        "self_ms": trace.self_time(span.span_id),
        "status": span.status.value,
        "error_type": span.error_type,
        "attributes": dict(span.attributes),
    }
