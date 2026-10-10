import json
import sqlite3
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import wechat_notifications_api as api
from conversation_intelligence import init_db, insert_event

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
BINDINGS = [{'project_id': 'p', 'group_name': 'authorized'}]


def test_mixed_users_projects_groups_devices_never_leak():
    db = sqlite3.connect(':memory:')
    init_db(db)
    for i, (user, device, project, group) in enumerate([
        ('u','d','p','authorized'), ('other','d','p','authorized'),
        ('u','other','p','authorized'), ('u','d','other','authorized'),
        ('u','d','p','private'),
    ]):
        insert_event(db, {'event_fingerprint': f'{i:064x}', 'project_id': project,
                         'conversation_name': group, 'user_id': user, 'device_id': device,
                         'text': 'secret chat', 'sender': 'secret sender',
                         'observed_at': NOW.isoformat(), 'categories': ['task']}, NOW.isoformat())
    scope = api.scope_digest('u', 'd', BINDINGS)
    health = {'scope_id': scope, 'status': 'available', 'last_success_at': NOW.isoformat()}
    result = api.summarize(db, 'u', 'd', BINDINGS, scope, health, NOW)
    assert result['status'] == 'available'
    assert len(result['events']) == 1
    assert set(result['events'][0]) == {'event_id','category'}
    assert 'secret' not in json.dumps(result)
    assert 'authorized' not in json.dumps(result['events'])
    assert result['events'][0]['event_id'] != '0' * 64
    for h in ({}, {**health, 'scope_id': 'other'},
              {**health, 'last_success_at': 'invalid'}):
        assert api.summarize(db, 'u', 'd', BINDINGS, scope, h, NOW)['status'] == 'unavailable'
    stale = {**health, 'last_success_at': (NOW - timedelta(hours=2)).isoformat()}
    assert api.summarize(db, 'u', 'd', BINDINGS, scope, stale, NOW)['status'] == 'stale'


def test_live_authorization_revocation_and_scope_change(tmp_path, monkeypatch):
    monkeypatch.setenv('CAO_WECHAT_STATE_ROOT', str(tmp_path))
    monkeypatch.setenv('CAO_WECHAT_USER_ID', 'u')
    monkeypatch.setenv('CAO_WECHAT_DEVICE_ID', 'd')
    target = tmp_path / 'wechat-config.json'
    target.write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(), 'enabled': True, 'bindings': BINDINGS}))
    first = api.read_scope()[3]
    target.write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(), 'enabled': True, 'bindings': [*BINDINGS, {'project_id': 'p', 'group_name': 'another'}]}))
    assert api.read_scope()[3] != first
    target.write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(), 'enabled': False, 'bindings': BINDINGS}))
    with pytest.raises(HTTPException) as error:
        api.read_scope()
    assert error.value.status_code == 503


def test_auth_happens_before_reading_scope(monkeypatch):
    monkeypatch.setenv('CAO_MUSE_WECHAT_TOKEN', 'dedicated-test-token' * 3)
    monkeypatch.setattr(api, 'read_scope', lambda: pytest.fail('read before auth'))
    req = Request({'type': 'http', 'client': ('127.0.0.1', 1)})
    with pytest.raises(HTTPException) as error:
        api.wechat_notifications(req, None)
    assert error.value.status_code == 401
    req = Request({'type': 'http', 'client': ('203.0.113.2', 1)})
    with pytest.raises(HTTPException) as error:
        api.wechat_notifications(req, 'dedicated-test-token' * 3)
    assert error.value.status_code == 403
