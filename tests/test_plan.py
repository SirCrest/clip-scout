from clipscout import plan


def w(start, end, word):
    return {'start': start, 'end': end, 'word': word, 'p': 0.9}


# "So yeah. Anyways I set up hotkeys. They work great!" then a long pause and "Next topic."
WORDS = [w(10.0, 10.2, ' So'), w(10.25, 10.5, ' yeah.'),
         w(11.0, 11.3, ' Anyways'), w(11.35, 11.5, ' I'), w(11.55, 11.8, ' set'), w(11.85, 12.0, ' up'),
         w(12.05, 12.6, ' hotkeys.'),
         w(12.9, 13.1, ' They'), w(13.15, 13.4, ' work'), w(13.45, 14.0, ' great!'),
         w(20.0, 20.3, ' Next'), w(20.35, 20.8, ' topic.')]
STARTS = [x['start'] for x in WORDS]
KEYS = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0]


class FakeStream:
    id = 'tw123'
    meta = {'source': {'kind': 'twitch', 'id': '123'}}

    def load(self, name, default=None):
        return default


def test_start_word_advances_to_hook():
    r = plan.resolve({'start': 11.0, 'last': 12.9, 'start_word': 'I'}, WORDS, STARTS, KEYS)
    assert r['hook_at'] == 11.35
    assert r['key_in'] == 10.0


def test_tail_guard_stops_before_next_word():
    # the sentence "I set up hotkeys." ends at 12.6; the next word starts at 12.9 -> out = 12.9 - 0.08
    r = plan.resolve({'start': 11.0, 'last': 11.0}, WORDS, STARTS, KEYS)
    assert r['source_out'] == 12.82


def test_tail_max_after_long_pause():
    # "They work great!" ends at 14.0, the next word is at 20.0 -> at most 1.5 s of tail
    r = plan.resolve({'start': 12.9, 'last': 12.9}, WORDS, STARTS, KEYS)
    assert r['source_out'] == 15.5


def test_raw_pick_uses_given_seconds():
    r = plan.resolve({'start': 15.0, 'last': 19.0, 'raw': True}, WORDS, STARTS, KEYS)
    assert (r['hook_at'], r['source_out'], r['key_in']) == (15.0, 19.0, 14.0)


def test_preroll_words_and_flags():
    clips = plan.build(FakeStream(), [{'start': 11.0, 'last': 12.9, 'start_word': 'I', 'product': 'Stream Deck',
                                       'flags': ['dated', 'preroll-speech']}], WORDS, KEYS)
    c = clips[0]
    assert c['preroll_words'] == 'So yeah. Anyways'
    assert c['flags'] == ['dated', 'preroll-speech']
    assert c['topic'] == 'Stream Deck'
    assert c['source_url'] == 'https://www.twitch.tv/videos/123?t=0h0m10s'


def test_ids_stable_and_collisions_suffixed():
    picks = [{'start': 12.9, 'last': 12.9}, {'start': 11.0, 'last': 11.0, 'start_word': 'I'},
             {'start': 11.0, 'last': 12.9, 'start_word': 'I'}]
    clips = plan.build(FakeStream(), picks, WORDS, KEYS)
    assert [c['id'] for c in clips] == ['t000114', 't000114b', 't000129']
    assert clips[0]['source_out'] < clips[1]['source_out']  # same hook: ordered by out point
    assert clips[1]['key'] == 'tw123/t000114b'


def test_later_stage_fields_carry_over():
    first = plan.build(FakeStream(), [{'start': 11.0, 'last': 11.0, 'title': 'old'}], WORDS, KEYS)
    first[0].update(judge={'bin': 'top'}, parked=False, key_in=9.5)
    again = plan.build(FakeStream(), [{'start': 11.0, 'last': 11.0, 'title': 'new'}], WORDS, KEYS, first)
    assert again[0]['id'] == first[0]['id']
    assert again[0]['judge'] == {'bin': 'top'} and again[0]['parked'] is False
    assert again[0]['title'] == 'new'
    assert again[0]['key_in'] == 9.5  # a measured in point survives while the hook is unchanged


def test_music_flags_replace_guess():
    c = {'flags': ['music', 'dated']}
    plan.music_flags(c, {'share': 0.0, 'peak': 0.25})
    assert c['flags'] == ['dated', 'music-faint']
    plan.music_flags(c, {'share': 0.3, 'peak': 0.1})
    assert c['flags'] == ['dated', 'music']
