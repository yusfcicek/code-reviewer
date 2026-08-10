"""Step 2 — three deterministic edits, and everything they decline.

The refusals are the level. A recipe that guesses produces a button that
breaks a build, and one broken button costs every future suggestion its
credibility.
"""

from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.fix_recipes import recipe_for, suggest
from code_reviewer.domain.severity import Severity

CRYPTO = "import hashlib\n\n\ndef digest(value):\n    return hashlib.md5(value).hexdigest()\n"
YAML_SOURCE = "import yaml\n\n\ndef read(text):\n    return yaml.load(text)\n"
SECRET = 'import os\n\nAPI_KEY = "sk_live_9f8a7b6c5d4e3f2a1b0c9d8e"\n'
SECRET_WITHOUT_OS = 'API_KEY = "sk_live_9f8a7b6c5d4e3f2a1b0c9d8e"\n'


def _finding(rule: str, line: int) -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=Severity.MEDIUM,
        file_path="src/subject.py",
        line_number=line,
        title="Something",
        description="",
        remediation="",
        rule_id=rule,
    )


# -- md5 to sha256 -----------------------------------------------------------


def test_the_weak_crypto_recipe_replaces_the_digest():
    suggestion = suggest(_finding("SAST.WEAK_CRYPTO", 5), CRYPTO)

    assert suggestion is not None
    assert suggestion.replacement == ("    return hashlib.sha256(value).hexdigest()",)
    assert suggestion.recipe == "md5-to-sha256"


def test_sha1_is_replaced_too():
    source = CRYPTO.replace("md5", "sha1")

    suggestion = suggest(_finding("SAST.WEAK_CRYPTO", 5), source)

    assert suggestion.replacement == ("    return hashlib.sha256(value).hexdigest()",)


def test_a_line_that_is_already_sha256_yields_nothing():
    """An edit that changes nothing is noise in a merge request."""
    source = CRYPTO.replace("md5", "sha256")

    assert suggest(_finding("SAST.WEAK_CRYPTO", 5), source) is None


def test_a_finding_pointing_at_the_wrong_line_yields_nothing():
    """A recipe that searched the file for its pattern would edit a line the
    finding never claimed anything about."""
    assert suggest(_finding("SAST.WEAK_CRYPTO", 1), CRYPTO) is None


def test_a_finding_past_the_end_of_the_file_yields_nothing():
    assert suggest(_finding("SAST.WEAK_CRYPTO", 99), CRYPTO) is None


# -- yaml.load to yaml.safe_load ---------------------------------------------


def test_the_deserialisation_recipe_makes_the_load_safe():
    suggestion = suggest(_finding("SAST.INSECURE_DESERIALIZATION", 5), YAML_SOURCE)

    assert suggestion.replacement == ("    return yaml.safe_load(text)",)
    assert suggestion.recipe == "yaml-load-to-safe-load"


def test_a_load_that_already_names_a_loader_yields_nothing():
    """The analyzer does not report it, and a recipe that fires anyway would
    rewrite correct code."""
    source = YAML_SOURCE.replace("yaml.load(text)", "yaml.load(text, Loader=yaml.SafeLoader)")

    assert suggest(_finding("SAST.INSECURE_DESERIALIZATION", 5), source) is None


def test_a_pickle_load_yields_nothing():
    """Same rule, no safe equivalent. Declining is the honest answer: there is
    no one-line change that makes `pickle.loads` safe on untrusted data."""
    source = "import pickle\n\n\ndef read(data):\n    return pickle.loads(data)\n"

    assert suggest(_finding("SAST.INSECURE_DESERIALIZATION", 5), source) is None


# -- a literal to the environment --------------------------------------------


def test_the_secret_recipe_moves_the_value_to_the_environment():
    suggestion = suggest(_finding("SAST.HARDCODED_SECRET", 3), SECRET)

    assert suggestion.replacement == ('API_KEY = os.environ["API_KEY"]',)
    assert suggestion.recipe == "secret-to-environment"


