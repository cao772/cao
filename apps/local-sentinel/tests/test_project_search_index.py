from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from project_search_index import build_project_search_index


class ProjectSearchIndexTests(unittest.TestCase):
    def _manifest(self, mode: str = "local_analysis") -> dict:
        return {
            "project": {"id": "demo", "name": "Demo"},
            "paths": {
                "documents": ["docs"],
                "tests": [],
                "outputs": [],
                "code": ["code"],
            },
            "security": {"mode": mode},
            "analysis": {
                "enabled": True,
                "include": ["documents", "code"],
                "search_index_enabled": True,
                "search_index_max_items": 20,
            },
        }

    def test_xlsx_locator_and_code_body_is_not_indexed(self) -> None:
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo"
            (root / "docs").mkdir(parents=True)
            (root / "code").mkdir(parents=True)
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "功能清单"
            worksheet.append(["功能", "说明"])
            worksheet.append(["模型切换", "支持修改独立切换密钥"])
            workbook.save(root / "docs" / "功能清单4.3.xlsx")
            (root / "code" / "secret_impl.py").write_text(
                "INTERNAL_CODE_BODY = 'must not become searchable material content'",
                encoding="utf-8",
            )

            result = build_project_search_index(root, self._manifest())
            self.assertTrue(result["enabled"])
            self.assertEqual(result["stats"].get("indexed"), 1)
            self.assertEqual(result["stats"].get("code_skipped"), 1)
            item = result["items"][0]
            self.assertEqual(item["path"], "docs/功能清单4.3.xlsx")
            match = next(segment for segment in item["segments"] if "独立切换密钥" in segment["text"])
            self.assertEqual(match["sheet"], "功能清单")
            self.assertEqual(match["row"], 2)
            self.assertEqual(match["locator"], "功能清单!第2行")

    def test_metadata_only_does_not_upload_content_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo"
            (root / "docs").mkdir(parents=True)
            (root / "docs" / "需求.md").write_text("这里有正文关键信息", encoding="utf-8")

            result = build_project_search_index(root, self._manifest("metadata_only"))
            self.assertFalse(result["enabled"])
            self.assertEqual(result["items"], [])


if __name__ == "__main__":
    unittest.main()
