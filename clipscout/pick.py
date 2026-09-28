"""The 'pick' stage: an agent reads the stream's sentences and returns transcript corrections plus clip picks.

Long streams are split into parts of about PART_CHARS characters (~50k tokens), each with a few minutes of
trailing context so clips near a boundary can end cleanly. Every part is its own task; answers are kept in
picks.parts/<part>.json and merged into picks.json and corrections.json as they arrive.
"""
import re

from . import elgato, tasks
from . import library as lib

PART_CHARS = 200_000
CONTEXT_S = 180
LINE = re.compile(r'^\[(\d\d:\d\d:\d\d)\s+([\d.]+)\]\s+(.*)$')
TEXT_FIELDS = ('title', 'hook', 'summary', 'speakers', 'yt_description')


def parse_sentences(text):
    """(t, text) for every sentence line of a sentences.txt body."""
    out = []
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            out.append((round(float(m.group(2)), 2), m.group(3)))
    return out


def _parts(lines, total_chars):
    """Split sentence-file lines into [(first index, end index)] of about PART_CHARS each, cutting at pauses."""
    if total_chars <= PART_CHARS * 1.3:
        return [(0, len(lines))]
    n_parts = -(-total_chars // PART_CHARS)
    target = total_chars / n_parts
    parts, start, size = [], 0, 0
    for i, line in enumerate(lines):
        size += len(line) + 1
        if size >= target and line.lstrip().startswith('~ pause') and len(parts) < n_parts - 1:
            parts.append((start, i + 1))
            start, size = i + 1, 0
    parts.append((start, len(lines)))
    return parts


def _time(line):
    m = LINE.match(line)
    return float(m.group(2)) if m else None


def open_tasks(stream):
    text = stream.path('sentences.txt').read_text(encoding='utf-8')
    head, _, body = text.partition('\n\n')
    lines = body.splitlines()
    parts = _parts(lines, len(body))
    guide = (lib.ELGATO / 'picking-guide.md').read_text(encoding='utf-8')
    instructions = tasks.prompt('pick') + guide
    ids = []
    for n, (a, b) in enumerate(parts, 1):
        times = [t for t in map(_time, lines[a:b]) if t is not None]
        lo = times[0] if times else 0.0
        hi = _time(lines[b]) if b < len(lines) and _time(lines[b]) is not None else None
        context = []
        if hi is not None:
            for line in lines[b:]:
                t = _time(line)
                if t is not None and t > hi + CONTEXT_S:
                    break
                context.append(line)
        header = [f"STREAM: {stream.title}", f"DATE: {stream.date}   ID: {stream.id}",
                  head.strip(),
                  f"PART {n} of {len(parts)}: sentences from {lib.hms(lo)} "
                  + (f"up to {lib.hms(hi)}. The lines after the CONTEXT marker are only context: pick clips that "
                     f"start before {hi:.2f}." if hi is not None else 'to the end of the stream.'), '']
        body_text = '\n'.join(lines[a:b])
        if context:
            body_text += '\n\n--- CONTEXT (do not start clips here) ---\n' + '\n'.join(context)
        ids.append(tasks.create('pick', stream.id, f'p{n}', instructions, '\n'.join(header) + body_text + '\n',
                                meta={'range': [lo, hi]}))
    return ids


def check(task, output):
    text = (tasks.folder(task['id']) / 'input.txt').read_text(encoding='utf-8')
    lines = dict(parse_sentences(text))
    lo, hi = task.get('range', [0, None])
    known = set(elgato.products())
    errors = []
    for i, c in enumerate(output['corrections']):
        line = lines.get(round(c['t'], 2))
        if line is None:
            errors.append(f"corrections/{i}: t={c['t']} is not a sentence start in input.txt")
        elif c['from'] not in line:
            errors.append(f"corrections/{i}: {c['from']!r} is not on line {c['t']} ({line[:80]!r})")
    for i, p in enumerate(output['picks']):
        if p.get('raw'):
            continue
        start, last = round(p['start'], 2), round(p['last'], 2)
        if start not in lines:
            errors.append(f'picks/{i}: start={p["start"]} is not a sentence start in input.txt')
        if last not in lines:
            errors.append(f'picks/{i}: last={p["last"]} is not a sentence start in input.txt')
        if start > last:
            errors.append(f'picks/{i}: start is after last')
        if hi is not None and start >= hi:
            errors.append(f'picks/{i}: starts in the context section (at or after {hi}); leave it out')
        if p.get('start_word') and start in lines:
            words = [re.sub(r'\W', '', w.lower()) for w in lines[start].split()]
            if re.sub(r'\W', '', p['start_word'].lower()) not in words:
                errors.append(f"picks/{i}: start_word {p['start_word']!r} is not on line {p['start']}")
        if p['product'] not in known:
            errors.append(f"picks/{i}: product {p['product']!r} is not in the product list")
        if p['score'] < 2:
            errors.append(f'picks/{i}: score 1 picks should be left out')
    return errors[:40]


def apply_task(task, output):
    stream = lib.get_stream(task['stream'])
    lib.write_json(stream.path('picks.parts') / f"{task['name']}.json", output)
    merge(stream)


def merge(stream):
    """Combine every part answered so far into picks.json and corrections.json."""
    picks, fixes, seen = [], [], set()
    for part in sorted(stream.path('picks.parts').glob('*.json')):
        data = lib.read_json(part)
        for f in data['corrections']:
            key = (round(f['t'], 2), f['from'])
            if key not in seen:
                seen.add(key)
                fixes.append({**f, 'to': elgato.fix_names(f['to'])})
        for p in data['picks']:
            for field in TEXT_FIELDS:
                p[field] = elgato.fix_names(p[field])
            p['yt_titles'] = [elgato.fix_names(t) for t in p['yt_titles']]
            picks.append(p)
    unique = {}
    for p in picks:  # parts overlap only in context, but guard against the same clip picked twice
        unique.setdefault((round(p['start'], 1), round(p['last'], 1), p.get('start_word')), p)
    stream.save('picks.json', sorted(unique.values(), key=lambda p: p['start']))
    stream.save('corrections.json', sorted(fixes, key=lambda f: f['t']))
    try:
        from .transcribe import write_sentences
    except ImportError:
        return
    write_sentences(stream)
