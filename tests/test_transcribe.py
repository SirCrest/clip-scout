from clipscout import transcribe


def w(start, end, word):
    return {'start': start, 'end': end, 'word': word, 'p': 0.9}


WORDS = [
    w(0.0, 0.3, ' Does'), w(0.3, 0.6, ' Stream'), w(0.6, 0.9, ' Deck'), w(0.9, 1.2, ' Plus'), w(1.2, 1.5, ' fit?'),
    w(1.6, 1.9, ' Yes'), w(1.9, 2.2, ' it'), w(2.2, 2.5, ' does'),
    w(5.0, 5.3, ' Next'), w(5.3, 5.6, ' one.'),
]


def test_sentences_split_on_punctuation_and_pauses():
    out = list(transcribe.sentences(WORDS))
    texts = [''.join(x['word'] for x in s).strip() for s, _ in out]
    assert texts == ['Does Stream Deck Plus fit?', 'Yes it does', 'Next one.']
    gaps = [round(g, 2) for _, g in out]
    assert gaps == [0.1, 2.5, 0]


def test_render_sentences_applies_corrections_and_marks_pauses():
    fixes = {0.0: [{'t': 0.0, 'from': 'Stream Deck Plus', 'to': 'Stream Deck +'}]}
    text = transcribe.render_sentences('tw1', 'A stream', 6, WORDS, fixes)
    lines = text.splitlines()
    assert lines[0] == '# tw1  A stream'
    assert lines[1] == '# duration 00:00:06'
    assert lines[3] == '[00:00:00  0.00]  Does Stream Deck + fit?'
    assert lines[4] == '[00:00:01  1.60]  Yes it does'
    assert lines[5] == '   ~ pause 2.5s'
    assert lines[6] == '[00:00:05  5.00]  Next one.'


def test_empty_transcript():
    assert list(transcribe.sentences([])) == []
