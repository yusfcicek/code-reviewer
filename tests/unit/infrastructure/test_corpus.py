"""Step 10 — building an index out of a checkout."""

from code_reviewer.infrastructure.retrieval.corpus import build_retriever, collect_chunks


def _repository(root):
    (root / "pkg").mkdir()
    (root / "pkg" / "auth.py").write_text(
        "def authenticate_user(token):\n    return verify(token)\n", encoding="utf-8"
    )
    (root / "pkg" / "billing.py").write_text(
        "def render_invoice(order):\n    return str(order)\n", encoding="utf-8"
    )
    (root / "settings.yaml").write_text("timeout: 30\nretries: 3\n", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n binary")
    return root


def test_every_indexable_file_is_chunked(tmp_path):
    chunks = collect_chunks(_repository(tmp_path))

    paths = {chunk.path for chunk in chunks}
    assert "pkg/auth.py" in paths
    assert "pkg/billing.py" in paths
    assert "settings.yaml" in paths


def test_a_file_that_is_not_source_is_not_indexed(tmp_path):
    chunks = collect_chunks(_repository(tmp_path))

    assert all(not chunk.path.endswith(".png") for chunk in chunks)


def test_a_credential_file_is_not_indexed(tmp_path):
    """`Workspace` refuses it, and the indexer inherits that rather than
    reimplementing it. An index is a copy of everything it read."""
    _repository(tmp_path)
    (tmp_path / "deploy.key").write_text("PRIVATE KEY\n", encoding="utf-8")
    (tmp_path / "pkg" / "id_rsa").write_text("PRIVATE KEY\n", encoding="utf-8")

    chunks = collect_chunks(tmp_path)

    assert all("id_rsa" not in chunk.path and ".key" not in chunk.path for chunk in chunks)


def test_a_virtualenv_is_not_walked(tmp_path):
    _repository(tmp_path)
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "vendored.py").write_text("def vendored(): ...\n", encoding="utf-8")

    chunks = collect_chunks(tmp_path)

    assert all(".venv" not in chunk.path for chunk in chunks)


def test_an_unreadable_file_is_skipped_rather_than_fatal(tmp_path):
    _repository(tmp_path)
    (tmp_path / "pkg" / "broken.py").write_bytes(b"\xff\xfe\x00 not utf-8")

    chunks = collect_chunks(tmp_path)

    assert chunks
    assert all(chunk.path != "pkg/broken.py" for chunk in chunks)


def test_a_directory_that_does_not_exist_yields_nothing(tmp_path):
    assert collect_chunks(tmp_path / "nowhere") == []


def test_the_file_ceiling_is_respected(tmp_path):
    _repository(tmp_path)

    assert len({chunk.path for chunk in collect_chunks(tmp_path, max_files=1)}) == 1


def test_the_chunk_ceiling_is_respected(tmp_path):
    _repository(tmp_path)

    assert len(collect_chunks(tmp_path, max_chunks=2)) == 2


def test_the_order_is_stable(tmp_path):
    _repository(tmp_path)

    assert collect_chunks(tmp_path) == collect_chunks(tmp_path)


# -- the retriever it produces ----------------------------------------------


def test_the_built_retriever_answers_a_query(tmp_path):
    retriever = build_retriever(_repository(tmp_path))

    found = retriever.related("authenticate_user token", limit=2)

    assert any(chunk.path == "pkg/auth.py" for chunk in found)


def test_a_retriever_over_an_empty_directory_is_usable(tmp_path):
    """An empty index is not an error state. A new repository has one."""
    retriever = build_retriever(tmp_path)

    assert retriever.related("anything", limit=3) == []


def test_the_file_under_review_is_excluded_by_its_indexed_path(tmp_path):
    """The exclusion is by the path the corpus stored, which is relative to
    the checkout — the same shape the forge reports a changed file as."""
    retriever = build_retriever(_repository(tmp_path))

    found = retriever.related("authenticate_user token", limit=3, exclude_path="pkg/auth.py")

    assert all(chunk.path != "pkg/auth.py" for chunk in found)


class TestARelativeRootIsIndexed:
    """Self-review S-05 — the defect Level 23 found in its own copy of this
    pattern and did not look for in the original.

    `Workspace` resolves the paths it is given *against its root*, so walking a
    relative root relatively produced `pkg/pkg/app.py`, every read was refused,
    and the index came back empty. Measured before the fix:

        collect_chunks('code_reviewer')   -> 0 chunks
        collect_chunks('./code_reviewer') -> 0 chunks
        collect_chunks('.')               -> 4205 chunks
        collect_chunks('<absolute>')      -> 1172 chunks

    Retrieval was therefore silently dead since Level 13 for any relative root
    other than `.`. The default happens to be `.`, which is why nobody noticed —
    and why the log line read `Indexed 0 chunk(s)` rather than an error.
    """

    SOURCE = "def create_app(config):\n    return config\n"

    def _tree(self, tmp_path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "app.py").write_text(self.SOURCE)
        return tmp_path

    def test_a_relative_subdirectory_is_indexed(self, tmp_path, monkeypatch):
        from code_reviewer.infrastructure.retrieval.corpus import collect_chunks

        self._tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        assert collect_chunks("pkg")

    def test_a_dot_prefixed_relative_root_is_indexed(self, tmp_path, monkeypatch):
        from code_reviewer.infrastructure.retrieval.corpus import collect_chunks

        self._tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        assert collect_chunks("./pkg")

    def test_a_relative_root_indexes_the_same_files_as_an_absolute_one(self, tmp_path, monkeypatch):
        from code_reviewer.infrastructure.retrieval.corpus import collect_chunks

        tree = self._tree(tmp_path)
        absolute = collect_chunks(tree / "pkg")
        monkeypatch.chdir(tmp_path)

        assert len(collect_chunks("pkg")) == len(absolute)

    def test_chunk_paths_stay_relative_to_the_root(self, tmp_path, monkeypatch):
        from code_reviewer.infrastructure.retrieval.corpus import collect_chunks

        self._tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        assert next(chunk.path for chunk in collect_chunks("pkg")).startswith("app.py")
