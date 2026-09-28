"""The 'judge' stage: an agent bins every clip of a stream against elgato/channel-guide.md.

One task per stream, so the judge can compare clips and find dupes. Very long streams are split into parts of
PART_CLIPS clips. The answer lands in judge.json ({clip id: verdict}) and on each clips.json entry as `judge`.
"""
import re
import textwrap

from . import tasks
from . import library as lib
from .pick import LINE

PART_CLIPS = 160


def guide_version():
    head = (lib.ELGATO / 'channel-guide.md').read_text(encoding='utf-8').splitlines()[0]
    m = re.search(r'\(v([\d.]+)', head)
    return m.group(1) if m else '?'


def anchors():
    """Clips staff approved in the anchor half of the benchmark: {clip key: approved file name}."""
    split = lib.read_json(lib.ELGATO / 'benchmark' / 'split.json', {})
    return {a['key']: a['approved'] for a in split.get('anchor', [])}


def clip_text(sentences, clip):
    """Words spoken in the clip, from the (corrected) sentence lines between its first and last sentence."""
    start, last = round(clip.get('start', clip['hook_at']), 2), round(clip.get('last', clip['source_out']), 2)
    lines = [text for t, text in sentences if start <= t <= last]
    if lines and clip.get('start_word'):
        want = re.sub(r'\W', '', clip['start_word'].lower())
        words = lines[0].split()
        for i, w in enumerate(words):
            if re.sub(r'\W', '', w.lower()) == want:
                lines[0] = ' '.join(words[i:])
                break
    return ' '.join(lines)


def _sentences(stream):
    text = stream.path('sentences.txt').read_text(encoding='utf-8')
    out = []
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            out.append((round(float(m.group(2)), 2), m.group(3)))
    return out


def packet(stream, clips, part=None):
    sentences, marked = _sentences(stream), anchors()
    out = [f'STREAM: {stream.title}', f'DATE: {stream.date}   STREAM ID: {stream.id}   CLIPS: {len(clips)}'
           + (f'   (part {part})' if part else ''), '']
    for c in clips:
        tag = f'   [APPROVED EXAMPLE: staff posted "{marked[c["key"]]}"]' if c['key'] in marked else ''
        flags = ', '.join(f for f in c.get('flags', []) if f not in ('preroll-speech', 'long-preroll')) or '-'
        out += [f"## {c['id']}  {lib.hms(c['hook_at'])}-{lib.hms(c['source_out'])}  ({c['duration']:.0f}s){tag}",
                f"picker: {c.get('category')} | {c.get('product')} | {c.get('score')}* | "
                f"speakers: {c.get('speakers', '')} | flags: {flags}",
                f"title: {c.get('title', '')}", f"summary: {c.get('summary', '')}",
                *textwrap.wrap('text: ' + clip_text(sentences, c), 700), '']
    return '\n'.join(out)


def open_tasks(stream):
    clips = stream.clips()
    if not clips:
        return []
    instructions = tasks.prompt('judge') + (lib.ELGATO / 'channel-guide.md').read_text(encoding='utf-8')
    chunks = [clips[i:i + PART_CLIPS] for i in range(0, len(clips), PART_CLIPS)]
    ids = []
    for n, chunk in enumerate(chunks, 1):
        name = f'p{n}' if len(chunks) > 1 else ''
        ids.append(tasks.create('judge', stream.id, name, instructions,
                                packet(stream, chunk, f'{n} of {len(chunks)}' if len(chunks) > 1 else None),
                                keys=[c['key'] for c in chunk], meta={'guide': guide_version()}))
    return ids


def check(task, output):
    want = [k.split('/', 1)[1] for k in task['keys']]
    got = [v['id'] for v in output]
    errors = []
    if got != want:
        missing = [i for i in want if i not in got]
        extra = [i for i in got if i not in want]
        errors.append(f'expected {len(want)} answers in input order; got {len(got)}'
                      + (f'; missing {missing[:10]}' if missing else '') + (f'; unknown {extra[:10]}' if extra else ''))
    ids = set(want)
    for i, v in enumerate(output):
        if (v['bin'] == 'dupe') != bool(v['dupe_of']):
            errors.append(f"{i} ({v['id']}): dupe_of must be set exactly when bin is 'dupe'")
        if v['dupe_of'] and v['dupe_of'] not in ids:
            errors.append(f"{i} ({v['id']}): dupe_of {v['dupe_of']!r} is not a clip in this input")
        if v['merge'] and any(m not in ids for m in v['merge']):
            errors.append(f"{i} ({v['id']}): merge lists ids that aren't in this input")
        if v['post'] and not (v['side'] == 'community' and v['bin'] == 'top'):
            errors.append(f"{i} ({v['id']}): post is only for community top clips")
        if v['side'] == 'community' and v['bin'] == 'top' and not v['post']:
            errors.append(f"{i} ({v['id']}): community top clips need a draft X post")
    return errors[:40]


def apply_task(task, output):
    stream = lib.get_stream(task['stream'])
    verdicts = {v['id']: {k: v[k] for k in ('side', 'bin', 'stars', 'reason', 'dupe_of', 'merge', 'post')}
                for v in output}
    with lib.locked(stream.path('clips.json')):
        judged = stream.load('judge.json', {})
        judged.update(verdicts)
        stream.save('judge.json', judged)
        clips = stream.clips()
        for c in clips:
            if c['id'] in verdicts:
                c['judge'] = {**verdicts[c['id']], 'guide': task.get('guide')}
        stream.save('clips.json', clips)
