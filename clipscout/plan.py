"""The 'plan' stage: resolve the picker's clips to cut points over the source video.

No clip files are written: a clip is its cut points, and render.py makes files later. For each pick in
picks.json this finds:
  hook_at     the first word of the hook (the pick's first sentence, advanced to `start_word` when given)
  source_out  just after the last word of the final sentence: the natural trailing pause, stopping 80 ms before
              the next word, at most 1.5 s of tail
  key_in      the last video keyframe at or before the hook, for lossless (stream-copy) export; the words between
              key_in and hook_at are `preroll_words` and give the `preroll-speech` / `long-preroll` flags
`raw` picks (speechless moments) use their start/last seconds as given. Clip ids stay stable across re-plans,
and fields added by later stages (judge, music, parked...) are carried over for the same id. Merged clips (added
by the app, with `merged_from: [clip id...]` and no pick behind them) are kept and re-spanned from their parts,
or dropped when a part no longer exists.
Writes clips.json (under its lock: judge and the app write it too) and thumbs/<clip id>.jpg (a frame 1 s after
the hook).
"""
import re
import struct
import subprocess
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor

from . import elgato
from . import library as lib

TAIL_MAX, TAIL_GUARD = 1.5, 0.08
THUMB_WIDTH = 480
PICK_KEYS = {'start', 'last', 'start_word', 'raw', 'category', 'product', 'title', 'hook', 'summary', 'speakers',
             'score', 'flags', 'yt_titles', 'yt_description'}
PLAN_KEYS = {'id', 'key', 'hook_at', 'source_out', 'duration', 'key_in', 'preroll_s', 'preroll_words', 'topic',
             'source_url'}


KEY_BEFORE, KEY_AFTER = 12.0, 15.0  # keyframe search window around a pick's first sentence


def _windows(times):
    spans = sorted((max(0.0, t - KEY_BEFORE), t + KEY_AFTER) for t in times)
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def keyframes(stream, near=()):
    """Video keyframe times (seconds from the start of the file) near the given times, cached in keyframes.json.

    Scanning a whole multi-hour file reads every byte of it, so only windows around each pick are read
    (`-read_intervals`). keyframes.json is either a full list (older streams) or {"windows", "keys"}."""
    cached = stream.load('keyframes.json')
    if isinstance(cached, list):
        return cached
    cached = cached or {'windows': [], 'keys': []}
    have = cached['windows']
    missing = [w for w in _windows(near) if not any(a <= w[0] and w[1] <= b for a, b in have)]
    if not missing:
        return cached['keys']
    src = str(stream.media)
    start = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=start_time', '-of', 'csv=p=0', src],
                           capture_output=True, text=True).stdout.strip()
    start = float(start) if start and start != 'N/A' else 0.0
    keys = set(cached['keys'])
    for i in range(0, len(missing), 200):  # keep the command line short
        intervals = ','.join(f'{a + start:.3f}%{b + start:.3f}' for a, b in missing[i:i + 200])
        out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-read_intervals', intervals,
                              '-show_entries', 'packet=pts_time,flags', '-of', 'csv=p=0', src],
                             capture_output=True, text=True).stdout
        keys |= {round(float(t) - start, 3) for t, f, *_ in (line.split(',') for line in out.splitlines()
                                                              if ',' in line) if 'K' in f and t != 'N/A'}
    cached = {'windows': sorted(have + missing), 'keys': sorted(keys)}
    stream.save('keyframes.json', cached)
    return cached['keys']


def sentence_end(words, i):
    """Index of the last word of the sentence starting at word i (same rule as the sentences view)."""
    j = i
    while j + 1 < len(words):
        if words[j]['word'].rstrip().endswith(('.', '?', '!')) or words[j + 1]['start'] - words[j]['end'] > 1.2:
            break
        j += 1
    return j


def nearest_word(starts, t):
    return max(bisect_right(starts, t + 0.05) - 1, 0)


