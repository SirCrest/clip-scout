import numpy as np
import pytest

from clipscout import edit
from clipscout import library as lib

FPS = 60


def level_for(words, t0=0.0, t1=30.0, voiced=()):
    """A fake audio level: speech at each word (and any extra `voiced` spans), silence elsewhere."""
    n = int((t1 - t0) / edit.HOP)
    db = np.full(n, -80.0, np.float32)
    for w in list(words) + [{'start': a, 'end': b} for a, b in voiced]:
        a, b = int((w['start'] - t0) / edit.HOP), int((w['end'] - t0) / edit.HOP)
        db[a:b] = -25.0
    return edit.Level(db, t0)


def sentence(start, texts, step=0.3, dur=0.25):
    return [{'start': round(start + k * step, 3), 'end': round(start + k * step + dur, 3), 'w': t, 'a': -0.1}
            for k, t in enumerate(texts)]


def make_det(words, pauses=(), fillers=(), shots=(), rng=None):
    w0 = next(i for i, w in enumerate(words) if not w.get('m'))
    w1 = max(i for i, w in enumerate(words) if not w.get('m'))
    rng = rng or [words[w0]['start'], words[w1]['end'] + 0.5]
    return {'clip': 't000010', 'range': rng, 'sig': 'x', 'w0': w0, 'w1': w1, 'words': words, 'pauses': list(pauses),
            'fillers': list(fillers), 'shots': list(shots), 'video': {'width': 1920, 'height': 1080, 'fps': FPS}}


CLIP = {'id': 't000010', 'hook_at': 1.0, 'source_out': 12.0}


@pytest.fixture
def two_sentences():
    words = sentence(1.0, ['This', 'is', 'the', 'first', 'point.']) + sentence(4.0, ['And', 'here', 'is', 'more.'])
    return words


def kept_texts(edl, words):
    out = []
    for w in words:
        mid = (w['start'] + w['end']) / 2
        if any(s['src_in'] <= mid < s['src_out'] for s in edl['segments']):
            out.append(w['w'])
    return out


def test_pause_cut_and_frame_grid(two_sentences):
    lvl = level_for(two_sentences)
    pauses = edit.find_pauses(two_sentences, 0, len(two_sentences) - 1, lvl)
    assert len(pauses) == 1 and pauses[0]['gap'] > 1.5
    edl = edit.build(None, CLIP, make_det(two_sentences, pauses), lvl=lvl)
    assert kept_texts(edl, two_sentences) == [w['w'] for w in two_sentences]
    assert len(edl['segments']) == 2 and len(edl['cuts']) == 1
    # silence left between the sentences is about KEEP_END
    gap = edl['segments'][1]['src_in'] - edl['segments'][0]['src_out']
    assert gap == pytest.approx(pauses[0]['to'] - pauses[0]['from'], abs=0.02)
    for s in edl['segments']:
        for t in (s['src_in'], s['src_out']):
            assert abs(t * FPS - round(t * FPS)) < 1e-3


def test_restore_keeps_a_pause(two_sentences):
    lvl = level_for(two_sentences)
    det = make_det(two_sentences, edit.find_pauses(two_sentences, 0, len(two_sentences) - 1, lvl))
    edl = edit.build(None, CLIP, det, human={'restore': ['p1']}, lvl=lvl)
    assert len(edl['segments']) == 1 and not [r for r in edl['removed'] if r['kind'] == 'pause']


def test_agent_removal_trim_and_human_precedence(two_sentences):
    lvl = level_for(two_sentences)
    det = make_det(two_sentences)
    agent = {'layout': 'screen', 'punch_in_ok': False, 'start': 1, 'end': None,
             'remove': [{'from': 6, 'to': 7, 'reason': 'aside'}]}
    edl = edit.build(None, CLIP, det, agent=agent, lvl=lvl)
    assert kept_texts(edl, two_sentences) == ['is', 'the', 'first', 'point.', 'And', 'more.']
    assert edl['source'] == 'agent' and edl['removed'][0]['id'] == 't0'
    human = {'restore': ['c1'], 'remove': [{'from': 1.55, 'to': 2.0}]}
    edl = edit.build(None, CLIP, det, agent=agent, human=human, lvl=lvl)
    assert 'here' in kept_texts(edl, two_sentences)
    assert kept_texts(edl, two_sentences)[:2] == ['is', 'first']  # "the" (1.6-1.85 s) removed by hand
    assert edl['source'] == 'human'


def test_cut_between_run_together_words_is_flagged_tight():
    words = sentence(1.0, ['you', 'want', 'mute.', 'Speaking', 'of', 'deals.', 'Back', 'to', 'it.'], step=0.25,
                     dur=0.25)
    lvl = level_for(words)  # no silence anywhere between the words
    det = make_det(words)
    agent = {'layout': 'camera', 'punch_in_ok': False, 'remove': [{'from': 3, 'to': 5, 'reason': 'plug'}]}
    edl = edit.build(None, CLIP, det, agent=agent, lvl=lvl)
    content = [r for r in edl['removed'] if r['kind'] == 'content']
    assert content[0].get('tight') and any(c['tight'] for c in edl['cuts'])


