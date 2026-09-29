import sqlite3
from gateway_diagnostics import gateway_diagnostics


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / 'missing.sqlite3'
    assert gateway_diagnostics(path)['state'] == 'not_initialized'
    assert not path.exists()


def test_status_excludes_private_content_and_expires(tmp_path):
    path = tmp_path / 'state.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.executescript('CREATE TABLE gateway_meta(key TEXT,value TEXT); CREATE TABLE commands(status TEXT,created_at INTEGER,command TEXT,reply TEXT);')
        conn.executemany('INSERT INTO gateway_meta VALUES(?,?)', [('last_cycle_ok','1000'),('route_checked_at','1000'),('reply_route','bound_test_private_chat')])
        conn.execute("INSERT INTO commands VALUES('bot_requested',990,'private-command','private-reply')")
    current = gateway_diagnostics(path, 1010)
    assert current['state'] == 'recently_polled'
    assert current['counts'] == {'bot_requested': 1}
    assert current['latest_command_at'] == 990
    assert 'private' not in str(current).replace('bound_test_private_chat', '')
    stale = gateway_diagnostics(path, 1100)
    assert stale['state'] == 'stale'
    assert stale['reply_route'] == 'unknown'


def test_corrupt_database_is_reported(tmp_path):
    path = tmp_path / 'bad.sqlite3'
    path.write_text('not a database')
    assert gateway_diagnostics(path)['state'] == 'unavailable'
