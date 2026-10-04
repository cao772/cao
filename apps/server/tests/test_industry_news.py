import json
import httpx
import pytest
from industry_news import NewsReader, normalize, safe_link


def sample(title='News'):
    return {'schemaVersion': 1, 'items': [{'id':'n', 'title':title, 'summary':'Summary', 'source':{'name':'Official'}, 'links':{'original':'https://example.com/news', 'aihot':'https://aihot.news/items/n'}, 'publishedAt':None, 'discoveredAt':'2026-10-04T01:00:00Z'}], 'page':{'hasMore':True}}


def test_preserves_attribution_and_unknown_publication_time():
    data=normalize(sample(), 'selected')
    assert data['items'][0]['published_at'] == ''
    assert data['items'][0]['discovered_at'] == '2026-10-04T01:00:00Z'
    assert data['items'][0]['url'] == 'https://example.com/news'
    assert data['items'][0]['attribution_url'] == 'https://aihot.news/items/n'
    assert data['has_more']


def test_deduplicates_and_rejects_unsafe_links_and_schemas():
    data=sample(); data['items'].append(data['items'][0])
    data['items'].append({'title':'bad', 'links':{'original':'javascript:alert(1)'}})
    assert len(normalize(data,'hot')['items']) == 1
    assert safe_link('https://user:secret@example.com') is None
    with pytest.raises(ValueError): normalize({'schemaVersion':2, 'items':[]},'hot')
    with pytest.raises(ValueError): normalize({'schemaVersion':1},'hot')


def test_daily_keeps_report_date_separate_from_item_publication():
    data=normalize({'schemaVersion':1,'report':{'date':'2026-10-04','sections':[{'label':'Research','items':sample()['items']}], 'flashes':[], 'links':{'aihot':'https://aihot.news/daily/2026-10-04'}}},'daily')
    assert data['report_date'] == '2026-10-04'
    assert data['items'][0]['published_at'] == ''
    assert data['items'][0]['section'] == 'Research'


def test_cache_survives_restart_and_outage_and_throttles_retries(tmp_path):
    now=[1000]; calls=[]
    def fetch(view):
        calls.append(view)
        if len(calls)>1: raise httpx.ConnectError('offline')
        return sample()
    reader=NewsReader(tmp_path,fetch,lambda:now[0])
    assert reader.read('hot')['status']=='ready'
    assert reader.read('hot')['status']=='ready'
    restarted=NewsReader(tmp_path,fetch,lambda:now[0])
    assert restarted.read('hot')['status']=='ready'
    assert len(calls)==1
    now[0]+=301
    stale=restarted.read('hot')
    assert stale['status']=='stale' and stale['items'][0]['title']=='News'
    assert restarted.read('hot')['status']=='stale'
    assert len(calls)==2
    now[0]+=61
    restarted.read('hot')
    assert len(calls)==3


def test_failure_and_corrupt_cache_do_not_masquerade_as_empty_news(tmp_path):
    (tmp_path/'hot.json').write_text('broken')
    def fetch(_): raise httpx.ConnectError('private runtime details')
    result=NewsReader(tmp_path,fetch).read('hot')
    assert result['status']=='unavailable'
    assert 'private runtime' not in json.dumps(result)


def test_invalid_refresh_preserves_last_good_snapshot(tmp_path):
    now=[1000]; values=iter([sample(), {'schemaVersion':999}])
    reader=NewsReader(tmp_path,lambda _:next(values),lambda:now[0])
    reader.read('selected');now[0]+=301
    assert reader.read('selected')['status']=='stale'
    assert json.loads((tmp_path/'selected.json').read_text())['data']['items'][0]['title']=='News'


def test_original_rank_is_preserved_and_old_cache_is_upgraded(tmp_path):
    old = normalize(sample(), 'hot')
    (tmp_path/'hot.json').write_text(json.dumps({'fetched':1000,'data':old}))
    data = sample();data['items'][0]['rank']=7
    reader=NewsReader(tmp_path,lambda _:data,lambda:1001)
    result=reader.read('hot')
    assert result['items'][0]['rank']==7
    assert json.loads((tmp_path/'hot.json').read_text())['format']==2
    data['items'][0]['rank']=True
    assert normalize(data,'hot')['items'][0]['rank'] is None
