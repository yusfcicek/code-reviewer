"""Step 5 — building the index, through the workspace rather than around it.

Level 8 bought path guarantees with a class that states them. Reading the tree
a second way here would be re-implementing them badly, so this adapter reads
through :class:`Workspace` and inherits its refusals.

What is *not* collected matters as much as what is. An option name assembled
at runtime cannot be seen by a parser, so it is not collected — and the rule
that reports unknown options is honest only because of that.
"""

from code_reviewer.infrastructure.documentation.workspace import build_symbol_index, collect_documents

SOURCE = '''
import os

MAX_LINES = 12


class Renderer:
    """Renders."""

    def render(self, version, outcome):
        return version


def create_app(config, worker=None):
    token = os.environ["REVIEW_TOKEN"]
    limit = os.getenv("REVIEW_LIMIT")
    return config, worker, token, limit


def _parser(parser):
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("-q", "--quiet")
'''


def _tree(tmp_path, **files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def test_functions_and_classes_are_indexed(tmp_path):
    index = build_symbol_index(_tree(tmp_path, **{"app.py": SOURCE}))

    assert index.resolves("create_app")
    assert index.resolves("Renderer")


def test_a_method_is_indexed_both_bare_and_qualified(tmp_path):
    index = build_symbol_index(_tree(tmp_path, **{"app.py": SOURCE}))

    assert index.resolves("render")
    assert index.resolves("Renderer.render")


def test_a_module_level_constant_is_indexed(tmp_path):
    assert build_symbol_index(_tree(tmp_path, **{"app.py": SOURCE})).resolves("MAX_LINES")


def test_parameters_exclude_the_implicit_ones(tmp_path):
    index = build_symbol_index(_tree(tmp_path, **{"app.py": SOURCE}))

    assert index.parameters_of("Renderer.render") == ("version", "outcome")
    assert index.parameters_of("create_app") == ("config", "worker")


def test_long_options_are_collected(tmp_path):
    index = build_symbol_index(_tree(tmp_path, **{"app.py": SOURCE}))

    assert index.knows_option("--strict")
    assert index.knows_option("--quiet")
    assert not index.knows_option("--loose")


def test_environment_names_are_collected_from_both_spellings(tmp_path):
    index = build_symbol_index(_tree(tmp_path, **{"app.py": SOURCE}))

    assert index.knows_environment("REVIEW_TOKEN")
    assert index.knows_environment("REVIEW_LIMIT")


def test_a_name_assembled_at_runtime_is_not_collected(tmp_path):
    """And so the unknown-option rule stays honest: what a parser cannot see,
    it does not claim to know."""
    source = 'import os\n\n\ndef read(suffix):\n    return os.environ["REVIEW_" + suffix]\n'

    index = build_symbol_index(_tree(tmp_path, **{"app.py": source}))

    assert not index.knows_environment("REVIEW_TOKEN")


def test_a_file_that_does_not_parse_does_not_stop_the_build(tmp_path):
    tree = _tree(tmp_path, **{"broken.py": "def (:\n", "app.py": SOURCE})

    assert build_symbol_index(tree).resolves("create_app")


def test_a_tree_with_no_python_yields_an_empty_index(tmp_path):
    assert build_symbol_index(_tree(tmp_path, **{"README.md": "# Title\n"})).is_empty


def test_a_missing_directory_yields_an_empty_index(tmp_path):
    assert build_symbol_index(tmp_path / "absent").is_empty


def test_documents_are_collected_with_their_relative_paths(tmp_path):
    tree = _tree(tmp_path, **{"README.md": "# Title\n", "docs/guide.md": "# Guide\n", "app.py": SOURCE})

    assert dict(collect_documents(tree)) == {"README.md": "# Title\n", "docs/guide.md": "# Guide\n"}


def test_a_directory_with_no_documents_yields_nothing(tmp_path):
    assert collect_documents(_tree(tmp_path, **{"app.py": SOURCE})) == []


def test_a_missing_directory_yields_no_documents(tmp_path):
    assert collect_documents(tmp_path / "absent") == []


def test_an_ordinary_dictionary_get_is_not_an_environment_read(tmp_path):
    """`.get("key")` on a dictionary is a dictionary key. Collecting those
    would widen the unknown-option rule until it accepted anything."""
    source = 'def read(settings):\n    return settings.get("RETRY_LIMIT")\n'

    index = build_symbol_index(_tree(tmp_path, **{"app.py": source}))

    assert not index.knows_environment("RETRY_LIMIT")


def test_an_environment_mapping_passed_in_is_still_collected(tmp_path):
    """`max_comment_chars_from_env(env)` reads `env.get(...)`, and the name
    of the receiver is the only evidence available that it is the environment."""
    source = 'def read(env):\n    return env.get("REVIEW_MAX_COMMENT_CHARS")\n'

    index = build_symbol_index(_tree(tmp_path, **{"app.py": source}))

    assert index.knows_environment("REVIEW_MAX_COMMENT_CHARS")


def test_a_relative_root_is_indexed_like_an_absolute_one(tmp_path, monkeypatch):
    """`Workspace` resolves paths against its root, so a relative root walked
    relatively produced `pkg/pkg/app.py` and every read was refused. The index
    came back empty and looked like a repository with no Python in it."""
    _tree(tmp_path, **{"pkg/app.py": SOURCE})
    monkeypatch.chdir(tmp_path)

    assert build_symbol_index("pkg").resolves("create_app")
    assert [path for path, _ in collect_documents(".")] == []
