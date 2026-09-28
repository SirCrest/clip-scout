import json

import pytest

from clipscout import publish, tasks, titles
from clipscout import library as lib

from conftest import SENTENCES

TWITCH = 'https://www.twitch.tv/videos/1?t=0h0m14s'


@pytest.fixture
def stream(library):
    s = lib.create_stream('tw1', 'Test stream', '2026-09-01', {'kind': 'twitch', 'id': '1'})
    s.path('sentences.txt').write_text(SENTENCES, encoding='utf-8')
    base = {'category': 'chat-qa', 'score': 4, 'speakers': 'Phil', 'summary': 'x', 'yt_description': 'Draft.'}
    s.save('clips.json', [
        {**base, 'id': 't000145', 'key': 'tw1/t000145', 'hook_at': 14.5, 'source_out': 19.0, 'duration': 4.5,
         'start': 14.5, 'last': 18.2, 'product': 'Stream Deck +', 'topic': 'Stream Deck', 'title': 'White SD+',
         'flags': ['dated', 'preroll-speech'], 'yt_titles': ['One', 'Two', 'Three'], 'source_url': TWITCH,
         'judge': {'side': 'staff', 'bin': 'top', 'stars': 5, 'reason': 'Buyer question.'}},
        {**base, 'id': 't000250', 'key': 'tw1/t000250', 'hook_at': 25.0, 'source_out': 31.0, 'duration': 6.0,
         'start': 25.0, 'last': 30.4, 'product': 'Wave Link', 'topic': 'Wave Link and audio software',
         'title': 'Hotkeys', 'flags': [], 'yt_titles': [], 'source_url': None,
         'judge': {'side': 'community', 'bin': 'top', 'stars': 4, 'reason': 'Creator tip.', 'post': 'x'}},
    ])
    return s


def answer(**over):
    a = {'id': 't000145',
         'titles': ['Elgato Stream Deck +: Yes, It Comes in White',
                    'Does Stream Deck + Come in White? The Answer',
                    'The White Stream Deck + You Asked About'],
         'description': 'Stream Deck + comes in white.\n\nPhil answers a chat question live.\n\n'
                        'Explore Stream Deck: https://www.elgato.com/us/en/s/stream-deck',
         'hashtags': ['#StreamDeck'], 'tags': ['Stream Deck +', 'Elgato'], 'playlist': 'Stream Deck',
         'hold': ['dated'], 'note': 'Check the white model is still sold.'}
    return {**a, **over}


def write(tid, value):
    (tasks.folder(tid) / 'output.json').write_text(json.dumps(value), encoding='utf-8')


def test_opens_one_task_for_staff_clips_only(stream):
    [tid] = titles.open_tasks_for(['tw1/t000145', 'tw1/t000250'])
    task = tasks.load(tid)
    assert task['keys'] == ['tw1/t000145']
    packet = (tasks.folder(tid) / 'input.txt').read_text(encoding='utf-8')
    assert 'Explore Stream Deck: https://www.elgato.com/us/en/s/stream-deck' in packet
    assert 'words: So, does the Stream Deck Plus come in white?' in packet
    assert 'YouTube house style' in (tasks.folder(tid) / 'TASK.md').read_text(encoding='utf-8')
    assert titles.open_tasks_for(['tw1/t000145']) == []  # already in an open task


def test_check_rejects_invented_links_boilerplate_and_bad_playlists(stream):
    [tid] = titles.open_tasks_for(['tw1/t000145'])
    write(tid, [answer(titles=['Same Title Here', 'same title here', 'Another Title'],
                       description='Great clip.\n\nMore words here to pass the length check easily.\n\n'
                                   'Buy it: https://www.elgato.com/us/en/p/stream-deck-plus-white\n\n'
                                   '▼ Connect with Elgato:',
                       playlist='Best Of', note=None)])
    errors = '\n'.join(tasks.submit(tid))
    assert 'must be different' in errors
    assert 'stream-deck-plus-white is not one of the listed links' in errors
    assert 'Clip Scout adds them' in errors
    assert "playlist 'Best Of'" in errors
    assert 'say in note' in errors


def test_accepted_answer_becomes_a_composed_draft(stream):
    [tid] = titles.open_tasks_for(['tw1/t000145'])
    write(tid, [answer()])
    assert tasks.submit(tid) == []
    entry = publish.load()['tw1/t000145']
    assert entry['status'] == 'draft' and entry['category_id'] == '22'
    assert entry['titles'][0] == 'Elgato Stream Deck +: Yes, It Comes in White'
    d = entry['description']
    assert d.index('Explore Stream Deck') < d.index(f'Watch the full stream: {TWITCH}') < d.index('▼ Connect')
    assert d.rstrip().endswith('#StreamDeck')
    assert entry['warnings'] == ['dated']
    assert publish.check_copy(entry) == []


def test_drafts_never_replace_approved_copy(stream):
    [tid] = titles.open_tasks_for(['tw1/t000145'])
    write(tid, [answer()])
    tasks.submit(tid)
    assert publish.approve('tw1/t000145', {'titles': ['Mine A title', 'Mine B title', 'Mine C title']})['ok']
    assert titles.open_tasks_for(['tw1/t000145']) == []  # has copy already
    [tid2] = titles.open_tasks_for(['tw1/t000145'], force=True) or [tid]
    tasks.reopen(tid2)
    write(tid2, [answer(titles=['New A title here', 'New B title here', 'New C title here'])])
    assert tasks.submit(tid2) == []
    entry = publish.load()['tw1/t000145']
    assert entry['status'] == 'approved' and entry['titles'][0] == 'Mine A title'
    assert entry['suggestion']['titles'][0] == 'New A title here'


def test_tags_are_counted_the_way_youtube_counts_them():
    assert titles.tags_length(['a b', 'cd']) == len('"a b"') + 1 + len('cd')
