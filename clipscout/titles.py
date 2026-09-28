"""The 'titles' task: an agent writes the YouTube copy for kept clips (A/B/C titles, description, tags, playlist).

Batches of up to BATCH kept staff clips from one stream per task. The answer becomes a draft in
library/publish.json (see publish.py); a draft never replaces copy someone approved or already published.
Clip Scout, not the agent, adds the "Watch the full stream" line, the channel boilerplate and the hashtags line,
so those stay exactly the same on every video.
"""
import hashlib
import json
import re

from . import elgato, judge, tasks
from . import library as lib

BATCH = 10
URL = re.compile(r'https?://[^\s)\]]+')
BOILERPLATE = """▼ Connect with Elgato:

Main YouTube: https://www.youtube.com/@elgato
Twitter: http://www.twitter.com/elgato
Instagram: http://www.instagram.com/elgato
Facebook: http://www.facebook.com/elgato
YouTube: http://www.youtube.com/elgato
Discord: http://discord.gg/elgato"""
EXTRA_PLAYLISTS = ('CES 2026',)


def links():
    return json.loads((lib.ELGATO / 'links.json').read_text(encoding='utf-8'))


def links_for(topic):
    data = links()
    return {**data['topics'].get(topic, {}), **data['general']}


def allowed_urls():
    data = links()
    urls = set(data['general'].values()) | set(data['boilerplate'])
    for group in data['topics'].values():
        urls |= set(group.values())
    return {u.rstrip('/') for u in urls}


def playlists():
    return [t for t in elgato.topics() if t != 'Community'] + list(EXTRA_PLAYLISTS)


def compose(body, source_url, hashtags=()):
    """The full description as uploaded: the agent's text, the full-stream line, boilerplate, hashtags."""
    parts = [body.strip()]
    if source_url:
        parts.append(f'Watch the full stream: {source_url}')
    parts.append(BOILERPLATE)
    if hashtags:
        parts.append(' '.join(hashtags))
    return '\n\n'.join(parts)


def tags_length(tags):
    """YouTube's count: commas between tags count, and a tag with a space counts as if quoted."""
    return sum(len(t) + (2 if ' ' in t else 0) for t in tags) + max(len(tags) - 1, 0)


def _clip(key):
    sid, cid = key.split('/', 1)
    stream = lib.get_stream(sid)
    clip = next((c for c in stream.clips() if c['id'] == cid), None)
    if clip is None:
        raise KeyError(f'no clip {key}')
    return stream, clip


def _block(stream, sentences, clip):
    j = clip.get('judge') or {}
    topic = clip.get('topic') or elgato.topic(clip.get('product'))
    flags = ', '.join(f for f in clip.get('flags', []) if f not in ('preroll-speech', 'long-preroll')) or '-'
    link_lines = [f'  {label}: {url}' for label, url in links_for(topic).items()]
    drafts = [f'  {n}) {t}' for n, t in enumerate(clip.get('yt_titles') or [], 1)]
    return '\n'.join([
        f"## {clip['id']}  ({clip.get('product')}, {lib.hms(clip.get('duration', 0))[3:]} long)",
        f"stream: {stream.title} ({stream.date})",
        f"topic / suggested playlist: {topic if topic in playlists() else 'Setup and tips'}",
        f"judge: {j.get('bin', '-')} {j.get('stars', '-')}* {j.get('side', 'staff')}: {j.get('reason', '')}",
        f"flags: {flags}",
        f"picker's title: {clip.get('title', '')}",
        "picker's draft titles:", *drafts,
        f"picker's draft description: {clip.get('yt_description', '')}",
        "links you may use:", *link_lines,
        f"full stream link (Clip Scout adds it): {clip.get('source_url') or 'none'}",
        f"words: {judge.clip_text(sentences, clip)}", ''])


def _busy_keys():
    busy = set()
    for t in tasks.list_tasks(kind='titles'):
        if t['state'] in ('open', 'claimed'):
            busy |= set(t['keys'])
    return busy


