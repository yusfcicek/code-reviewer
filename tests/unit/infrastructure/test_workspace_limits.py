"""The three limits that sit on top of confinement.

Confinement answers "can it leave the repository". These answer the questions
it does not (finding G-05):

- *should it read this file, inside the root* — the deny-list;
- *how much may it read in total* — the budget, because an exfiltration is a
  thousand ordinary reads, not one oversized one;
- *did it try* — the audit log, because a refused read is the loudest available
  signal that the diff contains an injection.

Confinement's own tests live in ``test_workspace.py`` and are untouched: that
behaviour is not what changes here.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar

from code_reviewer.infrastructure.tools.workspace import OutsideWorkspaceError, Workspace


class _Repo:
    """A checkout containing the things a CI runner's checkout contains."""

    FILES: ClassVar[dict[str, str]] = {
        "src/app.py": "value = 1\n",
        "README.md": "# project\n",
        ".env": "GITLAB_TOKEN=glpat-realtoken\n",
        ".env.production": "SECRET=y\n",
        ".netrc": "machine example.com\n",
        "credentials": "aws creds\n",
        "config/.env": "NESTED=1\n",
        "keys/id_rsa": "-----BEGIN OPENSSH PRIVATE KEY-----\n",
        "keys/server.key": "-----BEGIN PRIVATE KEY-----\n",
        "certs/client.p12": "binary-ish\n",
        "certs/chain.pem": "-----BEGIN CERTIFICATE-----\n",
        ".git/config": "[core]\n",
    }

    def __enter__(self):
        self._temporary = TemporaryDirectory()
        self.root = Path(self._temporary.name) / "repo"
        for relative, content in self.FILES.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return self

    def __exit__(self, *exc_info):
        self._temporary.cleanup()
        return False


class TestDenyList(unittest.TestCase):
    """Inside the root is not the same as fit to read."""

    DENIED = (
        ".env",
        ".env.production",
        ".netrc",
        "credentials",
        "config/.env",
        "keys/id_rsa",
        "keys/server.key",
        "certs/client.p12",
        "certs/chain.pem",
        ".git/config",
    )

    def test_a_credential_bearing_file_is_refused(self):
        with _Repo() as repo:
            workspace = Workspace(repo.root)

            for relative in self.DENIED:
                with self.subTest(path=relative):
                    with self.assertRaises(OutsideWorkspaceError):
                        workspace.read(relative)

    def test_the_refusal_says_it_was_the_name_and_not_the_location(self):
        with _Repo() as repo:
            with self.assertRaises(OutsideWorkspaceError) as caught:
                Workspace(repo.root).read(".env")

            self.assertIn("sensitive", str(caught.exception).lower())

    def test_an_ordinary_file_is_still_read(self):
        with _Repo() as repo:
            self.assertIn("value = 1", Workspace(repo.root).read("src/app.py"))

    def test_the_check_is_case_insensitive(self):
        """A case-insensitive filesystem would otherwise route around the list."""
        with _Repo() as repo:
            (repo.root / "ID_RSA").write_text("x", encoding="utf-8")

            with self.assertRaises(OutsideWorkspaceError):
                Workspace(repo.root).read("ID_RSA")


class TestListingHidesDeniedEntries(unittest.TestCase):
    def test_a_denied_entry_is_omitted_rather_than_named(self):
        """Naming it in a listing tells the model exactly what to ask for next."""
        with _Repo() as repo:
            entries = Workspace(repo.root).entries(".")

            self.assertIn("src/app.py", entries)
            self.assertNotIn(".env", entries)
            self.assertNotIn("keys/id_rsa", entries)

    def test_nothing_under_git_is_listed(self):
        with _Repo() as repo:
            self.assertEqual([e for e in Workspace(repo.root).entries(".") if ".git" in e], [])


class TestReadBudget(unittest.TestCase):
    def test_reads_are_refused_once_the_total_is_exhausted(self):
        with _Repo() as repo:
            workspace = Workspace(repo.root, total_read_budget_bytes=12)

            workspace.read("src/app.py")  # 10 bytes, inside the budget

            with self.assertRaises(OutsideWorkspaceError) as caught:
                workspace.read("README.md")

            self.assertIn("budget", str(caught.exception).lower())

    def test_the_running_total_matches_what_was_read(self):
        with _Repo() as repo:
            workspace = Workspace(repo.root)

            workspace.read("src/app.py")

            self.assertEqual(workspace.bytes_read, len("value = 1\n"))

    def test_a_truncated_file_only_spends_what_it_returned(self):
        with _Repo() as repo:
            (repo.root / "big.txt").write_text("x" * 5000, encoding="utf-8")
            workspace = Workspace(repo.root, max_file_bytes=100)

            workspace.read("big.txt")

            self.assertEqual(workspace.bytes_read, 100)

    def test_the_default_budget_does_not_get_in_the_way_of_a_normal_review(self):
        with _Repo() as repo:
            workspace = Workspace(repo.root)

            for _ in range(50):
                workspace.read("src/app.py")

            self.assertIn("value = 1", workspace.read("src/app.py"))


