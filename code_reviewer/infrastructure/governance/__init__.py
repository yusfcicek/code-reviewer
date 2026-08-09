"""Where a decision record goes, and what identifies the run that made it."""

from .identity import build_run_identity
from .json_sink import JsonAuditSink

__all__ = ["JsonAuditSink", "build_run_identity"]