def test_the_secret_recipe_declines_without_an_os_import():
    """A suggestion that leaves the file failing to import is a suggestion
    that wastes somebody's afternoon (contract C-4)."""
    assert suggest(_finding("SAST.HARDCODED_SECRET", 1), SECRET_WITHOUT_OS) is None


def test_the_secret_recipe_declines_a_line_that_is_not_an_assignment():
    source = 'import os\n\nrequests.get(url, headers={"Authorization": "Bearer sk_live_abc"})\n'

    assert suggest(_finding("SAST.HARDCODED_SECRET", 3), source) is None


def test_the_secret_recipe_keeps_the_indentation():
    source = 'import os\n\n\nclass Client:\n    API_KEY = "sk_live_9f8a7b6c5d4e"\n'

    suggestion = suggest(_finding("SAST.HARDCODED_SECRET", 5), source)

    assert suggestion.replacement == ('    API_KEY = os.environ["API_KEY"]',)


def test_the_replacement_never_carries_the_secret_itself():
    suggestion = suggest(_finding("SAST.HARDCODED_SECRET", 3), SECRET)

    assert "sk_live" not in "".join(suggestion.replacement)


# -- the registry ------------------------------------------------------------


def test_a_rule_with_no_recipe_has_none():
    assert recipe_for("QUALITY.SRP") is None
    assert suggest(_finding("QUALITY.SRP", 1), CRYPTO) is None


def test_every_registered_rule_names_a_rule_the_suite_can_emit():
    """A recipe for a rule id nobody produces is dead code that reads as a
    feature."""
    # Level 26 added a QUALITY recipe, so the namespace is checked against what
    # the attribution table registers rather than against one hard-coded name.
    from code_reviewer.application.governance import PRODUCERS
    from code_reviewer.domain.fix_recipes import RECIPES

    for rule_id in RECIPES:
        namespace, _, name = rule_id.partition(".")
        assert namespace in PRODUCERS, rule_id
        assert name.isupper()


def test_a_recipe_that_raises_costs_only_its_own_suggestion(monkeypatch):
    from code_reviewer.domain import fix_recipes as recipes

    def explode(finding, lines):
        raise RuntimeError("the recipe exploded")

    monkeypatch.setitem(recipes.RECIPES, "SAST.WEAK_CRYPTO", explode)

    assert suggest(_finding("SAST.WEAK_CRYPTO", 5), CRYPTO) is None


# -- Level 26: the recipes the one-range format could not express ------------

INSECURE_RANDOM = "import random\n\n\ndef token():\n    return random.random()\n"
INSECURE_HTTP = 'ENDPOINT = "http://api.internal/v1"\n'
BARE_EXCEPT = "def read(path):\n    try:\n        return open(path)\n    except:\n        return None\n"
RERAISE = "def read(path):\n    try:\n        return open(path)\n    except:\n        raise\n"
FILE_OPERATION = "def read(path):\n    return open(path)\n"


def _applied(source, rule, line):
    suggestion = suggest(_finding(rule, line), source)
    return None if suggestion is None else suggestion.applied_to(source)


class TestInsecureRandom:
    """AC-6 — the two-part edit the format change exists for."""

    def test_it_replaces_the_call(self):
        assert "secrets.SystemRandom()" in _applied(INSECURE_RANDOM, "SAST.INSECURE_RANDOM", 5)

    def test_it_adds_the_import(self):
        assert "import secrets" in _applied(INSECURE_RANDOM, "SAST.INSECURE_RANDOM", 5)

    def test_the_result_still_parses(self):
        import ast

        ast.parse(_applied(INSECURE_RANDOM, "SAST.INSECURE_RANDOM", 5))

    def test_the_import_is_not_added_twice(self):
        """AC-7."""
        source = "import random\nimport secrets\n\n\ndef token():\n    return random.random()\n"

        assert _applied(source, "SAST.INSECURE_RANDOM", 6).count("import secrets") == 1

    def test_it_declines_a_line_without_the_call(self):
        """AC-13."""
        assert suggest(_finding("SAST.INSECURE_RANDOM", 1), INSECURE_RANDOM) is None

    def test_it_declines_code_already_using_secrets(self):
        """AC-14."""
        source = "import secrets\n\n\ndef token():\n    return secrets.SystemRandom().random()\n"

        assert suggest(_finding("SAST.INSECURE_RANDOM", 5), source) is None


