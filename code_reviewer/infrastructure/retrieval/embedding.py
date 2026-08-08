"""A deterministic embedding with no weights and no network.

Every source names a hosted embedding model, and this is not one. It is worse
at meaning and better at everything else: nothing to download, no endpoint to
fail, no non-determinism in CI, and a test suite that runs in seconds
(decision D-3).

The trick is old and it works: hash each token into a fixed number of buckets,
count, and normalise. Texts sharing tokens land near each other; texts sharing
none are orthogonal. It has no idea that `authenticate` and `login` are
related, which is exactly the gap a trained model closes — and closing it is
one constructor call away, because `EmbeddingModel` is a port.

The digest is `blake2b`, not the builtin `hash`. Python salts `hash()` per
process, so an index built in one run would not match a query embedded in the
next, and the failure would be silent and intermittent.

Tokenisation is the other half of the work, and it is shared with BM25:
`get_user` has to be findable as `get_user`, as `get` and as `user`, because a
reviewer searching for one of the three should not have to guess which the
author wrote.
"""

import hashlib
import math
import re

from code_reviewer.application.ports import EmbeddingModel
from code_reviewer.domain.retrieval import Vector

#: Default width. Wide enough that unrelated tokens rarely collide, narrow
#: enough that a repository's vectors stay small.
DEFAULT_DIMENSIONS = 512

#: Identifier-shaped runs. Everything else is a separator.
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")

#: A camelCase or PascalCase boundary.
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def tokenise(text: str) -> list[str]:
    """Lowercased tokens: whole identifiers and their parts, in order.

    Both, deliberately. Keeping only the parts loses the exact match that is
    code search's strongest signal; keeping only the whole makes a search for
    `user` miss `get_user`.
    """
    tokens: list[str] = []

    for word in _WORD.findall(text):
        lowered = word.lower()
        tokens.append(lowered)
        # Split on the original spelling: lowercasing first would erase the
        # only evidence of where a camelCase boundary was.
        parts = [part for segment in word.split("_") for part in _CAMEL.split(segment) if part]
        tokens.extend(part.lower() for part in parts if part.lower() != lowered)

    # A dotted path is not one identifier run, so its segments arrive
    # separately; nothing extra is needed for them.
    return tokens


class HashingEmbedding(EmbeddingModel):
    """Hashed token counts, L2-normalised.

    Args:
        dimensions: Vector width. More dimensions mean fewer collisions and
            larger vectors.
    """

    def __init__(self, dimensions: int = DEFAULT_DIMENSIONS):
        if dimensions <= 0:
            raise ValueError("An embedding needs at least one dimension.")
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: list[str]) -> list[Vector]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> Vector:
        counts = [0.0] * self._dimensions

        for token in tokenise(text):
            counts[self._bucket(token)] += 1.0

        magnitude = math.sqrt(sum(value * value for value in counts))
        if magnitude == 0.0:
            # Text with no tokens at all: whitespace, punctuation, an empty
            # string. Zero is the honest answer, and `cosine_similarity`
            # already treats it as similar to nothing.
            return tuple(counts)

        return tuple(value / magnitude for value in counts)

    def _bucket(self, token: str) -> int:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big") % self._dimensions
