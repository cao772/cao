import json

import wechat_helper as helper


def test_empty_success_is_fresh_but_failure_and_disabled_invalidate(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, 'STATE_ROOT', tmp_path)
    result = {'wechat': {'available': True}, 'failed': 0, 'groups': [{}]}
    monkeypatch.setattr(helper, '_collect_authorized_groups', lambda config: result)
    config = {'enabled': True, 'bindings': [{'project_id': 'p', 'group_name': 'g'}]}
    helper.collect_authorized_groups(config)
    path = tmp_path / 'muse-readonly' / 'wechat-muse-health.json'
    health = json.loads(path.read_text())
    assert health['status'] == 'available'
    assert health['last_success_at']
    assert path.stat().st_mode & 0o777 == 0o600
    result['failed'] = 1
    helper.collect_authorized_groups(config)
    assert json.loads(path.read_text())['status'] == 'unavailable'
    result['failed'] = 0
    config['enabled'] = False
    helper.collect_authorized_groups(config)
    assert json.loads(path.read_text())['last_success_at'] is None


def test_projection_is_minimal_and_revoked_immediately(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, 'STATE_ROOT', tmp_path)
    monkeypatch.setattr(helper, 'CONFIG_PATH', tmp_path / 'wechat-config.json')
    config = {'enabled': True, 'bindings': [{'project_id': 'p', 'group_name': 'g'}], 'token': 'secret'}
    helper.save_config(config)
    path = tmp_path / 'muse-readonly' / 'wechat-config.json'
    assert 'secret' not in path.read_text()
    config['enabled'] = False
    helper.save_config(config)
    assert json.loads(path.read_text())['enabled'] is False
