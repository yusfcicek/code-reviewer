"""Token estimation as an explicit, injectable collaborator.

Both the memory strategy and the agent need to know roughly how many tokens a
piece of text will occupy. Neither of them should have to reach into the chat
model to find out, and neither should modify it: the strategy used to inject a
``get_num_tokens_from_messages`` implementation onto the shared ``ChatOpenAI``
instance with ``object.__setattr__``, so the agent's own token budgeting
silently received a chars/4 estimate instead of the model's tokenizer
(finding F-11).

A counter is any callable from ``str`` to ``int``, which keeps test doubles to
one line.
"""

from typing import Any, Callable, Optional, Protocol, runtime_checkable


@runtime_checkable
class TokenCounter(Protocol):
    """Estimates how many tokens a string occupies."""

    def __call__(self, text: str) -> int:  # pragma: no cover - protocol
        ...


class HeuristicTokenCounter:
    """Offline estimate of ``len(text) / CHARS_PER_TOKEN``.

    Deterministic and dependency-free, which matters in CI where the tokenizer
    for a self-hosted model is often unavailable. It under- and over-counts by
    roughly 20 % on source code, so callers should treat the result as a budget
    signal rather than an exact figure.
    """

    CHARS_PER_TOKEN = 4

    def __call__(self, text: str) -> int:
        return len(text) // self.CHARS_PER_TOKEN


class ModelTokenCounter:
    """Uses the chat model's tokenizer, falling back to the heuristic.

    Self-hosted models served through an OpenAI-compatible endpoint frequently
    have no tokenizer registered locally, in which case LangChain raises rather
    than guessing. The fallback keeps the caller working with a slightly worse
    number instead of failing the review.
    """

    def __init__(self, model: Any, fallback: Optional[Callable[[str], int]] = None):
        self._model = model
        self._fallback = fallback or HeuristicTokenCounter()

    def __call__(self, text: str) -> int:
        try:
            return int(self._model.get_num_tokens(text))
        except Exception:
            return self._fallback(text)