class TestAuditLog(unittest.TestCase):
    def test_an_allowed_read_is_recorded_with_its_size(self):
        with _Repo() as repo:
            workspace = Workspace(repo.root)

            workspace.read("src/app.py")

            record = workspace.audit_log[-1]
            self.assertTrue(record.allowed)
            self.assertEqual(record.size, len("value = 1\n"))

    def test_a_refusal_is_recorded_with_its_reason(self):
        with _Repo() as repo:
            workspace = Workspace(repo.root)

            with self.assertRaises(OutsideWorkspaceError):
                workspace.read(".env")

            record = workspace.audit_log[-1]
            self.assertFalse(record.allowed)
            self.assertIn(".env", record.path)
            self.assertTrue(record.reason)

    def test_violations_are_only_the_refusals(self):
        with _Repo() as repo:
            workspace = Workspace(repo.root)
            workspace.read("src/app.py")

            with self.assertRaises(OutsideWorkspaceError):
                workspace.read("../outside.txt")

            self.assertEqual(len(workspace.violations), 1)
            self.assertEqual(len(workspace.audit_log), 2)

    def test_leaving_the_root_is_recorded_too(self):
        """The loudest signal there is; it must not be the one that goes unlogged."""
        with _Repo() as repo:
            workspace = Workspace(repo.root)

            with self.assertRaises(OutsideWorkspaceError):
                workspace.read("/etc/passwd")

            self.assertEqual(len(workspace.violations), 1)


class TestMalformedPaths(unittest.TestCase):
    def test_a_path_containing_a_nul_byte_is_denied_rather_than_raised(self):
        """`Path.resolve()` raises ValueError on a NUL byte, not OSError.

        Letting that escape means the access is neither refused nor recorded:
        it leaves through a door the workspace does not know it has.
        """
        with _Repo() as repo:
            workspace = Workspace(repo.root)

            with self.assertRaises(OutsideWorkspaceError):
                workspace.resolve("src/\x00app.py")

            self.assertEqual(len(workspace.violations), 1)

    def test_an_empty_path_is_denied(self):
        with _Repo() as repo:
            workspace = Workspace(repo.root)

            with self.assertRaises(OutsideWorkspaceError):
                workspace.resolve("   ")


if __name__ == "__main__":
    unittest.main()


class TestLimitsAreOperatorSettable(unittest.TestCase):
    """The right budget depends on the repository, which is deployment knowledge.

    Both fall back rather than raise on a bad value: a review tool must not
    fail someone's pipeline over a typo in an environment variable, and the
    fallback is the documented default rather than "no limit".
    """

    def test_the_total_budget_is_read_from_the_environment(self):
        from code_reviewer.infrastructure.tools.workspace import total_read_budget_from_env

        self.assertEqual(total_read_budget_from_env({"WORKSPACE_TOTAL_READ_BUDGET": "4096"}), 4096)

    def test_the_per_file_cap_is_read_from_the_environment(self):
        from code_reviewer.infrastructure.tools.workspace import max_file_bytes_from_env

        self.assertEqual(max_file_bytes_from_env({"WORKSPACE_MAX_FILE_BYTES": "512"}), 512)

    def test_an_unset_variable_yields_the_default(self):
        from code_reviewer.infrastructure.tools.workspace import (
            DEFAULT_MAX_FILE_BYTES,
            DEFAULT_TOTAL_READ_BUDGET_BYTES,
            max_file_bytes_from_env,
            total_read_budget_from_env,
        )

        self.assertEqual(total_read_budget_from_env({}), DEFAULT_TOTAL_READ_BUDGET_BYTES)
        self.assertEqual(max_file_bytes_from_env({}), DEFAULT_MAX_FILE_BYTES)

    def test_a_nonsense_value_yields_the_default_rather_than_no_limit(self):
        from code_reviewer.infrastructure.tools.workspace import (
            DEFAULT_TOTAL_READ_BUDGET_BYTES,
            total_read_budget_from_env,
        )

        for value in ("plenty", "-1", "0", ""):
            with self.subTest(value=value):
                self.assertEqual(
                    total_read_budget_from_env({"WORKSPACE_TOTAL_READ_BUDGET": value}),
                    DEFAULT_TOTAL_READ_BUDGET_BYTES,
                )

    def test_a_workspace_built_from_the_environment_honours_them(self):
        from code_reviewer.infrastructure.tools.workspace import Workspace

        with _Repo() as repo:
            workspace = Workspace.from_environment(
                repo.root, environment={"WORKSPACE_TOTAL_READ_BUDGET": "5"}
            )

            with self.assertRaises(OutsideWorkspaceError):
                workspace.read("src/app.py")
