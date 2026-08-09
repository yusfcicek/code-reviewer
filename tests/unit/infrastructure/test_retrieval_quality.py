"""Step 12 — is the hybrid worth the code?

A small corpus with known answers, scored with the same `ConfusionMatrix` the
Level 12 harness uses for findings. One vocabulary for "how good is this",
whether the thing being judged is an analyzer or a retriever.

The floor is not the interesting assertion. The interesting one is that the
fusion beats both halves on their own: two retrievers that agree add nothing,
and if the hybrid only matched the better half then the second index would be
code with no argument behind it.
"""

import pytest

from code_reviewer.application.retrieval_service import HybridRetriever
from code_reviewer.domain.evaluation import ConfusionMatrix
from code_reviewer.domain.retrieval import CodeChunk
from code_reviewer.infrastructure.retrieval.embedding import HashingEmbedding
from code_reviewer.infrastructure.retrieval.lexical import BM25Index
from code_reviewer.infrastructure.retrieval.vector_index import InMemoryVectorIndex

#: Recall the hybrid must hold at the cutoff below. Read off the measurement
#: (9 of 11) with a margin, the same rule Level 12's decision D-4 set for the
#: analyzers' floors.
MIN_RECALL = 0.75

CORPUS: list[CodeChunk] = [
    CodeChunk(
        path="auth/tokens.py",
        start_line=1,
        end_line=6,
        name="verify_token",
        text=(
            "def verify_token(token):\n"
            "    payload = decode_jwt(token)\n"
            "    if payload['exp'] < now():\n"
            "        raise ExpiredToken()\n"
            "    return payload"
        ),
    ),
    CodeChunk(
        path="auth/passwords.py",
        start_line=1,
        end_line=5,
        name="hash_password",
        text=(
            "def hash_password(plain):\n"
            "    salt = secrets.token_bytes(16)\n"
            "    return argon2.hash(plain, salt)"
        ),
    ),
    CodeChunk(
        path="billing/invoice.py",
        start_line=1,
        end_line=6,
        name="render_invoice",
        text=(
            "def render_invoice(order):\n"
            "    lines = [format_line(item) for item in order.items]\n"
            "    return TEMPLATE.render(lines=lines, total=order.total)"
        ),
    ),
    CodeChunk(
        path="billing/tax.py",
        start_line=1,
        end_line=5,
        name="calculate_tax",
        text="def calculate_tax(amount, rate):\n    return round(amount * rate, 2)",
    ),
    CodeChunk(
        path="storage/repository.py",
        start_line=1,
        end_line=8,
        name="CustomerRepository.find_by_id",
        text=(
            "def find_by_id(self, customer_id):\n"
            "    cursor = self._connection.cursor()\n"
            "    cursor.execute('SELECT * FROM customers WHERE id = ?', (customer_id,))\n"
            "    return cursor.fetchone()"
        ),
    ),
    CodeChunk(
        path="storage/migrations.py",
        start_line=1,
        end_line=6,
        name="apply_migration",
        text=(
            "def apply_migration(connection, statement):\n"
            "    connection.execute(statement)\n"
            "    connection.commit()"
        ),
    ),
    CodeChunk(
        path="http/client.py",
        start_line=1,
        end_line=7,
        name="request_with_retry",
        text=(
            "def request_with_retry(url, attempts=3):\n"
            "    for attempt in range(attempts):\n"
            "        try:\n"
            "            return httpx.get(url, timeout=10)\n"
            "        except httpx.TimeoutException:\n"
            "            continue"
        ),
    ),
    CodeChunk(
        path="http/rate_limit.py",
        start_line=1,
        end_line=6,
        name="throttle",
        text=(
            "def throttle(key, limit_per_minute):\n"
            "    count = redis.incr(key)\n"
            "    return count <= limit_per_minute"
        ),
    ),
    CodeChunk(
        path="util/text.py",
        start_line=1,
        end_line=4,
        name="slugify",
        text="def slugify(value):\n    return re.sub(r'[^a-z0-9]+', '-', value.lower())",
    ),
    CodeChunk(
        path="util/dates.py",
        start_line=1,
        end_line=4,
        name="to_iso",
        text="def to_iso(moment):\n    return moment.astimezone(timezone.utc).isoformat()",
    ),
]

#: Query, and the chunk name a reviewer asking it wants back.
#:
#: The first six share vocabulary with the code, which is the easy case and the
#: common one — a diff is written in the same words as the module it changes.
#: The last five are paraphrases that share almost no tokens with their answer,
#: which is where a hashed embedding has nothing to offer and a trained one
#: would. Two of them are missed by everything here, and that is recorded
#: rather than removed: the corpus that only contains questions the system
#: answers is the retrieval equivalent of a dataset that states what the
#: analyzers already find.
QUERIES: list[tuple[str, str]] = [
    ("verify_token expired jwt payload", "verify_token"),
    ("hash a password with a salt", "hash_password"),
    ("execute a parameterised SELECT against the customers table", "CustomerRepository.find_by_id"),
    ("retry an http request after a timeout", "request_with_retry"),
    ("calculate_tax amount rate", "calculate_tax"),
    ("render an invoice from an order's items", "render_invoice"),
    ("token expiry check", "verify_token"),
    ("store a credential so it cannot be read back", "hash_password"),
    ("keep a caller under its allowance", "throttle"),
    ("turn a title into a url-safe string", "slugify"),
    ("schema change applied to the database", "apply_migration"),
]

