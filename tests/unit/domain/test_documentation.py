"""Step 1 — what a document claims, and what is merely a word in backticks.

The shape test is the whole precision argument of Level 23. This repository's
own README puts `async`, `false`, `critical` and `auto` in backticks beside
`AgentExecutor` and `create_app`, and a rule that cannot tell them apart would
report the English as dead code on its first run.
"""

from code_reviewer.domain.documentation import ClaimKind, claims_in

README_LIKE = """# Title

The gate reads `create_app` and the `AgentExecutor` it wraps.

## Options

Pass `--strict` to fail on warnings. Reads `CI_PROJECT_ID` from the environment.
"""


def _subjects(text, kind):
    return [claim.subject for claim in claims_in(text) if claim.kind is kind]


def test_a_symbol_shaped_token_becomes_a_claim():
    assert _subjects("Calls `create_app` at boot.", ClaimKind.SYMBOL) == ["create_app"]


def test_a_class_name_becomes_a_claim():
    assert _subjects("The `AgentExecutor` wrapper.", ClaimKind.SYMBOL) == ["AgentExecutor"]


def test_a_dotted_path_becomes_a_claim():
    assert _subjects("See `report.render_review_comment`.", ClaimKind.SYMBOL) == ["report.render_review_comment"]


def test_a_bare_call_becomes_a_symbol_claim():
    assert _subjects("Call `drain()` on exit.", ClaimKind.SYMBOL) == ["drain"]


def test_an_ordinary_word_in_backticks_is_not_a_claim():
    """AC-2 — the finding that would make this level unusable."""
    for word in ("async", "false", "critical", "auto", "true", "null"):
        assert claims_in(f"Set it to `{word}` here.") == [], word


def test_a_single_uppercase_word_is_not_a_claim():
    """`DEBUG`, `FAIL` and `CRITICAL` are enum values written as prose."""
    for word in ("DEBUG", "FAIL", "CRITICAL", "BREAKING"):
        assert claims_in(f"Reports `{word}`.") == [], word


def test_a_call_with_named_arguments_becomes_a_signature_claim():
    claim = claims_in("Use `render(version, outcome)`.")[0]

    assert claim.kind is ClaimKind.SIGNATURE
    assert claim.subject == "render"
    assert claim.arguments == ("version", "outcome")


def test_a_call_written_with_values_is_not_a_signature_claim():
    """A document showing usage is not a document stating a signature."""
    claims = claims_in('Use `render("1.0", 2)`.')

    assert [claim.kind for claim in claims] == [ClaimKind.SYMBOL]


def test_a_flag_becomes_an_option_claim():
    assert _subjects("Pass `--strict` to fail.", ClaimKind.OPTION) == ["--strict"]


def test_a_screaming_snake_name_becomes_an_environment_claim():
    assert _subjects("Reads `CI_PROJECT_ID`.", ClaimKind.ENVIRONMENT) == ["CI_PROJECT_ID"]


def test_a_fenced_python_block_becomes_an_example_claim():
    text = "# T\n\n```python\nx = 1\n```\n"

    claim = claims_in(text)[0]

    assert claim.kind is ClaimKind.EXAMPLE
    assert claim.source == "x = 1\n"


def test_a_fence_in_another_language_is_not_an_example():
    assert claims_in("```bash\nls -la\n```\n") == []


def test_backticks_inside_a_fence_are_not_read_as_prose():
    text = "```python\nvalue = `not really a span`\n```\n"

    assert [claim.kind for claim in claims_in(text)] == [ClaimKind.EXAMPLE]


def test_every_claim_carries_its_line():
    claims = claims_in(README_LIKE)

    assert all(claim.line > 0 for claim in claims)
    assert {claim.subject: claim.line for claim in claims}["--strict"] == 7


def test_a_claim_carries_the_nearest_preceding_heading():
    headings = {claim.subject: claim.heading for claim in claims_in(README_LIKE)}

    assert headings["create_app"] == "Title"
    assert headings["--strict"] == "Options"


def test_a_document_with_no_heading_still_yields_claims():
    claims = claims_in("Calls `create_app`.")

    assert [claim.subject for claim in claims] == ["create_app"]
    assert claims[0].heading == ""


def test_an_empty_document_yields_nothing():
    assert claims_in("") == []