def _norm(word):
    return re.sub(r'\W', '', word.lower())


def resolve(pick, words, starts, keys):
    """Cut points for one pick: {hook_at, source_out, key_in, preroll_words}."""
    a = nearest_word(starts, pick['start'])
    if pick.get('start_word'):  # the hook begins mid-line: advance to the named word within that sentence
        want = _norm(pick['start_word'])
        for j in range(a, sentence_end(words, a) + 1):
            if _norm(words[j]['word']) == want:
                a = j
                break
    b = sentence_end(words, nearest_word(starts, pick['last']))
    hook_t, last_end = words[a]['start'], words[b]['end']
    nxt = words[b + 1]['start'] if b + 1 < len(words) else last_end + TAIL_MAX
    out_t = min(last_end + TAIL_MAX, max(last_end + 0.05, nxt - TAIL_GUARD))
    if pick.get('raw'):  # a speechless moment: start/last are plain seconds
        hook_t, out_t = pick['start'], pick['last']
    k = keys[max(bisect_right(keys, hook_t - 0.02) - 1, 0)] if keys else 0.0
    return {'hook_at': round(hook_t, 3), 'source_out': round(out_t, 3), 'key_in': k}


def preroll(words, key_in, hook_at):
    return [w['word'].strip() for w in words if key_in <= w['start'] < hook_at]


def source_url(stream, t):
    src = stream.meta.get('source') or {}
    kind, sid, t = src.get('kind'), stream.id, max(int(t), 0)
    if kind == 'twitch' or sid.startswith('tw'):
        vid = re.sub(r'\D', '', str(src.get('id') or '')) or sid[2:]
        return f'https://www.twitch.tv/videos/{vid}?t={t // 3600}h{t % 3600 // 60}m{t % 60}s'
    if kind == 'youtube' or sid.startswith('yt'):
        vid = src.get('id') or sid[2:]
        return f'https://www.youtube.com/watch?v={vid}&t={t}s'
    return None


def music_flags(clip, m):
    """Measured music replaces the picker's transcript-based guess (thresholds from the year set's review)."""
    clip['music'] = {'share': m['share'], 'peak': m['peak']}
    flags = [f for f in clip.get('flags', []) if f not in ('music', 'music-faint')]
    if m['share'] >= 0.2 or m['peak'] >= 0.4:
        flags.append('music')
    elif m['peak'] >= 0.2:
        flags.append('music-faint')
    clip['flags'] = flags


def build(stream, picks, words, keys, previous=()):
    """clips.json entries for the picks, sorted by hook time, carrying over later stages' fields by id."""
    starts = [w['start'] for w in words]
    prev = {c['id']: c for c in previous if not c.get('merged_from')}
    music = stream.load('music.json', {})
    rows = []
    for p in picks:
        r = resolve(p, words, starts, keys)
        rows.append((r['hook_at'], r['source_out'], p, r))
    rows.sort(key=lambda row: (row[0], row[1]))
    clips, taken = [], set()
    for hook_at, out_t, p, r in rows:
        cid = lib.clip_id(hook_at, taken)
        taken.add(cid)
        old = prev.get(cid, {})
        k = old['key_in'] if old.get('hook_at') == hook_at and 'key_in' in old else r['key_in']
        pre = preroll(words, k, hook_at)
        flags = [f for f in p.get('flags', []) if f not in ('preroll-speech', 'long-preroll')]
        flags += (['preroll-speech'] if pre else []) + (['long-preroll'] if hook_at - k > 2.5 else [])
        clip = {k2: v for k2, v in old.items() if k2 not in PICK_KEYS | PLAN_KEYS}
        clip.update({'id': cid, 'key': f'{stream.id}/{cid}'})
        clip.update({k2: v for k2, v in p.items() if k2 in PICK_KEYS})
        clip.update({'flags': flags, 'hook_at': hook_at, 'source_out': out_t, 'duration': round(out_t - hook_at, 2),
                     'key_in': k, 'preroll_s': round(hook_at - k, 2), 'preroll_words': ' '.join(pre),
                     'topic': elgato.topic(p.get('product', '')), 'source_url': source_url(stream, k)})
        if cid in music:
            music_flags(clip, music[cid])
        clips.append(clip)
    clips += merged(stream, previous, {c['id']: c for c in clips}, taken)
    clips.sort(key=lambda c: (c['hook_at'], c['source_out']))
    return clips