class TestInsecureHttp:
    def test_it_upgrades_a_literal_scheme(self):
        """AC-10."""
        assert 'https://api.internal/v1"' in _applied(INSECURE_HTTP, "SAST.INSECURE_HTTP", 1)

    def test_it_declines_a_url_built_from_a_variable(self):
        """Upgrading a scheme it cannot see is a guess."""
        source = 'ENDPOINT = scheme + "://api.internal/v1"\n'

        assert suggest(_finding("SAST.INSECURE_HTTP", 1), source) is None

    def test_it_declines_localhost(self):
        """A loopback URL over http is not a defect, and rewriting one breaks a
        development setup for no gain."""
        for host in ("http://localhost:8080", "http://127.0.0.1:9000"):
            assert suggest(_finding("SAST.INSECURE_HTTP", 1), f'URL = "{host}"\n') is None, host

    def test_it_declines_a_line_without_a_url(self):
        assert suggest(_finding("SAST.INSECURE_HTTP", 1), "x = 1\n") is None

    def test_it_declines_a_url_already_https(self):
        assert suggest(_finding("SAST.INSECURE_HTTP", 1), 'URL = "https://api/v1"\n') is None


class TestBareExcept:
    def test_it_names_the_exception(self):
        """AC-11."""
        assert "except Exception:" in _applied(BARE_EXCEPT, "QUALITY.ERROR_HANDLING", 4)

    def test_it_keeps_the_indentation(self):
        applied = _applied(BARE_EXCEPT, "QUALITY.ERROR_HANDLING", 4)

        assert "    except Exception:" in applied

    def test_it_declines_a_deliberate_re_raise(self):
        """`except:` followed by a bare `raise` is a deliberate re-raise, and
        naming the exception changes what it catches."""
        assert suggest(_finding("QUALITY.ERROR_HANDLING", 4), RERAISE) is None

    def test_it_declines_an_except_that_already_names_something(self):
        source = BARE_EXCEPT.replace("except:", "except OSError:")

        assert suggest(_finding("QUALITY.ERROR_HANDLING", 4), source) is None

    def test_it_declines_a_line_that_is_not_an_except(self):
        assert suggest(_finding("QUALITY.ERROR_HANDLING", 1), BARE_EXCEPT) is None


class TestFileOperationHasNoRecipe:
    """Removed by the self-review. The rule fires on `chmod(...777)` and on
    `open(..., "w")`; the recipe handled `open(path)` with no mode, which the
    rule never reports, and its edit added `"r"` — the default, so it changed
    nothing (S-02)."""

    def test_the_rule_yields_no_suggestion(self):
        assert suggest(_finding("SAST.INSECURE_FILE_OPERATION", 2), FILE_OPERATION) is None

    def test_it_is_declined_with_a_reason_rather_than_forgotten(self):
        from code_reviewer.domain.fix_recipes import DECLINED

        assert "patterns" in DECLINED["SAST.INSECURE_FILE_OPERATION"]


# -- self-review 26: what the recipes were doing to real lines ---------------


