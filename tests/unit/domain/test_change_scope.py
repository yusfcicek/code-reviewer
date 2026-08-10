"""Step 6a — reading a change as a set of names.

The scope is what makes every rule in this level a fact rather than a
resemblance, so it is derived from the diff and from nothing else. A name that
disappeared from the file is a name the repository was responsible for and no
longer is; that is the whole evidence base, and it is available without a
second checkout, a git binding or a call to the forge.
"""

from code_reviewer.domain.documentation import scope_from_diff

REMOVED_FUNCTION = (
    "@@ -10,7 +10,3 @@\n"
    " import os\n"
    "-\n"
    "-def start_app(config):\n"
    '-    return os.environ["REVIEW_LEGACY_MODE"]\n'
    " \n"
    " def create_app(config):\n"
    "     return config\n"
)

RENAMED_FUNCTION = "@@ -1,3 +1,3 @@\n-def start_app(config):\n+def create_app(config):\n     return config\n"

CHANGED_SIGNATURE = (
    "@@ -1,3 +1,3 @@\n-def create_app(config):\n+def create_app(config, worker):\n     return config\n"
)


def test_a_deleted_function_is_removed():
    scope = scope_from_diff(REMOVED_FUNCTION)

    assert "start_app" in scope.removed


def test_a_deleted_function_is_also_touched():
    """Everything removed is also touched; the two sets nest."""
    assert "start_app" in scope_from_diff(REMOVED_FUNCTION).touched


def test_a_surviving_function_is_not_removed():
    assert "create_app" not in scope_from_diff(REMOVED_FUNCTION).removed


def test_a_rename_removes_the_old_name_and_touches_the_new_one():
    scope = scope_from_diff(RENAMED_FUNCTION)

    assert scope.removed == frozenset({"start_app"})
    assert "create_app" in scope.touched


def test_a_changed_signature_touches_without_removing():
    scope = scope_from_diff(CHANGED_SIGNATURE)

    assert scope.removed == frozenset()
    assert "create_app" in scope.touched


def test_a_deleted_class_is_removed():
    diff = "@@ -1,2 +1,1 @@\n-class Renderer:\n-    pass\n"

    assert "Renderer" in scope_from_diff(diff).removed


def test_a_deleted_constant_is_removed():
    diff = "@@ -1,2 +1,1 @@\n-MAX_LINES = 12\n"

    assert "MAX_LINES" in scope_from_diff(diff).removed


def test_a_deleted_option_literal_is_removed():
    diff = '@@ -1,2 +1,1 @@\n-    parser.add_argument("--legacy")\n'

    assert "--legacy" in scope_from_diff(diff).removed


def test_a_deleted_environment_literal_is_removed():
    diff = '@@ -1,2 +1,1 @@\n-    mode = os.environ["REVIEW_LEGACY_MODE"]\n'

    assert "REVIEW_LEGACY_MODE" in scope_from_diff(diff).removed


def test_a_line_that_moved_removes_nothing():
    """Reordered code is not deleted code."""
    diff = "@@ -1,4 +1,4 @@\n-def a():\n-    pass\n+def a():\n+    pass\n"

    assert scope_from_diff(diff).removed == frozenset()


def test_context_lines_contribute_nothing():
    diff = "@@ -1,3 +1,3 @@\n def untouched(config):\n     return config\n"

    scope = scope_from_diff(diff)

    assert scope.removed == frozenset()
    assert scope.touched == frozenset()


def test_the_file_header_is_not_read_as_a_change():
    """`--- a/app.py` starts with a minus and is not a deleted line."""
    diff = "--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n-def gone():\n"

    assert scope_from_diff(diff).removed == frozenset({"gone"})


def test_an_empty_diff_scopes_nothing():
    scope = scope_from_diff("")

    assert scope.removed == frozenset()
    assert scope.touched == frozenset()
    assert not scope.document_changed


def test_scopes_merge():
    first = scope_from_diff(RENAMED_FUNCTION)
    second = scope_from_diff("@@ -1,1 +1,0 @@\n-MAX_LINES = 12\n")

    merged = first.merged_with(second)

    assert merged.removed == frozenset({"start_app", "MAX_LINES"})
    assert "create_app" in merged.touched


def test_merging_keeps_a_document_change():
    from code_reviewer.domain.documentation import ChangeScope

    merged = ChangeScope(document_changed=True).merged_with(ChangeScope())

    assert merged.document_changed