def merged(stream, previous, by_id, taken):
    """Merged clips from `previous`, re-spanned from the first part's hook to the last part's out point."""
    out = []
    for old in previous:
        if not old.get('merged_from'):
            continue
        parts = [by_id.get(p) for p in old['merged_from']]
        if not parts or not all(parts):
            continue
        first = min(parts, key=lambda c: c['hook_at'])
        last = max(parts, key=lambda c: c['source_out'])
        cid = old['id'] if old['id'] not in taken else lib.clip_id(first['hook_at'], taken)
        taken.add(cid)
        m = dict(old)
        m.update({'id': cid, 'key': f'{stream.id}/{cid}', 'hook_at': first['hook_at'], 'source_out': last['source_out'],
                  'duration': round(last['source_out'] - first['hook_at'], 2), 'key_in': first['key_in'],
                  'preroll_s': first['preroll_s'], 'preroll_words': first['preroll_words'],
                  'source_url': source_url(stream, first['key_in'])})
        out.append(m)
    return out


def jpeg_width(path):
    """Width from a JPEG's SOF header, or 0 if unreadable."""
    try:
        data = path.read_bytes()
    except OSError:
        return 0
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0xC0, 0xC1, 0xC2):
            return struct.unpack('>H', data[i + 7:i + 9])[0]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + struct.unpack('>H', data[i + 2:i + 4])[0]
    return 0


def thumbnail(src, clip, out):
    at = min(clip['hook_at'] + 1.0, max(clip['source_out'] - 0.2, clip['hook_at']))
    tmp = out.with_suffix('.tmp.jpg')
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{at:.3f}', '-i', str(src), '-frames:v', '1',
                        '-vf', f'scale={THUMB_WIDTH}:-2', '-q:v', '4', str(tmp)], capture_output=True)
    if r.returncode or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(out)
    return True


def thumbnails(stream, clips, progress=None, workers=6):
    """Write thumbs/<clip id>.jpg for clips that lack one at full width. Returns (made, failed)."""
    folder = stream.path('thumbs')
    folder.mkdir(exist_ok=True)
    todo = [c for c in clips if jpeg_width(folder / f"{c['id']}.jpg") < THUMB_WIDTH]
    made = failed = 0
    if not todo or not stream.media or not stream.media.exists():
        return made, len(todo) if todo else 0
    with ThreadPoolExecutor(workers) as pool:
        for n, ok in enumerate(pool.map(lambda c: thumbnail(stream.media, c, folder / f"{c['id']}.jpg"), todo), 1):
            made += ok
            failed += not ok
            if progress:
                progress(0.2 + 0.8 * n / len(todo), f'thumbnails {n}/{len(todo)}')
    return made, failed


def run(stream, progress=lambda f, note='': None):
    picks = stream.load('picks.json', [])
    words = stream.words()
    if picks and not words:
        raise RuntimeError('picks.json has clips but transcript.json has no words')
    keys = keyframes(stream, [p['start'] for p in picks]) if picks else []
    progress(0.1, 'cut points')
    with lib.locked(stream.path('clips.json')):
        clips = build(stream, picks, words, keys, stream.clips())
        stream.save('clips.json', clips)
    progress(0.2, f'{len(clips)} clips')
    made, failed = thumbnails(stream, clips, progress)
    if failed:
        progress(1.0, f'{failed} thumbnails failed')
