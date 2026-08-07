"""Unit tests for workspace confinement.

The agent's file tools took whatever path the model asked for. A merge request
whose diff contains instructions — a prompt injection — could make the agent
read a file outside the repository and echo it into a public merge-request
comment (finding F-21). The CI runner's environment, deploy keys and other
projects' checkouts are all reachable from there.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from code_reviewer.infrastructure.tools.workspace import OutsideWorkspaceError, Workspace


class _Sandbox:
    """A temporary workspace with a file inside it and one outside."""

    def __enter__(self):
        self._outer = TemporaryDirectory()
        root = Path(self._outer.name) / "repo"
        (root / "src").mkdir(parents=True)
        (root / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
        (Path(self._outer.name) / "secret.txt").write_text("TOP-SECRET\n", encoding="utf-8")
        self.root = root
        return self

    def __exit__(self, *exc_info):
        self._outer.cleanup()
        return False

    @property
    def outside_file(self) -> Path:
        return Path(self._outer.name) / "secret.txt"


class TestResolve(unittest.TestCase):
    def test_a_path_inside_the_workspace_resolves(self):
        with _Sandbox() as sandbox:
            workspace = Workspace(sandbox.root)

            resolved = workspace.resolve("src/app.py")

            self.assertEqual(resolved, (sandbox.root / "src" / "app.py").resolve())

    def test_the_workspace_root_itself_resolves(self):
        with _Sandbox() as sandbox:
            self.assertEqual(Workspace(sandbox.root).resolve("."), sandbox.root.resolve())

    def test_an_absolute_path_outside_is_refused(self):
        with _Sandbox() as sandbox:
            workspace = Workspace(sandbox.root)

            with self.assertRaises(OutsideWorkspaceError):
                workspace.resolve("/etc/passwd")

    def test_traversal_is_refused_after_resolution(self):
        with _Sandbox() as sandbox:
            workspace = Workspace(sandbox.root)

            with self.assertRaises(OutsideWorkspaceError):
                workspace.resolve("../secret.txt")

    def test_deep_traversal_is_refused(self):
        with _Sandbox() as sandbox:
            workspace = Workspace(sandbox.root)

            with self.assertRaises(OutsideWorkspaceError):
                workspace.resolve("src/../../../../etc/passwd")

    def test_a_symlink_pointing_outside_is_refused(self):
        with _Sandbox() as sandbox:
            link = sandbox.root / "escape.txt"
            os.symlink(sandbox.outside_file, link)
            workspace = Workspace(sandbox.root)

            with self.assertRaises(OutsideWorkspaceError):
                workspace.resolve("escape.txt")

    def test_a_sibling_directory_with_a_shared_prefix_is_refused(self):
        """`/tmp/repo-other` must not pass because it starts with `/tmp/repo`."""
        with _Sandbox() as sandbox:
            sibling = sandbox.root.parent / f"{sandbox.root.name}-other"
            sibling.mkdir()
            (sibling / "f.txt").write_text("x", encoding="utf-8")
            workspace = Workspace(sandbox.root)

            with self.assertRaises(OutsideWorkspaceError):
                workspace.resolve(str(sibling / "f.txt"))


class TestRead(unittest.TestCase):
    def test_a_file_inside_the_workspace_is_read(self):
        with _Sandbox() as sandbox:
            self.assertEqual(Workspace(sandbox.root).read("src/app.py"), "value = 1\n")

    def test_a_large_file_is_truncated_with_a_notice(self):
        with _Sandbox() as sandbox:
            big = sandbox.root / "big.py"
            big.write_text("x" * 5000, encoding="utf-8")
            workspace = Workspace(sandbox.root, max_file_bytes=1000)

            content = workspace.read("big.py")

            self.assertLess(len(content), 1500)
            self.assertIn("truncated", content.lower())

    def test_a_missing_file_raises_file_not_found(self):
        with _Sandbox() as sandbox:
            with self.assertRaises(FileNotFoundError):
                Workspace(sandbox.root).read("src/absent.py")

    def test_undecodable_bytes_do_not_raise(self):
        with _Sandbox() as sandbox:
            (sandbox.root / "blob.bin").write_bytes(b"\xff\xfe\x00binary")

            content = Workspace(sandbox.root).read("blob.bin")

            self.assertIsInstance(content, str)


class TestDefaults(unittest.TestCase):
    def test_the_default_root_is_the_working_directory(self):
        self.assertEqual(Workspace().root, Path.cwd().resolve())

    def test_the_root_is_reported_in_the_refusal(self):
        with _Sandbox() as sandbox:
            workspace = Workspace(sandbox.root)

            with self.assertRaises(OutsideWorkspaceError) as caught:
                workspace.resolve("/etc/passwd")

            self.assertIn(str(sandbox.root.resolve()), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