class TestTheExceptRecipeKeepsTheBody:
    """Self-review S-01 — the guard that looked at the wrong lines.

    `except: raise` became `except Exception:` and the `raise` was gone: a
    handler that re-raised now swallows the exception, which is the opposite of
    a fix and invisible in a one-line diff. The guard for exactly this looked at
    the *following* lines, and the single-line form has none.
    """

    def test_a_single_line_re_raise_is_declined(self):
        source = "def r(p):\n    try:\n        return open(p)\n    except: raise\n"

        assert suggest(_finding("QUALITY.ERROR_HANDLING", 4), source) is None

    def test_any_single_line_body_is_declined(self):
        """Not just `raise`: the replacement discarded whatever else was on the
        line, so every single-line body was a deletion."""
        for body in ("raise", "pass", "return None", "log.warning('x')"):
            source = f"def r(p):\n    try:\n        return 1\n    except: {body}\n"

            assert suggest(_finding("QUALITY.ERROR_HANDLING", 4), source) is None, body

    def test_the_ordinary_multi_line_form_still_fires(self):
        source = "def r(p):\n    try:\n        return 1\n    except:\n        return None\n"

        assert "except Exception:" in suggest(_finding("QUALITY.ERROR_HANDLING", 4), source).applied_to(
            source
        )

    def test_a_multi_line_re_raise_is_still_declined(self):
        source = "def r(p):\n    try:\n        return 1\n    except:\n        raise\n"

        assert suggest(_finding("QUALITY.ERROR_HANDLING", 4), source) is None


class TestTheHttpRecipeFixesEveryUrlOrNone:
    """Self-review S-03 — the first of two.

    `re.search` found one. A reviewer clicked, saw a green diff, and had half a
    fix — and the half that remained was the one nobody would look at again,
    because the finding was now closed.
    """

    def test_two_urls_on_one_line_are_both_upgraded(self):
        source = 'PAIR = ("http://a.example", "http://b.example")\n'

        applied = suggest(_finding("SAST.INSECURE_HTTP", 1), source).applied_to(source)

        assert applied.count("https://") == 2
        assert "http://" not in applied.replace("https://", "")

    def test_a_line_mixing_an_upgradable_and_a_loopback_url_is_declined(self):
        """Half a line is the thing this finding is about. Declining is the
        honest answer when one part cannot be touched."""
        source = 'PAIR = ("http://a.example", "http://localhost:8080")\n'

        assert suggest(_finding("SAST.INSECURE_HTTP", 1), source) is None

    def test_one_url_still_works(self):
        source = 'URL = "http://a.example"\n'

        assert "https://a.example" in suggest(_finding("SAST.INSECURE_HTTP", 1), source).applied_to(source)


class TestTheRandomRecipeIgnoresComments:
    """Self-review S-04 — a comment is not code.

    The rule fires on a comment too: its pattern is `random\\.\\w+\\s*\\(` with no
    notion of context, so the finding is not wrong to exist. The recipe was
    wrong to act on it — rewriting a sentence somebody wrote and adding an
    import nothing uses is noise with provenance.
    """

    def test_a_call_inside_a_comment_is_declined(self):
        source = "import random\n# random.random() is not good enough here\nx = 1\n"

        assert suggest(_finding("SAST.INSECURE_RANDOM", 2), source) is None

    def test_a_trailing_comment_after_real_code_still_fires(self):
        source = "import random\n\n\ndef t():\n    return random.random()  # seeded elsewhere\n"

        assert suggest(_finding("SAST.INSECURE_RANDOM", 5), source) is not None

    def test_a_call_inside_a_string_is_declined(self):
        source = 'import random\nDOC = "call random.random() for this"\n'

        assert suggest(_finding("SAST.INSECURE_RANDOM", 2), source) is None


def test_the_file_operation_rule_has_no_recipe():
    """Self-review S-02 — a recipe that answered a question its rule never asks.

    `SAST.INSECURE_FILE_OPERATION` fires on `chmod(…777)` and on
    `open(…, "w")`. The recipe handled `open(path)` with no mode, which the rule
    never reports, and added `"r"`, which is the default and changes nothing.
    Removed, and declined on the record with that reason.
    """
    from code_reviewer.domain.fix_recipes import DECLINED, RECIPES

    assert "SAST.INSECURE_FILE_OPERATION" not in RECIPES
    assert "never reports" in DECLINED["SAST.INSECURE_FILE_OPERATION"]