def open_tasks_for(keys, force=False):
    """Open titles tasks for kept staff clips. Skips community clips (they go to X), clips already in an open
    task, and, unless force, clips that already have publish copy."""
    from . import publish
    drafted = publish.load() if not force else {}
    busy = _busy_keys()
    by_stream = {}
    for key in dict.fromkeys(keys):
        if key in busy or key in drafted:
            continue
        try:
            stream, clip = _clip(key)
        except KeyError:
            continue
        if (clip.get('judge') or {}).get('side') == 'community':
            continue
        by_stream.setdefault(stream.id, (stream, []))[1].append(clip)
    instructions = (tasks.prompt('titles') + (lib.ELGATO / 'youtube.md').read_text(encoding='utf-8')
                    + '\n## Product names\nWrite Elgato product names exactly as in this list, and never name a '
                      'product that isn\'t in it: ' + ', '.join(elgato.products()) + '.\n')
    ids = []
    for sid, (stream, clips) in by_stream.items():
        clips.sort(key=lambda c: c['hook_at'])
        sentences = judge._sentences(stream)
        for i in range(0, len(clips), BATCH):
            batch = clips[i:i + BATCH]
            batch_keys = [c['key'] for c in batch]
            name = 'b' + hashlib.sha1(','.join(batch_keys).encode()).hexdigest()[:8]
            head = [f'STREAM: {stream.title}', f'DATE: {stream.date}   STREAM ID: {sid}   CLIPS: {len(batch)}', '']
            packet = '\n'.join(head) + '\n'.join(_block(stream, sentences, c) for c in batch)
            ids.append(tasks.create('titles', sid, name, instructions, packet, keys=batch_keys))
    return ids


def check(task, output):
    want = [k.split('/', 1)[1] for k in task['keys']]
    got = [a['id'] for a in output]
    if got != want:
        return [f'expected {len(want)} answers in input order ({", ".join(want)}); got {", ".join(got) or "none"}']
    allowed, known_playlists = allowed_urls(), set(playlists())
    errors = []
    for i, (a, key) in enumerate(zip(output, task['keys'])):
        where = f"{i} ({a['id']})"
        if len({t.strip().casefold() for t in a['titles']}) < 3:
            errors.append(f'{where}: the three titles must be different')
        for url in URL.findall(a['description']):
            if url.rstrip('/.,') not in allowed:
                errors.append(f'{where}: {url} is not one of the listed links; use only those')
        if 'Connect with Elgato' in a['description'] or 'full stream' in a['description'].lower():
            errors.append(f'{where}: leave the full-stream line and the Connect with Elgato block out; '
                          'Clip Scout adds them')
        if tags_length(a['tags']) > 500:
            errors.append(f'{where}: tags are over 500 characters by YouTube\'s count')
        if a['playlist'] not in known_playlists:
            errors.append(f"{where}: playlist {a['playlist']!r} is not one of: {', '.join(sorted(known_playlists))}")
        if a['hold'] and not a['note']:
            errors.append(f'{where}: say in note what to check when hold is set')
        try:
            _, clip = _clip(key)
        except KeyError:
            continue
        full = compose(a['description'], clip.get('source_url'), a.get('hashtags') or [])
        if len(full.encode('utf-8')) > 5000:
            errors.append(f'{where}: the description is over 5,000 bytes once the boilerplate is added; shorten it')
    return errors[:40]


def apply_task(task, output):
    from . import publish
    drafts = {}
    for a, key in zip(output, task['keys']):
        _, clip = _clip(key)
        measured = [f for f in clip.get('flags', []) if f in ('music', 'music-faint', 'dated', 'verify-claim',
                                                             'profanity', 'guest-creator', 'third-party')]
        drafts[key] = {
            'titles': a['titles'],
            'description': compose(a['description'], clip.get('source_url'), a.get('hashtags') or []),
            'body': a['description'],
            'hashtags': a.get('hashtags') or [],
            'tags': a['tags'],
            'playlist': a['playlist'],
            'category_id': publish.CATEGORY_ID,
            'warnings': sorted(set(a['hold']) | set(measured)),
            'note': a['note'],
            'task': task['id'],
        }
    publish.save_drafts(drafts)
