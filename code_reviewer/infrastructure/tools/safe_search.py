"""Building a search command out of an untrusted pattern.

The pattern reaches this module from the model, and the model got it from the
diff — so whoever opened the merge request chose it. Three rules follow, and
none of them are about the shell: `subprocess` is called with ``shell=False``,
so there is no shell to inject into.

**Fixed string, not regex.** Without ``-F``, `grep` reads the pattern as a
basic regular expression. A symbol containing ``.`` matches more than it
should, one containing ``*`` matches something else entirely, and a crafted
pattern backtracks catastrophically inside a job that blocks the merge (finding
G-06).

**After ``--``.** Everything past the separator is data. Without it, ``-c``,
``--include=*.env`` and ``-f/etc/passwd`` are read as flags.

**Never over credentials.** Excluding `build/` is about noise. Excluding
``.env`` and ``*.pem`` is about what comes back in the observation and, from
there, into a merge-request comment anyone can read.
"""

import re
from collections.abc import Sequence

#: Long enough for a fully qualified symbol, short enough that a pattern built
#: from a paragraph of prose is refused rather than searched for.
MAX_PATTERN_LENGTH = 200

#: Default cap on matches. A search that returns ten thousand lines has not
#: answered a question; it has moved the file into the prompt.
DEFAULT_MAX_COUNT = 200

#: What a symbol looks like in source: identifier characters, the qualified-name
#: separator, C++ scope resolution, and the dashes and dots of a file name.
_VALID_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:/-]*$")

#: Directories never worth searching. Cost, not safety — except `.git`, which
#: holds every version of every secret ever committed.
EXCLUDED_DIRS = (
    ".git",
    ".gradle",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
)

#: Files whose *matching lines* must not come back. This list is safety.
EXCLUDED_FILES = (
    ".env",
    ".env.*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_*",
    "*.lock",
    "*.min.js",
)


class InvalidPatternError(ValueError):
    """The pattern cannot be used in a search command."""


def validate_pattern(pattern: str) -> str:
    """Checks a pattern and returns it trimmed.

    Refuses rather than sanitises. Stripping a leading ``-`` and searching for
    what is left produces an answer to a question nobody asked, and nothing in
    the output says so (decision D-6).

    Raises:
        InvalidPatternError: if the pattern is empty, over-long, flag-shaped,
            or carries control or shell-significant characters.
    """
    if not isinstance(pattern, str):
        raise InvalidPatternError(f"Pattern must be a string, got {type(pattern).__name__}.")

    stripped = pattern.strip()

    if not stripped:
        raise InvalidPatternError("Pattern must not be empty.")

    if len(stripped) > MAX_PATTERN_LENGTH:
        raise InvalidPatternError(
            f"Pattern is {len(stripped)} characters, longer than the {MAX_PATTERN_LENGTH} allowed."
        )

    if any(character in stripped for character in "\n\r\x00"):
        raise InvalidPatternError(f"Pattern must not contain control characters: {pattern!r}")

    if stripped.startswith("-"):
        raise InvalidPatternError(f"Pattern must not start with '-', which looks like a flag: {stripped!r}")

    if ".." in stripped:
        raise InvalidPatternError(f"Pattern must not contain path traversal: {stripped!r}")

    if not _VALID_PATTERN.match(stripped):
        raise InvalidPatternError(f"Pattern contains unsupported characters: {stripped!r}")

    return stripped


def build_grep_command(
    pattern: str,
    paths: Sequence[str],
    max_count: int = DEFAULT_MAX_COUNT,
) -> list[str]:
    """Assembles an argv for `grep` that treats the pattern as data.

    Args:
        pattern: The search term, validated before use.
        paths: Where to search. At least one.
        max_count: Matches per file before `grep` moves on.

    Raises:
        InvalidPatternError: if the pattern does not validate.
        ValueError: if no path was given.
    """
    validated = validate_pattern(pattern)

    if not paths:
        raise ValueError("At least one search path is required.")

    command = ["grep", "-rnI", "-F", f"--max-count={max_count}"]
    command += [f"--exclude-dir={name}" for name in EXCLUDED_DIRS]
    command += [f"--exclude={name}" for name in EXCLUDED_FILES]
    command.append("--")
    command.append(validated)
    command.extend(paths)

    return command
