from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from project_context import context_path, load_project_context, write_project_context


class ProjectContextTests(unittest.TestCase):
    def test_write_load_and_redact_sensitive_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo"
            root.mkdir()
            result = write_project_context(
                root,
                {
                    "project": {"name": "Demo", "purpose": "测试项目认知"},
                    "folders": [{"path": "docs", "role": "项目资料"}],
                    "known_facts": [{"fact": "当前功能清单为4.3"}],
                    "connection": {"api_key": "should-not-persist", "endpoint": "https://example.invalid"},
                },
                generator={"type": "coding_agent", "name": "codex"},
            )

            self.assertTrue(result["present"])
            self.assertTrue(result["valid"])
            data = result["data"]
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["project"]["name"], "Demo")
            self.assertEqual(data["generator"]["name"], "codex")
            self.assertEqual(data["connection"]["api_key"], "<redacted>")
            self.assertNotIn("should-not-persist", context_path(root).read_text(encoding="utf-8"))

            loaded = load_project_context(root)
            self.assertEqual(loaded["data"]["known_facts"][0]["fact"], "当前功能清单为4.3")

    def test_malformed_context_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo"
            path = context_path(root)
            path.parent.mkdir(parents=True)
            path.write_text("schema_version: [broken", encoding="utf-8")

            result = load_project_context(root)
            self.assertTrue(result["present"])
            self.assertFalse(result["valid"])
            self.assertIsNotNone(result["error"])
            self.assertIsNone(result["data"])


if __name__ == "__main__":
    unittest.main()
