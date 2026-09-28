from datetime import datetime, timezone

import pytest

import googleapiclient.http
from clipscout import publish
from clipscout import library as lib

KEY, KEY2 = 'tw1/t000145', 'tw1/t000250'
ELGATO_CLIPS = {'id': publish.CHANNEL_ID, 'snippet': {'title': 'Elgato Clips'},
                'contentDetails': {'relatedPlaylists': {'uploads': 'UU1'}}}


class FakeUpload:
    def __init__(self, yt, body):
        self.yt, self.body, self.calls = yt, body, 0

    def next_chunk(self):
        self.calls += 1
        if self.calls == 1:
            return type('S', (), {'progress': lambda self: 0.5})(), None
        vid = f'vid{len(self.yt.inserted) + 1}'
        self.yt.inserted.append((vid, self.body))
        return None, {'id': vid}


class FakeYT:
    """Stands in for googleapiclient's youtube service; records every call."""

    def __init__(self, channels=None, playlists=None, uploads=None):
        self.channel_items = [ELGATO_CLIPS] if channels is None else channels
        self.playlist_items = [{'id': 'PL1', 'snippet': {'title': 'Stream Deck'}}] if playlists is None else playlists
        self.uploads = uploads or []
        self.log, self.inserted = [], []

    def _resource(self, name, handlers):
        yt = self

        class Resource:
            def __getattr__(self, method):
                def call(**kwargs):
                    yt.log.append((f'{name}.{method}', kwargs))
                    result = handlers[method](**kwargs)
                    if isinstance(result, FakeUpload):
                        return result
                    return type('Req', (), {'execute': lambda self: result})()
                return call
        return Resource()

    def channels(self):
        return self._resource('channels', {'list': lambda **k: {'items': self.channel_items}})

    def playlists(self):
        return self._resource('playlists', {'list': lambda **k: {'items': self.playlist_items}})

    def playlistItems(self):
        return self._resource('playlistItems', {
            'insert': lambda **k: {'id': 'item'},
            'list': lambda **k: {'items': [{'contentDetails': {'videoId': v['id']}} for v in self.uploads]}})

    def videos(self):
        return self._resource('videos', {
            'insert': lambda body, **k: FakeUpload(self, body),
            'update': lambda body, **k: body,
            'list': lambda id, **k: {'items': [v for v in self.uploads if v['id'] in id.split(',')]}})

    def calls(self, name):
        return [kw for n, kw in self.log if n == name]


@pytest.fixture
def yt(library, monkeypatch):
    fake = FakeYT()
    monkeypatch.setattr(publish, '_service', lambda: fake)
    monkeypatch.setattr(googleapiclient.http, 'MediaFileUpload', lambda *a, **k: object())
    monkeypatch.setattr(publish.time, 'sleep', lambda s: None)
    return fake


def rendered(library, key, name):
    path = library / 'approved' / 'YouTube' / 'Stream Deck' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'video')
    renders = lib.read_json(library / 'renders.json', {})
    renders[key] = {'path': path.relative_to(library).as_posix(), 'rendered_at': 'x', 'lossless': False}
    lib.write_json(library / 'renders.json', renders)


def approved(key, playlist='Stream Deck', **extra):
    publish.save_drafts({key: {'titles': ['Title A here', 'Title B here', 'Title C here'],
                               'description': 'Words.', 'tags': ['Elgato'], 'playlist': playlist}})
    assert publish.approve(key, {})['ok']
    if extra:
        publish._record(key, **extra)


def test_channel_check_passes_and_is_remembered(yt):
    assert publish.channel() == {'ok': True, 'channel': {'id': publish.CHANNEL_ID, 'title': 'Elgato Clips'}}
    assert lib.read_json(lib.LIBRARY / 'settings.json')['publish']['channel_id'] == publish.CHANNEL_ID


@pytest.mark.parametrize('items, message', [
    ([{'id': 'UCother', 'snippet': {'title': 'Elgato'}}], 'not Elgato Clips'),
    ([ELGATO_CLIPS, {'id': 'UCx', 'snippet': {'title': 'Me'}}], 'has 2 YouTube channels'),
    ([], 'has 0 YouTube channels'),
])
def test_wrong_channel_blocks_every_write(yt, library, items, message):
    yt.channel_items = items
    approved(KEY)
    rendered(library, KEY, 'a.mp4')
    result = publish.upload([KEY])
    assert not result['ok'] and message in result['error']
    assert yt.inserted == [] and not yt.calls('videos.update')


def test_upload_happens_once_and_adds_to_existing_playlists(yt, library):
    approved(KEY)
    approved(KEY2, playlist='Lighting')
    rendered(library, KEY, 'a.mp4')
    rendered(library, KEY2, 'b.mp4')
    messages = []
    result = publish.upload([KEY, KEY2], messages.append)
    assert [u['key'] for u in result['uploaded']] == [KEY, KEY2]
    assert result['missing_playlists'] == ['Lighting']
    assert any('50%' in m for m in messages)
    body = yt.inserted[0][1]
    assert body['snippet']['title'] == 'Title A here' and body['snippet']['categoryId'] == '22'
    assert body['status'] == {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False,
                              'containsSyntheticMedia': False}
    assert len(yt.calls('playlistItems.insert')) == 1
    entry = publish.load()[KEY]
    assert entry['status'] == 'uploaded' and entry['url'] == 'https://youtu.be/vid1'
    again = publish.upload([KEY])
    assert again['skipped'] == [{'key': KEY, 'reason': 'already on YouTube'}] and len(yt.inserted) == 2


