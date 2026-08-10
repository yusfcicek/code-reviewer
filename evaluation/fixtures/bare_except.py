"""A handler that catches everything, and one that catches something.

The second is here so a rule that fires on any `except` is caught by the
forbidden expectation rather than by somebody noticing.
"""


def read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except:
        return None


def read_carefully(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None
