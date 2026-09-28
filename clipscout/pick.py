"""The 'pick' stage: an agent reads the stream's sentences and returns transcript corrections plus clip picks.

Long streams are split into parts of about PART_CHARS characters (~50k tokens), each with a few minutes of
trailing context so clips near a boundary can end cleanly. Every part is its own task; answers are kept in
picks.parts/<part>.json and merged into picks.json and corrections.json as they arrive.
"""
import re

from . import elgato, tasks
from . import library as lib

PART_CHARS = 60_000  # ~15k tokens, ~40 min of talk: small enough that any agent reads a part in full
GAP_MAX, GAP_WORDS = 480, 700  # a stretch this long and this talky with no pick needs a pick or a reason
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


NEAR = 3  # lines either side where an off-by-one timestamp is fixed rather than rejected


def _nearby(order, index, t, test):
    """The start time of the closest line within NEAR lines of t whose text passes test, or None."""
    i = index.get(t)
    if i is None:
        return None
    for d in range(1, NEAR + 1):
        for j in (i - d, i + d):
            if 0 <= j < len(order) and test(order[j][1]):
                return order[j][0]
    return None


def _word_in(line, word):
    return re.sub(r'\W', '', word.lower()) in [re.sub(r'\W', '', w.lower()) for w in line.split()]


def check(task, output):
    """Reject answers that point at lines that don't exist. A correction or start word that sits a line or two
    away from the timestamp given is moved to its line (agents often copy the neighbouring timestamp)."""
    text = (tasks.folder(task['id']) / 'input.txt').read_text(encoding='utf-8')
    order = parse_sentences(text)
    lines, index = dict(order), {t: i for i, (t, _) in enumerate(order)}
    lo, hi = task.get('range', [0, None])
    known = set(elgato.products())
    errors = []
    for i, c in enumerate(output['corrections']):
        t = round(c['t'], 2)
        line = lines.get(t)
        if line is None:
            errors.append(f"corrections/{i}: t={c['t']} is not a sentence start in input.txt")
        elif c['from'] not in line:
            moved = _nearby(order, index, t, lambda s: c['from'] in s)
            if moved is None:
                errors.append(f"corrections/{i}: {c['from']!r} is not on line {c['t']} ({line[:80]!r})")
            else:
                c['t'] = moved
    for i, p in enumerate(output['picks']):
        if p.get('raw'):
            continue
        start, last = round(p['start'], 2), round(p['last'], 2)
        if p.get('start_word') and start in lines and not _word_in(lines[start], p['start_word']):
            moved = _nearby(order, index, start, lambda s: _word_in(s, p['start_word']))
            if moved is not None and (moved <= last):
                p['start'] = start = moved
        if start not in lines:
            errors.append(f'picks/{i}: start={p["start"]} is not a sentence start in input.txt')
        if last not in lines:
            errors.append(f'picks/{i}: last={p["last"]} is not a sentence start in input.txt')
        if start > last:
            errors.append(f'picks/{i}: start is after last')
        if hi is not None and start >= hi:
            errors.append(f'picks/{i}: starts in the context section (at or after {hi}); leave it out')
        if p.get('start_word') and start in lines and not _word_in(lines[start], p['start_word']):
            errors.append(f"picks/{i}: start_word {p['start_word']!r} is not on line {p['start']}")
        if p['product'] not in known:
            errors.append(f"picks/{i}: product {p['product']!r} is not in the product list")
        if p['score'] < 2:
            errors.append(f'picks/{i}: score 1 picks should be left out')
    errors += _gaps(order, text, lo, hi, output)
    return errors[:40]


def _gaps(order, text, lo, hi, output):
    """Long, talky stretches with no pick: agents sometimes skim past part of a transcript. Each needs picks or an
    entry in `skipped` saying why nothing there fits."""
    body = text.split('--- CONTEXT', 1)[0]
    mine = [(t, s) for t, s in parse_sentences(body) if hi is None or t < hi]
    if not mine:
        return []
    covered = sorted((round(p['start'], 2), round(p['last'], 2)) for p in output['picks'])
    skipped = [(s['from'], s['to']) for s in output.get('skipped', [])]
    errors, cursor = [], mine[0][0]
    for a, b in covered + [(mine[-1][0] + 1, mine[-1][0] + 1)]:
        if a - cursor > GAP_MAX:
            words = sum(len(s.split()) for t, s in mine if cursor < t < a)
            explained = any(sa <= cursor + 60 and sb >= a - 60 for sa, sb in skipped)
            if words >= GAP_WORDS and not explained:
                errors.append(f'no picks from {lib.hms(cursor)} ({cursor:.2f}) to {lib.hms(a)} ({a:.2f}): '
                              f'{(a - cursor) / 60:.0f} min and {words} words of talk. Read that stretch again and '
                              f'pick every moment that fits the guide; if truly nothing does, add '
                              f'{{"from": {cursor:.2f}, "to": {a:.2f}, "why": "..."}} to "skipped"')
        cursor = max(cursor, b)
    return errors


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
    if stream.path('transcript.json').exists():
        from .transcribe import write_sentences
        write_sentences(stream)
