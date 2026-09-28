import re

from clipscout import render

WORDS = [{'start': 1.0, 'end': 1.2, 'w': 'Hello'}, {'start': 1.3, 'end': 1.5, 'w': 'there.'},
         {'start': 2.0, 'end': 2.2, 'w': 'um'}, {'start': 3.0, 'end': 3.3, 'w': 'Stream'},
         {'start': 3.4, 'end': 3.6, 'w': 'Deck'}, {'start': 3.7, 'end': 4.0, 'w': 'Plus.'}]
SEGS = [{'src_in': 0.9, 'src_out': 1.6, 'zoom': 1.0}, {'src_in': 2.9, 'src_out': 4.1, 'zoom': 1.08}]
FACTS = {'width': 1920, 'height': 1080, 'fps': 60}


def test_remap_moves_words_onto_the_edited_timeline():
    out = render.remap(WORDS, SEGS)
    assert [w[2] for w in out] == ['Hello', 'there.', 'Stream', 'Deck', 'Plus.']
    assert out[0][0] == 1.0 - 0.9
    assert abs(out[2][0] - (0.7 + 0.1)) < 1e-9  # 0.7 s of the first piece, then 0.1 s into the second


def test_captions_drop_fillers_fix_names_and_wrap():
    srt = render.captions(WORDS, SEGS)
    assert 'um' not in srt
    assert 'Stream Deck +' in srt  # elgato name fix: "Stream Deck Plus" -> "Stream Deck +"
    blocks = srt.strip().split('\n\n')
    assert len(blocks) == 2 and blocks[0].startswith('1\n00:00:00,100 --> ')
    long_words = [{'start': 1 + k * 0.3, 'end': 1.2 + k * 0.3, 'w': 'word'} for k in range(14)]
    text = render.captions(long_words, [{'src_in': 0, 'src_out': 10, 'zoom': 1.0}])
    first = text.split('\n\n')[0].splitlines()
    assert len(first) == 4 and all(len(line) <= 42 for line in first[2:])


def test_captions_glue_split_words_and_capitalise_after_a_sentence():
    words = [{'start': 1.0, 'end': 1.2, 'w': 'Done.'}, {'start': 1.3, 'end': 1.5, 'w': 'they'},
             {'start': 1.6, 'end': 1.8, 'w': 'get'}, {'start': 1.9, 'end': 2.1, 'w': 'broadcast'},
             {'start': 2.1, 'end': 2.3, 'w': '-ready'}, {'start': 2.4, 'end': 2.6, 'w': 'sound.'}]
    srt = render.captions(words, [{'src_in': 0.9, 'src_out': 3, 'zoom': 1.0}])
    assert 'They get broadcast-ready sound.' in srt


def test_video_graph_selects_each_piece_and_overlays_the_zoom():
    lines = render.video_graph(SEGS, 0.0, FACTS, preview=False)
    graph = ';'.join(lines)
    assert graph.count('between(t,') == 3  # two pieces selected, one zoomed stretch enabled
    assert 'crop=iw/1.08' in graph and 'overlay=0:0' in graph and graph.endswith('[v]')
    preview = ';'.join(render.video_graph(SEGS, 0.0, FACTS, preview=True))
    assert 'scale=1280:720' in preview


def test_audio_graph_fades_every_join_and_merges_contiguous_pieces():
    graph = ';'.join(render.audio_graph(SEGS, 0.5))
    assert graph.count('atrim=') == 2 and graph.count('afade=t=in') == 2
    assert re.search(r'atrim=start=0\.4000:end=1\.1000', graph)
    contiguous = [{'src_in': 1, 'src_out': 2, 'zoom': 1.08}, {'src_in': 2, 'src_out': 3, 'zoom': 1.0}]
    assert ';'.join(render.audio_graph(contiguous, 0)).count('atrim=') == 1
