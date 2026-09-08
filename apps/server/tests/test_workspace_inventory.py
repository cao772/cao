from workspace_inventory import build_workspace_inventory


def test_workspace_inventory_flags_copies_archives_and_pending_parsers():
    files = [
        {"path": "低电压项目 8.12问题反馈表.xlsx", "size": 803_000, "suffix": ".xlsx"},
        {"path": "未来发展规划相关问题及建议.docx", "size": 19_000, "suffix": ".docx"},
        {"path": "南方电网定额【2026】6号.pdf", "size": 4_100_000, "suffix": ".pdf"},
        {"path": "2026年低电压项目清单.csv", "size": 307_000, "suffix": ".csv"},
        {"path": "历史定级标准.doc", "size": 700_000, "suffix": ".doc"},
        {"path": "alignment_handoff_pack/readme.md", "size": 1200, "suffix": ".md"},
        {"path": "alignment_handoff_pack.zip", "size": 443_000, "suffix": ".zip"},
        {"path": "algorithm-ryj 7_副本/readme.md", "size": 1200, "suffix": ".md"},
    ]

    result = build_workspace_inventory(files)

    assert result["file_count"] == len(files)
    assert result["suffix_counts"][".xlsx"] == 1
    assert {item["suffix"] for item in result["pending_parsers"]} == {".doc"}
    assert result["content_parser_ready_count"] == 6
    assert result["packaged_duplicates"] == [
        {"archive": "alignment_handoff_pack.zip", "folder": "alignment_handoff_pack"}
    ]
    assert "algorithm-ryj 7_副本/readme.md" in result["copy_like_paths"]