#: How many chunks a query is allowed. Two rather than five: at a generous
#: cutoff every retriever looks alike, and the measurement stops separating
#: anything.
CUTOFF = 2


def _retriever(**overrides) -> HybridRetriever:
    retriever = HybridRetriever(
        embedding=HashingEmbedding(dimensions=512),
        lexical=BM25Index(),
        vectors=InMemoryVectorIndex(),
        **overrides,
    )
    retriever.index(list(CORPUS))
    return retriever


def _recall(hits: list[bool]) -> ConfusionMatrix:
    """One expected answer per query: found is a true positive, missed a false
    negative. Precision is not meaningful at a fixed cutoff — every query
    returns `CUTOFF` chunks whatever the corpus holds — so only recall is
    read."""
    return ConfusionMatrix(
        true_positives=sum(hits),
        false_negatives=sum(1 for hit in hits if not hit),
    )


def _hybrid_hits() -> list[bool]:
    retriever = _retriever()
    return [
        expected in {chunk.name for chunk in retriever.related(query, limit=CUTOFF)}
        for query, expected in QUERIES
    ]


def _lexical_only_hits() -> list[bool]:
    index = BM25Index()
    index.add(list(CORPUS))
    return [
        expected in {scored.chunk.name for scored in index.search(query, CUTOFF)}
        for query, expected in QUERIES
    ]


def _dense_only_hits() -> list[bool]:
    model = HashingEmbedding(dimensions=512)
    index = InMemoryVectorIndex()
    index.add(list(zip(CORPUS, model.embed([chunk.text for chunk in CORPUS]), strict=True)))
    return [
        expected in {scored.chunk.name for scored in index.search(model.embed([query])[0], CUTOFF)}
        for query, expected in QUERIES
    ]


def test_the_hybrid_holds_its_recall_floor():
    matrix = _recall(_hybrid_hits())

    assert matrix.recall >= MIN_RECALL, f"recall@{CUTOFF} was {matrix.recall:.2f}"


def test_the_hybrid_is_at_least_as_good_as_either_half():
    """The argument for maintaining two indexes instead of one.

    If fusing them only matched the better half, the second index would be
    code with nothing behind it.
    """
    hybrid = _recall(_hybrid_hits()).recall
    lexical = _recall(_lexical_only_hits()).recall
    dense = _recall(_dense_only_hits()).recall

    assert hybrid > max(lexical, dense), f"hybrid {hybrid:.2f}, lexical {lexical:.2f}, dense {dense:.2f}"


def test_each_half_finds_something_the_other_misses():
    """If they agreed on everything, one of them would be redundant.

    They do not: the lexical half alone answers "turn a title into a url-safe
    string" (`slugify` shares the token `url`), and the dense half alone
    answers "store a credential so it cannot be read back" (no shared token
    with `hash_password`, but the surrounding vocabulary lands nearby).
    """
    lexical = _lexical_only_hits()
    dense = _dense_only_hits()

    assert any(left and not right for left, right in zip(lexical, dense, strict=True))
    assert any(right and not left for left, right in zip(lexical, dense, strict=True))


def test_the_paraphrase_gap_is_recorded_rather_than_hidden():
    """Two queries are missed by every configuration here.

    "keep a caller under its allowance" shares no token with `throttle`, and
    neither does "schema change applied to the database" with
    `apply_migration`. A hashed embedding has no notion that they are related,
    and no amount of fusion invents one. This is the measurement that says
    what swapping `EmbeddingModel` for a trained adapter would buy — and it is
    a test rather than a comment so that it fails, loudly, on the day someone
    does it.
    """
    hits = _hybrid_hits()
    missed = [query for (query, _), hit in zip(QUERIES, hits, strict=True) if not hit]

    assert missed == [
        "keep a caller under its allowance",
        "schema change applied to the database",
    ], missed


def test_diversification_does_not_cost_recall_at_this_cutoff():
    """Novelty is bought with relevance, so it can cost recall. At λ=0.7 over
    a corpus with no near-duplicates it should not, and this is what says so
    if the weight is ever changed."""
    relevance_only = HybridRetriever(
        embedding=HashingEmbedding(dimensions=512),
        lexical=BM25Index(),
        vectors=InMemoryVectorIndex(),
        relevance_weight=1.0,
    )
    relevance_only.index(list(CORPUS))

    diversified = _recall(_hybrid_hits()).recall
    undiversified = _recall(
        [
            expected in {chunk.name for chunk in relevance_only.related(query, limit=CUTOFF)}
            for query, expected in QUERIES
        ]
    ).recall

    assert diversified == pytest.approx(undiversified)
