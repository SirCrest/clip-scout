import pytest
from fastapi.testclient import TestClient

from clipscout import decisions, server
from clipscout import library as lib

W = {'X-Clip-Scout': '1'}


def clip(cid, hook, out, **over):
    c = {'id': cid, 'key': f'tw1/{cid}', 'hook_at': hook, 'source_out': out, 'duration': out - hook,
         'title': f'Clip {cid}', 'product': 'Stream Deck', 'topic': 'Stream Deck', 'flags': ['visual'],
         'judge': {'side': 'staff', 'bin': 'top', 'stars': 4, 'reason': 'Good.', 'merge': None, 'dupe_of': None}}
    return {**c, **over}


@pytest.fixture
def client(library, monkeypatch):
    monkeypatch.setattr(server, 'catalog', server.Catalog())
    monkeypatch.setattr(server.renderer, 'enqueue', lambda key, now=False: None)
    s = lib.create_stream('tw1', 'Test stream', '2026-09-01', {'kind': 'twitch', 'id': '1'})
    s.save('clips.json', [clip('t000100', 10, 40), clip('t000410', 41, 70, flags=['dated']),
                          clip('t000200', 20, 30, judge={'side': 'staff', 'bin': 'effort', 'stars': 2})])
    return TestClient(server.app, base_url='http://127.0.0.1')


def test_writes_need_the_header_and_localhost(client):
    assert client.post('/api/decide', json={'key': 'tw1/t000100', 'd': 'keep'}).status_code == 403
    assert client.get('/api/overview', headers={'Host': 'evil.example'}).status_code == 403
    r = client.post('/api/decide', json={'key': 'tw1/t000100', 'd': 'keep'},
                    headers={**W, 'Origin': 'https://evil.example'})
    assert r.status_code == 403


def test_clips_are_compact_and_nest_short_cuts(client):
    clips = {c['id']: c for c in client.get('/api/clips').json()['clips']}
    assert set(clips) == {'t000100', 't000410', 't000200'}
    assert clips['t000200']['inside'] == 'tw1/t000100'
    assert clips['t000100']['inside'] is None


def test_decide_and_undo(client):
    assert client.post('/api/decide', json={'key': 'tw1/t000100', 'd': 'keep'}, headers=W).json()['ok']
    assert decisions.load()['decisions']['tw1/t000100']['d'] == 'keep'
    r = client.post('/api/decide', json={'key': 'tw1/t000100', 'd': None}, headers=W).json()
    assert r['before']['d'] == 'keep'
    assert 'tw1/t000100' not in decisions.load()['decisions']
    assert client.post('/api/decide', json={'key': 'tw1/nope', 'd': 'keep'}, headers=W).status_code == 404


def test_make_one_clip(client):
    r = client.post('/api/merge', json={'keys': ['tw1/t000100', 'tw1/t000410']}, headers=W).json()
    merged = lib.get_stream('tw1').clips()
    new = next(c for c in merged if c.get('merged_from'))
    assert r['key'] == new['key'] and new['id'].startswith('t000100') and new['id'] != 't000100'
    assert new['source_out'] == 70 and new['duration'] == 60 and new['flags'] == ['dated', 'visual']
    # the parts now sit inside the combined clip
    clips = {c['id']: c for c in client.get('/api/clips').json()['clips']}
    assert clips['t000410']['inside'] == new['key']
    # asking again returns the same clip
    again = client.post('/api/merge', json={'keys': ['tw1/t000410', 'tw1/t000100']}, headers=W).json()
    assert again['key'] == new['key']
