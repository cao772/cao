import sqlite3

import portfolio_search
from portfolio_search import rank_search_results


def test_global_search_keeps_one_result_per_source_and_ranks_newer_ties():
    hits = [
        {"project_id": "p1", "source_type": "material", "source_path": "docs/report.md", "score": 80,
         "source_time": "2026-09-01T00:00:00Z"},
        {"project_id": "p1", "source_type": "material", "source_path": "docs/report.md", "score": 80,
         "source_time": "2026-09-20T00:00:00Z"},
        {"project_id": "p2", "source_type": "material", "source_path": "docs/report.md", "score": 80,
         "source_time": "2026-09-10T00:00:00Z"},
        {"project_id": "p1", "source_type": "conversation", "source_id": 12, "score": 55,
         "source_time": "2026-09-28T00:00:00Z"},
    ]

    ranked = rank_search_results(hits, 20)
    assert len(ranked) == 3
    assert ranked[0]["source_time"] == "2026-09-20T00:00:00Z"
    assert ranked[1]["project_id"] == "p2"
    assert ranked[2]["source_type"] == "conversation"


def test_search_still_works_without_unmerged_conversation_table(monkeypatch):
    conn = sqlite3.connect(":memory:")
    monkeypatch.setattr(portfolio_search.main_module, "get_db", lambda: conn)
    assert portfolio_search._search_conversations("p1", "框架") == []