def test_voiced_sliver_is_kept_even_without_a_word():
    words = sentence(1.0, ['one', 'two.']) + sentence(3.0, ['three', 'four.'])
    lvl = level_for(words, voiced=[(2.1, 2.3)])  # a sound the transcript put nowhere
    removals = [{'from': 1.6, 'to': 2.05, 'kind': 'pause'}, {'from': 2.35, 'to': 2.9, 'kind': 'pause'}]
    segs = edit._keep(1.0, 4.0, removals, words, FPS, lvl)
    assert any(s['src_in'] <= 2.2 < s['src_out'] for s in segs)
    quiet = level_for(words)
    segs = edit._keep(1.0, 4.0, removals, words, FPS, quiet)
    assert not any(s['src_in'] <= 2.2 < s['src_out'] for s in segs)


def test_punch_ins_alternate_and_reset_at_a_shot_change():
    segs = [{'src_in': a, 'src_out': b, 'zoom': 1.0} for a, b in ((0, 2), (2.5, 4), (4.5, 6), (6.5, 8))]
    out, cuts = edit._styles(segs, [], True, {}, {}, FPS)
    assert [s['zoom'] for s in out] == [1.0, edit.ZOOM, 1.0, edit.ZOOM]
    assert all(c['style'] == 'punch' for c in cuts)
    out, cuts = edit._styles(segs, [4.3], True, {}, {}, FPS)
    assert cuts[1]['style'] == 'hard' and cuts[1]['why'] == 'shot change'
    assert out[2]['zoom'] == 1.0
    out, cuts = edit._styles(segs, [], False, {1: 'punch'}, {}, FPS)
    assert [c['style'] for c in cuts] == ['hard', 'punch', 'hard'] and cuts[1]['why'] == 'by hand'


def test_zoom_ends_at_a_shot_change_inside_a_segment():
    segs = [{'src_in': 0, 'src_out': 2, 'zoom': 1.0}, {'src_in': 2.5, 'src_out': 6, 'zoom': 1.0}]
    out, cuts = edit._styles(segs, [4.0], True, {}, {}, FPS)
    assert [(s['src_in'], s['src_out'], s['zoom']) for s in out] == [(0, 2, 1.0), (2.5, 4.0, edit.ZOOM), (4.0, 6, 1.0)]
    assert len(cuts) == 1 and cuts[0]['at'] == pytest.approx(2.0)


def test_ctc_path_finds_each_token():
    # 3 tokens (ids 5, 6, 5) over 9 frames; blank is 0
    V, T = 8, 9
    lp = np.full((T, V), -10.0)
    lp[:, 0] = -0.1
    for t, tok in ((1, 5), (2, 5), (4, 6), (7, 5)):
        lp[t, tok] = -0.01
        lp[t, 0] = -5
    spans = edit.ctc_path(lp, [5, 6, 5])
    assert spans == [(1, 2), (4, 4), (7, 7)]
    assert edit.ctc_path(lp[:2], [5, 6, 5]) is None


def test_merge_fillers_skips_duplicates():
    words = sentence(1.0, ['So', 'uh,', 'the', 'idea.'])
    merged = edit.merge_fillers(words, [{'start': 1.3, 'end': 1.5, 'w': 'uh'}, {'start': 2.2, 'end': 2.4, 'w': 'um'}])
    assert [w['w'] for w in merged] == ['So', 'uh,', 'the', 'idea.', 'um']


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, 'LIBRARY', tmp_path)
    monkeypatch.setattr(lib, 'STREAMS', tmp_path / 'streams')
    monkeypatch.setattr(lib, 'TASKS', tmp_path / 'tasks')
    return tmp_path


def test_check_rejects_bad_answers(library, two_sentences):
    s = lib.create_stream('f123', 'Test', '2026-09-01', {'kind': 'file'})
    clip = dict(CLIP)
    s.save('clips.json', [clip])
    det = make_det(two_sentences, rng=[clip['hook_at'], clip['source_out']])
    lib.write_json(edit.folder(s) / 't000010.detect.json', det)
    task = {'stream': 'f123', 'keys': ['f123/t000010']}
    good = {'clips': [{'clip': 't000010', 'layout': 'camera', 'punch_in_ok': True, 'remove': [{'from': 5, 'to': 6,
                                                                                               'reason': 'x'}]}]}
    assert edit.check(task, good) == []
    assert edit.check(task, {'clips': []})  # missing clip
    bad = {'clips': [{'clip': 't000010', 'layout': 'camera', 'punch_in_ok': True,
                      'remove': [{'from': 0, 'to': 2, 'reason': 'x'}], 'keep': ['p9']}]}
    errors = edit.check(task, bad)
    assert any('inside the kept words' in e for e in errors) and any('p9' in e for e in errors)
