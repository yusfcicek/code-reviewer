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
    from code_reviewer.domain.fix_recipes import RECIPES

    for rule_id in RECIPES:
        namespace, _, name = rule_id.partition(".")
        assert namespace == "SAST"
        assert name.isupper()


def test_a_recipe_that_raises_costs_only_its_own_suggestion(monkeypatch):
    from code_reviewer.domain import fix_recipes as recipes

    def explode(finding, lines):
        raise RuntimeError("the recipe exploded")

    monkeypatch.setitem(recipes.RECIPES, "SAST.WEAK_CRYPTO", explode)

    assert suggest(_finding("SAST.WEAK_CRYPTO", 5), CRYPTO) is None
