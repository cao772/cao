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


def test_conversation_query_treats_wildcards_as_literals_and_keeps_project_scope(monkeypatch):
    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        db_path = directory + '/search.db'
        with connect() as conn:
            conn.execute('CREATE TABLE conversation_events (id INTEGER, project_id TEXT, conversation_name TEXT, sender TEXT, text TEXT, observed_at TEXT, received_at TEXT)')
            for i, pid, text in [(1, 'p1', '50% env_file'), (2, 'p1', '500 envXfile'), (3, 'p2', '50% env_file')]:
                conn.execute('INSERT INTO conversation_events VALUES (?, ?, ?, ?, ?, ?, ?)', (i, pid, 'authorized', 'owner', text, '2026-10-01', '2026-10-01'))
        monkeypatch.setattr(portfolio_search.main_module, 'get_db', connect)
        assert [row['id'] for row in portfolio_search._search_conversations('p1', '%')] == [1]
        assert [row['id'] for row in portfolio_search._search_conversations('p1', 'env_file')] == [1]
        assert portfolio_search._search_conversations('p1', '   ') == []


def test_rank_zero_limit_is_empty():
    assert rank_search_results([{'source_id': 1}], 0) == []


def test_missing_material_snapshot_does_not_hide_authorized_chat(monkeypatch):
    from fastapi import HTTPException
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE projects (project_id TEXT, project_name TEXT)')
    conn.execute("INSERT INTO projects VALUES ('p1', 'Project')")
    conn.execute('CREATE TABLE conversation_events (id INTEGER, project_id TEXT, conversation_name TEXT, sender TEXT, text TEXT, observed_at TEXT, received_at TEXT)')
    conn.execute("INSERT INTO conversation_events VALUES (1, 'p1', 'authorized', 'owner', '框架已确认', '2026-10-03', '2026-10-03')")
    conn.commit()
    monkeypatch.setattr(portfolio_search.main_module, 'get_db', lambda: conn)
    def missing(pid):
        raise HTTPException(404, 'no snapshot')
    monkeypatch.setattr(portfolio_search, '_latest_snapshots', missing)
    result = portfolio_search.search_portfolio(q='框架', project_id=None, source='all', limit=30, offset=0)
    assert result['count'] == 1
    assert result['results'][0]['matched_fields'] == ['正文']
    assert result['unavailable_projects'] == ['p1']


def test_search_pagination_recent_order_and_candidate_limit_are_explicit(monkeypatch):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE projects (project_id TEXT, project_name TEXT)')
    conn.execute("INSERT INTO projects VALUES ('p1', 'Project')")
    conn.commit()
    monkeypatch.setattr(portfolio_search.main_module, 'get_db', lambda: conn)
    monkeypatch.setattr(portfolio_search, '_material_intelligence', lambda pid: {})
    hits = [{'score': i, 'snippet': 'query', 'material': {'path': f'doc-{i}', 'name': f'doc-{i}', 'modified_at': f'2026-10-{i % 3 + 1:02}'}} for i in range(100)]
    monkeypatch.setattr(portfolio_search, 'search_project_intelligence', lambda *args, **kwargs: {'count': 105, 'results': hits})
    first = portfolio_search.search_portfolio(q='query', project_id=None, source='material', limit=30, offset=0, order='recent')
    second = portfolio_search.search_portfolio(q='query', project_id=None, source='material', limit=30, offset=30, order='recent')
    last = portfolio_search.search_portfolio(q='query', project_id=None, source='material', limit=30, offset=90, order='recent')
    assert len(first['results']) == len(second['results']) == 30
    assert len(last['results']) == 10 and not last['has_more']
    assert first['has_more'] and first['count'] == 100
    assert first['truncated_sources'] == [{'project_id': 'p1', 'source': 'material'}]
    assert not {row['source_id'] for row in first['results']} & {row['source_id'] for row in second['results']}
    assert first['results'][0]['source_time'] == '2026-10-03'
