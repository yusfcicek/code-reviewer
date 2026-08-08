"""A policy file either describes the running configuration or refuses to load.

`block_on_critcal: false` used to be read, not recognised, logged at WARNING
and ignored. The rule stayed on under a name its author believed they had
turned off — and the inverse typo left it on when they meant to disable it.
Either way the file stopped describing the configuration, and the only notice
was a line in a log nobody reads during a green build (finding G-10).

The asymmetry that makes this liveable: **fail closed on content, stay
permissive on absence** (decision D-4). Finding no policy file at all is a
deployment that has not configured one, which is a legitimate state with a
documented default. A file containing `block_on_critcal` is a deployment that
believes something false about itself. Silence is not a claim; a typo is.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from code_reviewer.infrastructure.config.loader import (
    PolicyLoadError,
    ReviewPolicyLoader,
    load_policy,
)


class _PolicyFile:
    """Writes a policy file into a temporary directory and yields its path."""

    def __init__(self, content: str, name: str = "policy.yaml"):
        self.content = content
        self.name = name

    def __enter__(self) -> str:
        self._temporary = TemporaryDirectory()
        path = Path(self._temporary.name) / self.name
        path.write_text(self.content, encoding="utf-8")
        return str(path)

    def __exit__(self, *exc_info):
        self._temporary.cleanup()
        return False


class TestUnrecognisedContentRefusesToLoad(unittest.TestCase):
    def test_an_unknown_key_raises(self):
        with _PolicyFile("security:\n  block_on_critcal: false\n") as path:
            with self.assertRaises(PolicyLoadError) as caught:
                load_policy(path)

        self.assertIn("block_on_critcal", str(caught.exception))

    def test_the_message_names_the_section_and_the_file(self):
        with _PolicyFile("security:\n  block_on_critcal: false\n") as path:
            with self.assertRaises(PolicyLoadError) as caught:
                load_policy(path)

            message = str(caught.exception)
            self.assertIn("security", message)
            self.assertIn(path, message)

    def test_an_unknown_section_raises(self):
        with _PolicyFile("securty:\n  block_on_critical: false\n") as path:
            with self.assertRaises(PolicyLoadError) as caught:
                load_policy(path)

        self.assertIn("securty", str(caught.exception))

    def test_the_message_lists_what_was_expected(self):
        """A refusal that does not say what would have worked is a dead end."""
        with _PolicyFile("securty:\n  x: 1\n") as path:
            with self.assertRaises(PolicyLoadError) as caught:
                load_policy(path)

        self.assertIn("security", str(caught.exception))

    def test_unparseable_yaml_raises(self):
        with _PolicyFile("security:\n  - [unbalanced\n") as path:
            with self.assertRaises(PolicyLoadError):
                load_policy(path)

    def test_a_root_that_is_not_a_mapping_raises(self):
        with _PolicyFile("- just\n- a\n- list\n") as path:
            with self.assertRaises(PolicyLoadError):
                load_policy(path)

    def test_a_section_that_is_not_a_mapping_raises(self):
        with _PolicyFile("security: nonsense\n") as path:
            with self.assertRaises(PolicyLoadError) as caught:
                load_policy(path)

        self.assertIn("security", str(caught.exception))

    def test_a_wrongly_typed_value_raises(self):
        with _PolicyFile("quality:\n  max_class_methods: many\n") as path:
            with self.assertRaises(PolicyLoadError) as caught:
                load_policy(path)

        self.assertIn("max_class_methods", str(caught.exception))

    def test_a_boolean_where_an_integer_belongs_raises(self):
        """`True` is an int in Python. The policy should not inherit that."""
        with _PolicyFile("quality:\n  max_class_methods: true\n") as path:
            with self.assertRaises(PolicyLoadError):
                load_policy(path)

    def test_a_string_where_a_boolean_belongs_raises(self):
        with _PolicyFile('security:\n  block_on_critical: "yes"\n') as path:
            with self.assertRaises(PolicyLoadError):
                load_policy(path)

    def test_a_named_file_that_does_not_exist_raises(self):
        """Naming a file is a claim that it is there."""
        with self.assertRaises(PolicyLoadError) as caught:
            load_policy("/definitely/not/here.yaml")

        self.assertIn("not/here.yaml", str(caught.exception))


class TestValidContentStillLoads(unittest.TestCase):
    def test_a_correct_file_loads(self):
        content = "version: '3.1'\nsecurity:\n  block_on_critical: false\nquality:\n  max_class_methods: 4\n"

        with _PolicyFile(content) as path:
            policy = load_policy(path)

        self.assertEqual(policy.version, "3.1")
        self.assertFalse(policy.security.block_on_critical)
        self.assertEqual(policy.quality.max_class_methods, 4)

    def test_an_empty_section_is_accepted(self):
        """A heading followed only by comments parses as None, and is fine."""
        with _PolicyFile("security:\ncustom_rules:\n") as path:
            self.assertIsNotNone(load_policy(path))

    def test_an_integer_where_a_float_belongs_is_accepted(self):
        with _PolicyFile("gate:\n  quality_score_threshold: 70\n") as path:
            self.assertEqual(load_policy(path).gate.quality_score_threshold, 70)

    def test_a_list_of_patterns_is_accepted(self):
        with _PolicyFile('triage:\n  skip_patterns:\n    - "\\\\.md$"\n') as path:
            self.assertEqual(load_policy(path).triage.skip_patterns, ["\\.md$"])

    def test_custom_rules_are_free_form(self):
        """The one section whose keys are the user's own vocabulary."""
        with _PolicyFile("custom_rules:\n  anything_at_all: 1\n") as path:
            self.assertEqual(load_policy(path).custom_rules["anything_at_all"], 1)


class TestAbsenceIsNotAClaim(unittest.TestCase):
    """Fail closed on content, permissive on absence (decision D-4)."""

    def test_no_policy_file_anywhere_still_loads_the_bundled_default(self):
        with TemporaryDirectory() as empty:
            loader = ReviewPolicyLoader()
            loader.DEFAULT_POLICY_PATHS = [str(Path(empty) / "nothing.yaml")]

            policy = loader.load()

        self.assertIsNotNone(policy)
        self.assertTrue(policy.security.block_on_critical)


class TestTheShippedPolicyIsValid(unittest.TestCase):
    """The default must survive its own validator.

    Otherwise this level turns the shipped configuration into a startup
    failure for every existing deployment, which would be a strange way to
    make a tool safer.
    """

    def test_the_bundled_policy_loads(self):
        path = ReviewPolicyLoader().packaged_policy_path()
        self.assertIsNotNone(path, "the packaged policy file is missing")

        self.assertIsNotNone(load_policy(str(path)))


if __name__ == "__main__":
    unittest.main()