def test_unapproved_or_unrendered_clips_are_skipped(yt, library):
    publish.save_drafts({KEY: {'titles': ['A title', 'B title', 'C title'], 'description': 'x', 'tags': []}})
    approved(KEY2)
    result = publish.upload([KEY, KEY2])
    assert {s['reason'] for s in result['skipped']} == {'copy not approved', 'not rendered yet'}
    assert yt.inserted == []


def test_schedule_slots_and_upload_sends_publish_at(yt, library):
    approved(KEY)
    approved(KEY2)
    now = datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc)  # 17:30 on Sep 30 in Los Angeles (PDT)
    plan = publish.schedule([KEY, KEY2], '2026-09-30', per_day=2, at_time='17:00', now=now)
    # 17:00 has passed, so the first slot is 19:00 that day; the next is 17:00 the following day
    assert [p['publish_at'] for p in plan['planned']] == ['2026-10-01T02:00:00Z', '2026-10-02T00:00:00Z']
    assert plan['planned'][0]['local'].startswith('2026-09-30T19:00')
    assert plan['planned'][1]['local'].startswith('2026-10-01T17:00')
    publish._record(KEY, publish_at='2999-01-01T17:00:00Z')
    rendered(library, KEY, 'a.mp4')
    result = publish.upload([KEY])
    assert result['uploaded'][0]['scheduled']
    assert yt.inserted[0][1]['status']['publishAt'] == '2999-01-01T17:00:00Z'
    assert publish.load()[KEY]['status'] == 'scheduled'


def test_past_publish_time_is_not_uploaded(yt, library):
    approved(KEY, publish_at='2020-01-01T00:00:00Z')
    rendered(library, KEY, 'a.mp4')
    assert 'schedule it again' in publish.upload([KEY])['skipped'][0]['reason']


def test_quota_stops_before_the_daily_limit(yt, library):
    approved(KEY)
    rendered(library, KEY, 'a.mp4')
    lib.write_json(lib.LIBRARY / 'publish-quota.json',
                   {'day': publish._today(), 'units': publish.DAILY_UNITS - publish.RESERVE_UNITS - 10, 'uploads': 0})
    result = publish.upload([KEY])
    assert result['ok'] is False or result['stopped']
    assert yt.inserted == []


def test_upload_bucket_limit(yt, library):
    approved(KEY)
    rendered(library, KEY, 'a.mp4')
    lib.write_json(lib.LIBRARY / 'publish-quota.json', {'day': publish._today(), 'units': 0, 'uploads': 100})
    result = publish.upload([KEY])
    assert result['stopped'] and yt.inserted == []


def test_a_crashed_upload_is_recovered_not_repeated(yt, library):
    approved(KEY, upload_started_at='2026-09-28T10:00:00')
    rendered(library, KEY, 'a.mp4')
    yt.uploads = [{'id': 'old1', 'fileDetails': {'fileName': 'a.mp4'}, 'status': {'privacyStatus': 'private'}}]
    result = publish.upload([KEY])
    assert result['uploaded'] == [{'key': KEY, 'video_id': 'old1', 'recovered': True}]
    assert yt.inserted == []


def test_sync_fills_fresh_studio_uploads_and_only_links_the_rest(yt, library):
    approved(KEY)
    publish.save_drafts({KEY2: {'titles': ['A title', 'B title', 'C title'], 'description': 'x', 'tags': []}})
    rendered(library, KEY, 'SD - White (2026-09-01 Test).mp4')
    rendered(library, KEY2, 'b.mp4')
    yt.uploads = [
        {'id': 'v1', 'fileDetails': {'fileName': 'SD - White (2026-09-01 Test).mp4'},
         'status': {'privacyStatus': 'private'}},
        {'id': 'v2', 'fileDetails': {'fileName': 'b.mp4'}, 'status': {'privacyStatus': 'public'}},
        {'id': 'v3', 'fileDetails': {'fileName': 'unrelated.mp4'}, 'status': {'privacyStatus': 'public'}},
    ]
    result = publish.sync()
    assert result['filled'] == [{'key': KEY, 'video_id': 'v1'}]
    assert result['linked'][0]['key'] == KEY2 and result['unmatched'][0]['video_id'] == 'v3'
    [update] = yt.calls('videos.update')
    assert update['body']['id'] == 'v1' and update['body']['snippet']['title'] == 'Title A here'
    assert publish.load()[KEY2]['status'] == 'public'
    yt.uploads[0]['status'] = {'privacyStatus': 'public'}
    assert publish.sync()['refreshed'] == [{'key': KEY, 'status': 'public'}]


def test_approve_validates_youtube_limits(yt):
    publish.save_drafts({KEY: {'titles': ['A title', 'B title', 'C title'], 'description': 'x', 'tags': []}})
    bad = publish.approve(KEY, {'titles': ['x' * 101, 'B', 'C']})
    assert not bad['ok'] and 'max 100' in bad['error']
    assert not publish.approve(KEY, {'description': 'a < b'})['ok']
    assert not publish.approve(KEY, {'bogus': 1})['ok']
    publish._record(KEY, status='uploaded', video_id='v')
    assert 'already on YouTube' in publish.approve(KEY, {})['error']


def test_sheet_lists_everything(yt, library):
    approved(KEY)
    path = publish.sheet()['path']
    text = open(path, encoding='utf-8-sig').read()
    assert 'Title A here' in text and KEY in text


def test_signin_without_client_file_explains_what_to_do(library, monkeypatch):
    monkeypatch.setattr(publish, 'CLIENT_FILE', library / 'nope.json')
    result = publish.signin()
    assert not result['ok'] and 'OAuth client file' in result['error']
