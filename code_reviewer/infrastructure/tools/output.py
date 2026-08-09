"""How much of a tool's output the model is allowed to see.

One cap, shared. It lives in its own module because two tool modules need it
and neither should import the other — the alternative was a circular import
between the filesystem tools and the retrieval tool, which is the usual way a
"just put it in the big module" decision announces itself.
"""

#: Longest tool output handed back to the model. Beyond this the observation
#: crowds out the diff it is supposed to explain.
MAX_OUTPUT_CHARS = 2000


def truncate(text: str) -> str:
    """Caps ``text``, saying so where it was cut."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n[... truncated at {MAX_OUTPUT_CHARS} characters ...]"
