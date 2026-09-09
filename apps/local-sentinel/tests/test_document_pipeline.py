from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from document_pipeline import analyze_project_files, classify_role


class DocumentPipelineTests(unittest.TestCase):
    def test_role_classification(self) -> None:
        self.assertEqual(classify_role("docs/需求说明.md", "documents"), "requirement")
        self.assertEqual(classify_role("tests/回归测试.xlsx", "tests"), "test_result")

    def test_xlsx_sheet_whitelist_and_truncation(self) -> None:
        from openpyxl import Workbook
        from document_pipeline import parse_xlsx
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "progress.xlsx"
            workbook = Workbook()
            workbook.active.title = "current"
            workbook.active.append(["allowed", "extra column"])
            workbook.active.append(["extra row"])
            workbook.create_sheet("unrelated").append(["must not upload"])
            workbook.save(path)
            text, meta = parse_xlsx(path, 1000, 1, 1, ["current"])
            self.assertIn("allowed", text)
            self.assertNotIn("must not upload", text)
            self.assertTrue(meta["truncated"])
            with self.assertRaises(ValueError):
                parse_xlsx(path, 1000, 10, 10, ["missing"])

    def test_incremental_text_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo"
            state = Path(tmp) / "state"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "需求.md").write_text(
                "# 新需求\n必须支持项目资料增量分析。\n当前阻塞：测试环境未准备。",
                encoding="utf-8",
            )
            manifest = {
                "project": {"id": "demo", "name": "Demo"},
                "paths": {"documents": ["docs"], "tests": [], "outputs": [], "code": []},
                "security": {"mode": "local_analysis"},
                "analysis": {"enabled": True, "use_llm": False},
            }

            first = analyze_project_files(root, manifest, state)
            self.assertTrue(first["enabled"])
            self.assertEqual(first["stats"].get("new_or_changed"), 1)
            fact_types = {
                fact["type"]
                for fact in first["project_memory"]["facts"]
            }
            self.assertIn("requirement", fact_types)
            self.assertIn("blocker", fact_types)

            second = analyze_project_files(root, manifest, state)
            self.assertEqual(second["stats"].get("cached"), 1)
            self.assertIsNone(second["stats"].get("new_or_changed"))


if __name__ == "__main__":
    unittest.main()
