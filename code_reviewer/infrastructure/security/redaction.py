"""Masking secrets before the review leaves the process.

The agent reads files and quotes what it finds, and its output goes to two
places that cannot be taken back: the CI log and a merge-request comment.
Deleting the comment does not undo it — the text is already in the notification
emails and the webhook history (finding G-04).

Two layers, applied in this order:

1. **Values.** The actual contents of known secret-bearing environment
   variables, masked wherever they appear in whatever form. This layer has no
   false negatives: if the process holds the token, any appearance of it is
   caught regardless of how the model mangled the text around it.
2. **Shapes.** Private key blocks, cloud access keys, platform tokens, bearer
   credentials, assignment expressions. This is the fallback for secrets this
   process does not hold, and it is the layer that will miss things.

Values first, because a value match is certain and a shape match is a guess
(decision D-1).
"""

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from re import Match, Pattern

MASK = "[REDACTED]"

#: Environment variables whose *values* are masked wherever they appear.
SECRET_ENV_VARS = (
    "GITLAB_TOKEN",
    "CI_JOB_TOKEN",
    "VLLM_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GITHUB_TOKEN",
)

#: Shorter environment values are not masked. Replacing every occurrence of an
#: eight-character string would shred an ordinary review, and a secret that
#: short has a bigger problem than this module (decision D-2).
MIN_ENV_SECRET_LENGTH = 8

#: In an assignment, a shorter value is a placeholder: `password = "x"` in an
#: example is not a leak.
MIN_ASSIGNED_SECRET_LENGTH = 6

#: ``(pattern, group)``. Group 0 means mask the whole match; a positive group
#: means mask only that capture, leaving the surrounding text — the header
#: name, the variable name — legible.
_PATTERN_SPECS: tuple[tuple[str, int], ...] = (
    # Private key blocks, body included. `[\s\S]` rather than `.` with DOTALL,
    # so the pattern spans lines regardless of how it is compiled.
    (r"-----BEGIN[^-]*PRIVATE KEY-----[\s\S]*?-----END[^-]*PRIVATE KEY-----", 0),
    (r"-----BEGIN[^-]*PRIVATE KEY-----", 0),
    # Cloud and platform token shapes.
    (r"\bAKIA[0-9A-Z]{16}\b", 0),
    (r"\bASIA[0-9A-Z]{16}\b", 0),
    (r"\bglpat-[A-Za-z0-9_\-]{20,}", 0),
    (r"\bgh[pousr]_[A-Za-z0-9]{20,}", 0),
    (r"\bsk-[A-Za-z0-9]{20,}", 0),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}", 0),
    # Authorization headers: the scheme stays, the credential goes.
    (r"(?:Bearer|Basic)\s+([A-Za-z0-9._\-+/=]{12,})", 1),
    # key = "value" — the name is often the most useful part of the finding.
    (
        r"(?:password|passwd|secret|secret[_-]?key|api[_-]?key|access[_-]?token|"
        r"auth[_-]?token|private[_-]?key|token)\s*[:=]\s*"
        rf"[\"']([^\"'\n]{{{MIN_ASSIGNED_SECRET_LENGTH},}})[\"']",
        1,
    ),
    # KEY=value, as an environment assignment.
    (
        r"(?:[A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_KEY|ACCESS_KEY))\s*=\s*"
        rf"([^\s\"'#]{{{MIN_ASSIGNED_SECRET_LENGTH},}})",
        1,
    ),
)


def _compile(specs: Iterable[tuple[str, int]]) -> list[tuple[Pattern[str], int]]:
    return [(re.compile(pattern, re.IGNORECASE), group) for pattern, group in specs]


@dataclass(frozen=True)
class RedactionResult:
    """The redacted text and how many spans were masked."""

    text: str
    count: int


class SecretRedactor:
    """Masks secrets in text on its way out of the process.

    Args:
        values: Literal secret values to mask wherever they appear. Anything
            shorter than :data:`MIN_ENV_SECRET_LENGTH` is dropped.
    """

    def __init__(self, values: Iterable[str] | None = None):
        self._patterns = _compile(_PATTERN_SPECS)
        # Longest first: masking "prefix-secret" before "prefix-secret-longer"
        # would leave "-longer" in the output, which is worse than useless
        # because it looks redacted.
        self._values: list[str] = sorted(
            {value for value in (values or ()) if value and len(value) >= MIN_ENV_SECRET_LENGTH},
            key=len,
            reverse=True,
        )

    @classmethod
    def from_environment(cls, env_vars: Iterable[str] = SECRET_ENV_VARS) -> "SecretRedactor":
        """A redactor that also masks the secrets this process was given."""
        return cls(values=[os.environ.get(name, "") for name in env_vars])

    def redact(self, text: str) -> str:
        return self.redact_with_report(text).text

    def redact_with_report(self, text: str) -> RedactionResult:
        """Masks, and reports how much was masked.

        The count is worth logging: a review that redacted forty spans is a
        review someone should look at, whether the secrets were real or the
        patterns were wrong.
        """
        if not text:
            return RedactionResult(text=text, count=0)

        redacted = text
        count = 0

        for value in self._values:
            occurrences = redacted.count(value)
            if occurrences:
                count += occurrences
                redacted = redacted.replace(value, MASK)

        for pattern, group in self._patterns:
            # `group` is bound as a default argument. Left as a free variable
            # it would close over the loop, which happens to work today
            # because `re.sub` runs within the same iteration — a silent
            # order-dependent bug sitting in a waiting room.
            def _replace(match: Match[str], _group: int = group) -> str:
                nonlocal count
                count += 1
                if _group == 0:
                    return MASK
                secret = match.group(_group)
                if not secret:
                    return match.group(0)
                return match.group(0).replace(secret, MASK)

            redacted = pattern.sub(_replace, redacted)

        return RedactionResult(text=redacted, count=count)
