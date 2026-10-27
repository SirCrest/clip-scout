"""The library on disk: one folder per stream, plus shared state and agent tasks.

library/
  settings.json                     which agent runs tasks, and its options
  decisions.json                    reviewers' Keep/Maybe/Cut, keyed "<stream id>/<clip id>"
  streams/<date>_<stream id>/
    stream.json                     id, title, date, source, media, duration, stages
    source.<ext>                    the stream video
    transcript.json                 {"model", "duration", "processed", "complete", "segments": [{start, end, text,
                                     words: [{start, end, word, p}]}]}
    sentences.txt                   one sentence per line: "[HH:MM:SS  1637.71]  text", "   ~ pause 2.4s"
    corrections.json                [{t, from, to}]  transcript fixes (t = sentence start as printed)
    picks.json                      the picker's clips (schema: clipscout/tasks/schemas/pick.json)
    keyframes.json                  video keyframe times, for lossless cuts
    clips.json                      [clip]  picks resolved to source times, one per clip, see plan.py
    judge.json                      {clip id: {side, bin, stars, reason, dupe_of, merge, post}}
    music.json                      {clip id: {share, peak}}
    thumbs/<clip id>.jpg
  tasks/<task id>/                  work for an agent: task.json, TASK.md, input.txt, output.json

Stream ids: "tw<twitch id>", "yt<youtube id>", or "f<hash>" for a local file. Clip ids are the hook time in
tenths of a second ("t016377" starts at 1637.7 s), with a letter suffix when two clips share a hook, so they
stay stable when a stream is re-planned. A clip's global key is "<stream id>/<clip id>".
"""
import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = Path(os.environ.get('CLIPSCOUT_LIBRARY', ROOT / 'library'))
STREAMS = LIBRARY / 'streams'
TASKS = LIBRARY / 'tasks'
ELGATO = ROOT / 'elgato'
UV = 'uv/uv.exe' if (ROOT / 'uv' / 'uv.exe').exists() else 'uv'  # for commands we show: a release has its own uv

STAGES = ('fetch', 'transcribe', 'pick', 'plan', 'music', 'judge')
AGENT_STAGES = ('pick', 'judge')


def now():
    return datetime.now().isoformat(timespec='seconds')


def read_json(path, default=None):
    path = Path(path)
    for attempt in range(50):  # Windows refuses a read while another process is replacing the file
        if not path.exists():
            return default
        try:
            text = path.read_text(encoding='utf-8-sig')
            break
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.05)
    return json.loads(text) if text.strip() else default


def write_json(path, value, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False, suffix='.tmp') as f:
        json.dump(value, f, ensure_ascii=False, indent=indent)
        f.write('\n')
    for attempt in range(40):  # Windows: a reader may hold the target open for a moment
        try:
            os.replace(f.name, path)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(f.name, path)


@contextmanager
def locked(path, timeout=30):
    """Cross-process lock: a sibling '<name>.lock' file created exclusively."""
    lock = Path(str(path) + '.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            if time.time() - lock.stat().st_mtime > 300:  # stale: its process died mid-write
                lock.unlink(missing_ok=True)
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f'lock held: {lock}')
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def stream_id(kind, ref):
    if kind == 'twitch':
        return 'tw' + re.sub(r'\D', '', str(ref))
    if kind == 'youtube':
        return 'yt' + str(ref)
    return 'f' + hashlib.sha1(str(ref).encode()).hexdigest()[:10]


def clip_id(hook_at, taken=()):
    base = f't{int(round(hook_at * 10)):06d}'
    cid, n = base, 0
    while cid in taken:
        n += 1
        cid = base + chr(ord('a') + n)
    return cid


def hms(t):
    t = int(t)
    return f'{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}'


class Stream:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.meta = read_json(self.folder / 'stream.json')
        if self.meta is None:
            raise FileNotFoundError(f'no stream.json in {self.folder}')

    def __repr__(self):
        return f'<Stream {self.id} {self.title[:40]!r}>'

    id = property(lambda self: self.meta['id'])
    title = property(lambda self: self.meta.get('title', ''))
    date = property(lambda self: self.meta.get('date', ''))

    def path(self, name):
        return self.folder / name

    @property
    def media(self):
        return self.folder / self.meta['media'] if self.meta.get('media') else None

    def reload(self):
        self.meta = read_json(self.folder / 'stream.json')
        return self

    def update(self, fn):
        """Read-modify-write stream.json under a lock; fn mutates the dict in place."""
        with locked(self.folder / 'stream.json'):
            meta = read_json(self.folder / 'stream.json')
            fn(meta)
            write_json(self.folder / 'stream.json', meta)
            self.meta = meta

    def stage(self, name):
        return self.meta.setdefault('stages', {}).get(name, {'state': 'pending'})

    def set_stage(self, name, state, **extra):
        def fn(meta):
            entry = {'state': state, 'at': now(), **extra}
            meta.setdefault('stages', {})[name] = entry
        self.update(fn)

    def load(self, name, default=None):
        return read_json(self.folder / name, default)

    def save(self, name, value):
        write_json(self.folder / name, value)

    def words(self):
        data = self.load('transcript.json', {})
        return [w for s in data.get('segments', []) for w in s.get('words', [])]

    def clips(self):
        return self.load('clips.json', [])


def create_stream(sid, title, date, source, media=None, duration=None):
    folder = STREAMS / f'{date}_{sid}'
    folder.mkdir(parents=True, exist_ok=True)
    meta = {'id': sid, 'title': title, 'date': date, 'source': source, 'media': media, 'duration': duration,
            'added': now(), 'stages': {}}
    write_json(folder / 'stream.json', meta)
    return Stream(folder)


def get_stream(sid):
    hits = sorted(STREAMS.glob(f'*_{sid}'))
    if not hits:
        raise KeyError(f'no stream {sid!r} in {STREAMS}')
    return Stream(hits[0])


def all_streams():
    if not STREAMS.exists():
        return []
    return [Stream(p) for p in sorted(STREAMS.iterdir()) if (p / 'stream.json').exists()]
