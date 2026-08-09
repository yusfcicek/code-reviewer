"""Step 2 — what the code offers, and what an empty answer means.

The last two tests are the ones that matter. An index that failed to build
resolves nothing, and a rule that reads "nothing resolves" as "everything is
dead" would report the entire README on the first bad day. The index says it is
empty, and the rules refuse to run against it.
"""

from code_reviewer.domain.documentation import SymbolIndex

INDEX = SymbolIndex(
    names=frozenset({"create_app", "AgentExecutor", "report.render", "MAX_LINES"}),
    signatures={"create_app": ("config", "worker"), "report.render": ("version",)},
    options=frozenset({"--strict"}),
    environment=frozenset({"CI_PROJECT_ID"}),
)


def test_a_bare_name_resolves():
    assert INDEX.resolves("create_app")


def test_a_dotted_path_resolves_by_its_full_name():
    assert INDEX.resolves("report.render")


def test_a_dotted_path_resolves_by_its_final_segment():
    """A document writes `module.create_app` for a function indexed bare."""
    assert INDEX.resolves("code_reviewer.serve.create_app")


def test_an_absent_name_does_not_resolve():
    assert not INDEX.resolves("create_apps")


def test_parameters_are_returned_for_a_function():
    assert INDEX.parameters_of("create_app") == ("config", "worker")


def test_a_known_name_that_is_not_a_function_returns_none():
    """Not a function and not indexed are different answers."""
    assert INDEX.parameters_of("MAX_LINES") is None


def test_an_unknown_name_returns_none():
    assert INDEX.parameters_of("nothing_here") is None


def test_an_option_is_known():
    assert INDEX.knows_option("--strict")
    assert not INDEX.knows_option("--loose")


def test_an_environment_name_is_known():
    assert INDEX.knows_environment("CI_PROJECT_ID")
    assert not INDEX.knows_environment("CI_PROJECT_SLUG")


def test_an_environment_name_that_is_a_module_constant_is_known():
    """`MAX_LINES` in a document is a constant, not a missing variable."""
    assert INDEX.knows_environment("MAX_LINES")


def test_an_empty_index_says_so():
    assert SymbolIndex.EMPTY.is_empty
    assert not INDEX.is_empty


def test_an_empty_index_resolves_nothing():
    assert not SymbolIndex.EMPTY.resolves("create_app")
