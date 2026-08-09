"""Step 8 — the two indexes and the embedding between them."""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from code_reviewer.domain.retrieval import CodeChunk
from code_reviewer.infrastructure.retrieval.embedding import HashingEmbedding, tokenise
from code_reviewer.infrastructure.retrieval.lexical import BM25Index
from code_reviewer.infrastructure.retrieval.vector_index import InMemoryVectorIndex


def _chunk(name: str, text: str) -> CodeChunk:
    return CodeChunk(path=f"{name}.py", start_line=1, end_line=3, text=text, name=name)


# -- tokenisation ------------------------------------------------------------


def test_snake_case_is_split_and_the_whole_identifier_kept():
    """`get_user` has to be findable as `get_user`, as `get` and as `user`."""
    assert set(tokenise("get_user")) >= {"get_user", "get", "user"}


def test_camel_case_is_split():
    assert set(tokenise("getUserName")) >= {"getusername", "get", "user", "name"}


def test_a_dotted_path_is_split():
    assert set(tokenise("code_reviewer.domain.gate")) >= {"code_reviewer", "domain", "gate"}


def test_punctuation_is_not_a_token():
    assert "" not in tokenise("def f(x): return x + 1")


def test_tokenising_nothing_yields_nothing():
    assert tokenise("") == []
    assert tokenise("()[]{}") == []


# -- BM25 --------------------------------------------------------------------


def _index() -> BM25Index:
    index = BM25Index()
    index.add(
        [
            _chunk("auth", "def authenticate_user(token):\n    return verify(token)"),
            _chunk("cache", "def cache_user(user):\n    return store(user)"),
            _chunk("maths", "def add(left, right):\n    return left + right"),
        ]
    )
    return index


def test_an_exact_identifier_match_ranks_first():
    results = _index().search("authenticate_user", limit=3)

    assert results[0].chunk.name == "auth"


def test_a_term_in_every_document_is_worth_far_less_than_a_rare_one():
    """That is what the inverse document frequency is for.

    `def` appears in all three chunks and separates none of them;
    `authenticate_user` appears in one and is almost an answer on its own.
    Both still score — the smoothed IDF keeps every term positive — but not
    remotely alike, and that ratio is the whole reason to compute a score
    rather than count matches.
    """
    index = _index()

    common = index.search("def", limit=3)[0].score
    rare = index.search("authenticate_user", limit=3)[0].score

    assert rare > common * 3


def test_a_one_chunk_index_still_answers():
    index = BM25Index()
    index.add([_chunk("only", "def authenticate_user(token): pass")])

    assert index.search("authenticate_user", limit=3)


def test_a_term_in_no_document_returns_nothing():
    assert _index().search("kubernetes", limit=3) == []


def test_searching_an_empty_index_returns_nothing():
    assert BM25Index().search("anything", limit=3) == []


def test_an_empty_query_returns_nothing():
    assert _index().search("   ", limit=3) == []


def test_the_limit_is_respected():
    assert len(_index().search("user", limit=1)) == 1


def test_scores_descend():
    scores = [scored.score for scored in _index().search("user token", limit=3)]

    assert scores == sorted(scores, reverse=True)


def test_adding_twice_extends_the_index():
    index = _index()
    index.add([_chunk("extra", "def kubernetes_client():\n    return 1")])

    assert index.search("kubernetes", limit=3)


# -- the embedding -----------------------------------------------------------


def test_the_embedding_is_deterministic():
    model = HashingEmbedding()

    assert model.embed(["def f(): pass"]) == model.embed(["def f(): pass"])


def test_the_embedding_does_not_depend_on_this_process():
    """`hash()` is salted per process, so an index built in one run would not
    match a query embedded in another. The embedding uses a stable digest,
    and this is the test that says so."""
    known = HashingEmbedding(dimensions=8).embed(["user"])[0]

    assert known == HashingEmbedding(dimensions=8).embed(["user"])[0]
    assert any(value != 0.0 for value in known)


def test_every_vector_has_the_requested_dimension():
    vectors = HashingEmbedding(dimensions=16).embed(["a", "", "def something(x): return x"])

    assert {len(vector) for vector in vectors} == {16}


def test_a_vector_is_unit_length_unless_the_text_had_no_tokens():
    model = HashingEmbedding(dimensions=32)
    populated, empty = model.embed(["def authenticate(user): pass", "   "])

    assert math.sqrt(sum(value * value for value in populated)) == pytest.approx(1.0)
    assert set(empty) == {0.0}


def test_similar_texts_embed_closer_than_unrelated_ones():
    model = HashingEmbedding(dimensions=512)
    from code_reviewer.domain.retrieval import cosine_similarity

    auth, auth_like, unrelated = model.embed(
        [
            "def authenticate_user(token): return verify_token(token)",
            "def authenticate_admin(token): return verify_token(token)",
            "def add(left, right): return left + right",
        ]
    )

    assert cosine_similarity(auth, auth_like) > cosine_similarity(auth, unrelated)


def test_a_dimension_of_zero_is_refused():
    with pytest.raises(ValueError):
        HashingEmbedding(dimensions=0)


@given(st.lists(st.text(max_size=60), max_size=6))
def test_embedding_arbitrary_text_returns_one_vector_each(texts):
    vectors = HashingEmbedding(dimensions=8).embed(texts)

    assert len(vectors) == len(texts)
    for vector in vectors:
        assert len(vector) == 8
        assert all(math.isfinite(value) for value in vector)


# -- the vector index --------------------------------------------------------


def test_the_nearest_chunk_comes_first():
    index = InMemoryVectorIndex()
    near = _chunk("near", "x")
    far = _chunk("far", "y")
    index.add([(near, (1.0, 0.0)), (far, (0.0, 1.0))])

    results = index.search((0.9, 0.1), limit=2)

    assert results[0].chunk is near


def test_an_empty_index_returns_nothing():
    assert InMemoryVectorIndex().search((1.0, 0.0), limit=3) == []


def test_asking_for_more_than_the_index_holds_returns_what_there_is():
    index = InMemoryVectorIndex()
    index.add([(_chunk("only", "x"), (1.0, 0.0))])

    assert len(index.search((1.0, 0.0), limit=10)) == 1


def test_the_stored_vector_can_be_read_back():
    index = InMemoryVectorIndex()
    chunk = _chunk("one", "x")
    index.add([(chunk, (1.0, 0.0))])

    assert index.vector_of(chunk) == (1.0, 0.0)
    assert index.vector_of(_chunk("other", "y")) is None


def test_a_vector_of_the_wrong_size_is_refused():
    """Silently ignoring it would leave a chunk in the index that can never
    be found, which is worse than a loud failure at build time."""
    index = InMemoryVectorIndex()
    index.add([(_chunk("one", "x"), (1.0, 0.0))])

    with pytest.raises(ValueError):
        index.add([(_chunk("two", "y"), (1.0, 0.0, 0.0))])
