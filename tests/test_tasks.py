import json

from clipscout import judge, pick, tasks
from clipscout import library as lib

from conftest import SENTENCES


def make_stream():
    s = lib.create_stream('tw1', 'Test stream', '2026-09-01', {'kind': 'twitch', 'id': '1'})
    s.path('sentences.txt').write_text(SENTENCES, encoding='utf-8')
    return s


def a_pick(**over):
    p = {'start': 14.5, 'last': 18.2, 'category': 'chat-qa', 'product': 'Stream Deck +',
         'title': 'Does Stream Deck + come in white', 'hook': 'Does the Stream Deck + come in white?',
         'summary': 'A chat question about colours, answered.', 'speakers': 'Phil', 'score': 4, 'flags': [],
         'yt_titles': ['White Stream Deck +?', 'Yes, it comes in white', 'The white Stream Deck +'], 'yt_description': 'Phil answers whether Stream Deck + comes in white.'}
    return {**p, **over}


def answer(tid, value):
    (tasks.folder(tid) / 'output.json').write_text(json.dumps(value), encoding='utf-8')


def test_pick_flow_merges_parts_and_marks_stage_done(library):
    s = make_stream()
    [tid] = pick.open_tasks(s)
    assert tasks.claim_next(agent='test')['id'] == tid
    answer(tid, {'corrections': [{'t': 14.5, 'from': 'Stream Deck Plus', 'to': 'Stream Deck +'}],
                 'picks': [a_pick(), a_pick(start=25.0, last=30.4, start_word='I', category='workflow',
                                             product='Wave Link')]})
    assert tasks.submit(tid) == []
    assert len(s.load('picks.json')) == 2
    assert s.load('corrections.json')[0]['to'] == 'Stream Deck +'
    assert lib.get_stream('tw1').stage('pick')['state'] == 'done'
    assert tasks.load(tid)['state'] == 'done'


def test_pick_check_rejects_bad_times_and_substrings(library):
    s = make_stream()
    [tid] = pick.open_tasks(s)
    answer(tid, {'corrections': [{'t': 14.5, 'from': 'Stream Deck Pro', 'to': 'x'}],
                 'picks': [a_pick(start=15.0), a_pick(start_word='Banana'), a_pick(product='Toaster')]})
    errors = tasks.submit(tid)
    text = '\n'.join(errors)
    assert "'Stream Deck Pro' is not on line" in text
    assert 'start=15.0 is not a sentence start' in text
    assert "start_word 'Banana'" in text
    assert "'Toaster' is not in the product list" in text
    assert tasks.load(tid)['state'] == 'open'


def test_off_by_one_timestamps_are_moved_not_rejected(library):
    s = make_stream()
    [tid] = pick.open_tasks(s)
    answer(tid, {'corrections': [{'t': 10.0, 'from': 'Stream Deck Plus', 'to': 'Stream Deck +'}],
                 'picks': [a_pick(start=18.2, last=30.4, start_word='I', category='workflow', product='Embrace')]})
    assert tasks.submit(tid) == []
    assert s.load('corrections.json')[0]['t'] == 14.5
    assert s.load('picks.json')[0]['start'] == 25.0


def test_schema_errors_are_reported_with_paths(library):
    s = make_stream()
    [tid] = pick.open_tasks(s)
    answer(tid, {'corrections': [], 'picks': [a_pick(score=9, yt_titles=['only one'])]})
    errors = tasks.submit(tid)
    assert any(e.startswith('picks/0/score') for e in errors)
    assert any(e.startswith('picks/0/yt_titles') for e in errors)


def test_code_fenced_output_is_accepted(library):
    s = make_stream()
    [tid] = pick.open_tasks(s)
    (tasks.folder(tid) / 'output.json').write_text('```json\n{"corrections": [], "picks": []}\n```',
                                                   encoding='utf-8')
    assert tasks.submit(tid) == []


def test_long_sentence_files_split_at_pauses():
    lines = []
    for i in range(4000):
        lines.append(f'[00:00:00  {i * 3:.2f}]  ' + 'word ' * 20)
        if i % 10 == 9:
            lines.append('   ~ pause 2.0s')
    total = sum(len(l) + 1 for l in lines)
    parts = pick._parts(lines, total)
    assert len(parts) == -(-total // pick.PART_CHARS)
    assert all(lines[b - 1].lstrip().startswith('~ pause') for _, b in parts[:-1])
    assert parts[0][0] == 0 and parts[-1][1] == len(lines)


def judged(cid, **over):
    v = {'id': cid, 'side': 'staff', 'bin': 'top', 'stars': 4, 'reason': 'Clear buyer question, answered.',
         'dupe_of': None, 'merge': None, 'post': None}
    return {**v, **over}


def test_judge_check_and_apply(library):
    s = make_stream()
    clips = [{'id': 't000145', 'key': 'tw1/t000145', 'hook_at': 14.5, 'source_out': 19.0, 'duration': 4.5,
              'start': 14.5, 'last': 18.2, **{k: a_pick()[k] for k in ('category', 'product', 'score', 'title',
                                                                       'summary', 'speakers', 'flags')}},
             {'id': 't000250', 'key': 'tw1/t000250', 'hook_at': 25.0, 'source_out': 31.0, 'duration': 6.0,
              'start': 25.0, 'last': 30.4, 'start_word': 'I', 'category': 'workflow', 'product': 'Wave Link',
              'score': 3, 'title': 'Hotkeys', 'summary': 'x', 'speakers': 'Phil', 'flags': []}]
    s.save('clips.json', clips)
    [tid] = judge.open_tasks(s)
    packet = (tasks.folder(tid) / 'input.txt').read_text(encoding='utf-8')
    assert 'text: I set up hotkeys on my Wave Link. That' in packet
    answer(tid, [judged('t000250'), judged('t000145')])
    assert 'expected 2 answers in input order' in tasks.submit(tid)[0]
    answer(tid, [judged('t000145', bin='dupe'), judged('t000250', side='community')])
    errors = '\n'.join(tasks.submit(tid))
    assert 'dupe_of must be set' in errors and 'need a draft X post' in errors
    answer(tid, [judged('t000145', merge=['t000145', 't000250']), judged('t000250', bin='dupe', dupe_of='t000145')])
    assert tasks.submit(tid) == []
    assert s.load('judge.json')['t000250']['dupe_of'] == 't000145'
    assert lib.get_stream('tw1').clips()[0]['judge']['merge'] == ['t000145', 't000250']
