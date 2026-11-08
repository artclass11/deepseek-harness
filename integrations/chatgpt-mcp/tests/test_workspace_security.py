from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepseek_harness_mcp.security import is_valid_bearer
from deepseek_harness_mcp.workspace import resolve_workspace, validate_session_id


class WorkspaceSecurityTests(unittest.TestCase):
    def test_workspace_defaults_to_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(resolve_workspace("", root), root.resolve())

    def test_workspace_allows_nested_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "project"
            nested.mkdir()
            self.assertEqual(resolve_workspace("project", root), nested.resolve())

    def test_workspace_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "allowed"
            root.mkdir()
            with self.assertRaises(ValueError):
                resolve_workspace("../", root)

    def test_workspace_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "allowed"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            link = root / "escape"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlink creation is unavailable")
            with self.assertRaises(ValueError):
                resolve_workspace("escape", root)

    def test_workspace_rejects_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(FileNotFoundError):
                resolve_workspace("missing", root)

    def test_session_id_grammar(self) -> None:
        self.assertEqual(validate_session_id("session-abc_1"), "session-abc_1")
        for invalid in ("", "../escape", "white space", "a" * 81):
            with self.assertRaises(ValueError):
                validate_session_id(invalid)

    def test_bearer_requires_scheme_and_exact_token(self) -> None:
        self.assertTrue(is_valid_bearer("Bearer abcdef0123456789", "abcdef0123456789"))
        self.assertTrue(is_valid_bearer("bearer abcdef0123456789", "abcdef0123456789"))
        self.assertFalse(is_valid_bearer(None, "abcdef0123456789"))
        self.assertFalse(is_valid_bearer("Basic abcdef0123456789", "abcdef0123456789"))
        self.assertFalse(is_valid_bearer("Bearer wrong", "abcdef0123456789"))
        self.assertFalse(is_valid_bearer("Bearer abcdef0123456789 extra", "abcdef0123456789"))


if __name__ == "__main__":
    unittest.main()
