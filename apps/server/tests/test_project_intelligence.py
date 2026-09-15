from __future__ import annotations

import unittest

from project_intelligence import build_project_intelligence, search_project_intelligence


def snapshot(
    *,
    snapshot_id: int = 1,
    observed_at: str = "2026-09-15T08:00:00+00:00",
    files: list[dict] | None = None,
    analysis_items: list[dict] | None = None,
    context: dict | None = None,
    search_items: list[dict] | None = None,
    workspace_name: str = "demo",
    user_id: str = "cyh",
    device_id: str = "mac-1",
) -> dict:
    return {
        "id": snapshot_id,
        "project_id": "demo",
        "project_name": "Demo",
        "user_id": user_id,
        "device_id": device_id,
        "workspace_name": workspace_name,
        "observed_at": observed_at,
        "payload": {
            "files": {"files": files or []},
            "analysis": {"enabled": True, "items": analysis_items or [], "current_project_memory": {}},
            "project_intelligence": {
                "context": {
                    "present": bool(context),
                    "valid": True if context else None,
                    "modified_at": observed_at if context else None,
                    "data": context,
                },
                "search_index": {"enabled": bool(search_items), "items": search_items or []},
            },
        },
    }


class ProjectIntelligenceTests(unittest.TestCase):
    def test_agent_context_current_file_beats_newer_filesystem_mtime(self) -> None:
        context = {
            "schema_version": 1,
            "generated_at": "2026-09-15T08:00:00+00:00",
            "document_series": [
                {
                    "series_id": "feature-list",
                    "name": "功能清单",
                    "known_files": ["docs/功能清单4.1.xlsx", "docs/功能清单4.3.xlsx"],
                    "current_file": "docs/功能清单4.1.xlsx",
                    "purpose": "记录当前功能范围",
                }
            ],
        }
        files = [
            {
                "path": "docs/功能清单4.1.xlsx",
                "sha256": "a",
                "suffix": ".xlsx",
                "modified_at": "2026-09-01T08:00:00+00:00",
            },
            {
                "path": "docs/功能清单4.3.xlsx",
                "sha256": "b",
                "suffix": ".xlsx",
                "modified_at": "2026-09-14T08:00:00+00:00",
            },
        ]
        result = build_project_intelligence([snapshot(files=files, context=context)])
        series = next(item for item in result["series"] if item["series_id"] == "context:feature-list")
        self.assertEqual(series["current_path"], "docs/功能清单4.1.xlsx")
        current = next(item for item in result["materials"] if item["path"] == "docs/功能清单4.1.xlsx")
        newer = next(item for item in result["materials"] if item["path"] == "docs/功能清单4.3.xlsx")
        self.assertEqual(current["version_status"], "current")
        self.assertEqual(newer["version_status"], "historical")
        self.assertIn("开发侧 AI 明确认知指定当前文件", series["evidence"])

    def test_weekly_reports_are_periods_not_invalid_versions(self) -> None:
        files = [
            {"path": "周报/项目周报第8期.docx", "sha256": "w8", "modified_at": "2026-09-01T08:00:00+00:00"},
            {"path": "周报/项目周报第9期.docx", "sha256": "w9", "modified_at": "2026-09-08T08:00:00+00:00"},
        ]
        result = build_project_intelligence([snapshot(files=files)])
        statuses = {item["name"]: item["version_status"] for item in result["materials"]}
        self.assertEqual(statuses["项目周报第9期.docx"], "latest_period")
        self.assertEqual(statuses["项目周报第8期.docx"], "period_history")
        self.assertTrue(any(relation["relation"] == "periodic_snapshot" for relation in result["relations"]))

    def test_contract_supplement_does_not_replace_main_contract(self) -> None:
        files = [
            {"path": "商务/项目合同.pdf", "sha256": "c1", "modified_at": "2026-05-01T08:00:00+00:00"},
            {"path": "商务/合同补充协议2.pdf", "sha256": "c2", "modified_at": "2026-09-10T08:00:00+00:00"},
        ]
        result = build_project_intelligence([snapshot(files=files)])
        main = next(item for item in result["materials"] if item["path"] == "商务/项目合同.pdf")
        supplement = next(item for item in result["materials"] if item["path"] == "商务/合同补充协议2.pdf")
        self.assertIn(main["version_status"], {"primary", "single"})
        self.assertIn(supplement["version_status"], {"active_related", "single"})
        self.assertTrue(
            any(
                relation["relation"] == "supplements"
                and relation["from"] == supplement["path"]
                and relation["to"] == main["path"]
                for relation in result["relations"]
            )
        )

    def test_duplicate_content_and_workspace_divergence_are_visible(self) -> None:
        first = snapshot(
            observed_at="2026-09-15T07:00:00+00:00",
            files=[
                {"path": "docs/A.docx", "sha256": "a-old", "modified_at": "2026-09-10T08:00:00+00:00"},
                {"path": "docs/B.docx", "sha256": "duplicate", "modified_at": "2026-09-10T08:00:00+00:00"},
                {"path": "docs/B副本.docx", "sha256": "duplicate", "modified_at": "2026-09-10T08:00:00+00:00"},
            ],
        )
        second = snapshot(
            snapshot_id=2,
            observed_at="2026-09-15T08:00:00+00:00",
            workspace_name="demo-copy",
            user_id="ryj",
            device_id="mac-2",
            files=[
                {"path": "docs/A.docx", "sha256": "a-new", "modified_at": "2026-09-11T08:00:00+00:00"},
            ],
        )
        result = build_project_intelligence([first, second])
        issue_types = {item["type"] for item in result["health"]["issues"]}
        self.assertIn("duplicate_content", issue_types)
        self.assertIn("workspace_divergence", issue_types)

    def test_content_keyword_search_returns_exact_xlsx_locator(self) -> None:
        files = [
            {"path": "资料/功能清单4.3.xlsx", "sha256": "f1", "modified_at": "2026-09-14T08:00:00+00:00"},
        ]
        analysis_items = [
            {
                "path": "资料/功能清单4.3.xlsx",
                "sha256": "f1",
                "role": "document",
                "status": "analyzed",
                "analysis": {"summary": "当前功能清单", "facts": []},
            }
        ]
        search_items = [
            {
                "path": "资料/功能清单4.3.xlsx",
                "category": "documents",
                "segments": [
                    {
                        "text": "模型切换 | 支持修改独立切换密钥",
                        "locator": "功能清单!第32行",
                        "location_type": "sheet_row",
                        "sheet": "功能清单",
                        "row": 32,
                    }
                ],
            }
        ]
        intelligence = build_project_intelligence(
            [snapshot(files=files, analysis_items=analysis_items, search_items=search_items)],
            include_search_index=True,
        )
        result = search_project_intelligence(intelligence, "独立切换密钥")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["locator"], "功能清单!第32行")
        self.assertIn("正文", result["results"][0]["matched_fields"])

    def test_recent_change_compares_latest_two_workspace_snapshots(self) -> None:
        older = snapshot(
            snapshot_id=1,
            observed_at="2026-09-14T08:00:00+00:00",
            files=[{"path": "docs/需求.docx", "sha256": "old", "modified_at": "2026-09-14T07:00:00+00:00"}],
        )
        newer = snapshot(
            snapshot_id=2,
            observed_at="2026-09-15T08:00:00+00:00",
            files=[{"path": "docs/需求.docx", "sha256": "new", "modified_at": "2026-09-15T07:00:00+00:00"}],
        )
        result = build_project_intelligence([newer], [newer, older])
        change = next(item for item in result["recent_changes"] if item["path"] == "docs/需求.docx")
        self.assertEqual(change["change_type"], "modified")


if __name__ == "__main__":
    unittest.main()
