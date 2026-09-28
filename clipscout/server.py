"""The Clip Scout app: a web server on 127.0.0.1 that serves the UI (web/), the library's media and a JSON API,
and runs three background threads: the pipeline, the agent worker, and the render queue for kept clips.

Only this machine can reach it. Requests must carry a localhost Host header (no DNS rebinding), and every write needs
the `X-Clip-Scout: 1` header, which a page on another site can't send without a CORS preflight we never allow.
"""
import asyncio
import json
import os
import re
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import agents, decisions, pipeline, tasks
from . import library as lib

WEB = lib.ROOT / 'web'
LOCAL = {'127.0.0.1', 'localhost'}
app = FastAPI(title='Clip Scout', docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def guard(request: Request, call_next):
    if (request.headers.get('host') or '').rsplit(':', 1)[0].strip('[]') not in LOCAL:
        return JSONResponse({'error': 'Clip Scout only answers on localhost'}, 403)
    if request.method in ('POST', 'PUT', 'DELETE'):
        origin = request.headers.get('origin')
        if request.headers.get('x-clip-scout') != '1' or origin and urlparse(origin).hostname not in LOCAL:
            return JSONResponse({'error': 'missing X-Clip-Scout header'}, 403)
    return await call_next(request)


# ---------------------------------------------------------------- catalog

def _nested(clips):
    """Mark clips whose whole range sits inside a longer top clip of the same stream (shown inside its card)."""
    tops = [c for c in clips if (c.get('judge') or {}).get('bin') == 'top']
    for c in clips:
        for p in tops:
            if p is not c and p['hook_at'] <= c['hook_at'] and c['source_out'] <= p['source_out'] + 0.5 \
                    and p['duration'] > c['duration']:
                c['_inside'] = p['key']
                break


def compact(stream, c):
    j = c.get('judge') or {}
    return {
        'key': c['key'], 'sid': stream.id, 'id': c['id'], 'title': c.get('title', ''), 'product': c.get('product'),
        'topic': c.get('topic'), 'category': c.get('category'), 'score': c.get('score'), 'stars': j.get('stars'),
        'bin': j.get('bin'), 'side': j.get('side'), 'reason': j.get('reason', ''), 'merge': j.get('merge'),
        'dupe_of': j.get('dupe_of'), 'hook': c['hook_at'], 'out': c['source_out'], 'dur': c['duration'],
        'flags': c.get('flags', []), 'speakers': c.get('speakers', ''), 'date': stream.date,
        'inside': c.get('_inside'), 'music': (c.get('music') or {}).get('share'),
    }


class Catalog:
    """Every stream's clips, reloaded only when a stream's clips.json or stream.json changes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}  # folder -> (mtimes, stream, clips)
        self.version = 0

    def _load(self):
        with self._lock:
            seen = set()
            for folder in sorted(lib.STREAMS.iterdir()) if lib.STREAMS.exists() else []:
                meta = folder / 'stream.json'
                if not meta.exists():
                    continue
                seen.add(folder)
                clips_file = folder / 'clips.json'
                mt = (meta.stat().st_mtime_ns, clips_file.stat().st_mtime_ns if clips_file.exists() else 0)
                if folder in self._cache and self._cache[folder][0] == mt:
                    continue
                stream = lib.Stream(folder)
                clips = stream.clips()
                _nested(clips)
                old = self._cache.get(folder)
                self._cache[folder] = (mt, stream, clips)
                if not old or old[0][1] != mt[1]:
                    self.version += 1
            for gone in set(self._cache) - seen:
                del self._cache[gone]
                self.version += 1
            return list(self._cache.values())

    def streams(self):
        return [s for _, s, _ in self._load()]

    def clips(self):
        return [compact(s, c) for _, s, cs in self._load() for c in cs]

    def find(self, key):
        sid, _, cid = key.partition('/')
        for _, s, cs in self._load():
            if s.id == sid:
                for c in cs:
                    if c['id'] == cid:
                        return s, c
        raise HTTPException(404, f'no clip {key}')

    def stream(self, sid):
        for s in self.streams():
            if s.id == sid:
                return s
        raise HTTPException(404, f'no stream {sid}')


catalog = Catalog()


# ---------------------------------------------------------------- background work

class Activity:
    def __init__(self):
        self.lines = deque(maxlen=300)
        self.seq = 0

    def say(self, text):
        self.seq += 1
        self.lines.append({'n': self.seq, 't': time.strftime('%H:%M:%S'), 'text': str(text)})


activity = Activity()


class Loop(threading.Thread):
    """Runs step() every `every` seconds, or sooner when poked."""

    def __init__(self, every):
        super().__init__(daemon=True)
        self.every = every
        self.wake = threading.Event()

    def poke(self):
        self.wake.set()

    def run(self):
        while True:
            try:
                self.step()
            except Exception as e:  # keep the app alive; the error shows in the activity feed
                activity.say(f'{type(self).__name__}: {type(e).__name__}: {e}')
            self.wake.wait(self.every)
            self.wake.clear()


class PipelineLoop(Loop):
    def step(self):
        if agents.settings().get('auto', True):
            pipeline.process(log=activity.say)


class AgentLoop(Loop):
    def __init__(self, every):
        super().__init__(every)
        self.worker = None

    def step(self):
        s = agents.settings()
        if not s.get('auto', True) or not tasks.list_tasks(state='open'):
            return
        if self.worker and self.worker.is_alive():
            return
        if s['agent'] != 'custom' and not agents.available().get(s['agent']):
            activity.say(f"Waiting for an agent: {s['agent']} isn't installed. Pick another in Settings.")
            return
        self.worker = agents.Worker(stop_when_idle=True, log=activity.say)
        self.worker.start()


def _safe(text, n=90):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', str(text or '')).replace('  ', ' ').strip().rstrip('.')
    return text[:n].rstrip(' .')


def render_path(stream, clip):
    side = (clip.get('judge') or {}).get('side') or 'staff'
    dest = 'X' if side == 'community' else 'YouTube'
    name = f"{_safe(clip.get('product'), 30)} - {_safe(clip.get('title'))} ({stream.date} {_safe(stream.title, 40)})"
    folder = lib.LIBRARY / 'approved' / dest / _safe(clip.get('topic') or 'Other', 40)
    return folder / (name[:180] + '.mp4')


class Renderer(Loop):
    """Renders kept clips with their edits. A clip waits while its agent edit task is still open, unless 'now'."""

    def __init__(self, every):
        super().__init__(every)
        self.queue = []  # [{key, now}]
        self.active = None
        self.lock = threading.Lock()

    @staticmethod
    def renders():
        return lib.read_json(lib.LIBRARY / 'renders.json', {})

    def enqueue(self, key, now=False):
        with self.lock:
            self.queue = [q for q in self.queue if q['key'] != key] + [{'key': key, 'now': now}]
        self.poke()

    def cancel(self, key):
        with self.lock:
            self.queue = [q for q in self.queue if q['key'] != key]

    def forget(self, key):
        """A clip is no longer kept: remove its render unless it was already sent to YouTube."""
        self.cancel(key)
        published = (lib.read_json(lib.LIBRARY / 'publish.json', {}) or {}).get(key, {})
        if published.get('status') not in (None, 'draft', 'approved'):
            return
        with lib.locked(lib.LIBRARY / 'renders.json'):
            renders = self.renders()
            entry = renders.pop(key, None)
            lib.write_json(lib.LIBRARY / 'renders.json', renders)
        if entry:
            for rel in (entry.get('path'), entry.get('srt')):
                if rel:
                    (lib.LIBRARY / rel).unlink(missing_ok=True)

    def state(self):
        with self.lock:
            return {'queued': [q['key'] for q in self.queue], 'active': self.active}

    AGENT_WAIT = 20 * 60

    def _edit_pending(self, key):
        """Wait for the agent's content edits, but only while an agent can actually do them, and not forever."""
        s = agents.settings()
        if not s.get('auto', True) or s['agent'] != 'custom' and not agents.available().get(s['agent']):
            return False
        sid = key.split('/')[0]
        now = time.time()
        for t in tasks.list_tasks(kind='edit', stream=sid):
            if key in t.get('keys', []) and t['state'] in ('open', 'claimed'):
                created = time.mktime(time.strptime(t['created'], '%Y-%m-%dT%H:%M:%S'))
                if now - created < self.AGENT_WAIT:
                    return True
        return False

    _last_stale = 0.0

    def _requeue_stale(self):
        """A kept clip whose edit plan changed after it was rendered (the agent's cuts arrived) renders again."""
        if time.monotonic() - self._last_stale < 20:
            return
        self._last_stale = time.monotonic()
        renders, queued = self.renders(), {q['key'] for q in self.queue}
        for key, v in decisions.load()['decisions'].items():
            r = renders.get(key)
            if v['d'] != 'keep' or not r or key in queued or not r.get('edl_mtime'):
                continue
            sid, _, cid = key.partition('/')
            try:
                edl_file = catalog.stream(sid).path('edits') / f'{cid}.json'
            except HTTPException:
                continue
            if edl_file.exists() and edl_file.stat().st_mtime_ns != r['edl_mtime']:
                self.enqueue(key)

    def step(self):
        """First give every queued clip its edit plan (which opens the agent's edit task), then render the ones
        whose edits are settled."""
        from . import edit, render
        self._requeue_stale()
        while True:
            with self.lock:
                queue = list(self.queue)
            ready = None
            for q in queue:
                try:
                    stream, clip = catalog.find(q['key'])
                except HTTPException:
                    self.cancel(q['key'])
                    continue
                if not edit.load_edl(stream, clip):
                    self.active = {'key': q['key'], 'progress': 0.0, 'stage': 'planning'}
                    activity.say(f'Planning edits for {clip.get("title", q["key"])}')
                    try:
                        edit.ensure(stream, clip)
                    except Exception as e:
                        activity.say(f'Edit planning failed for {q["key"]}: {e}')
                        self.cancel(q['key'])
                    self.active = None
                    agent_loop.poke()
                    continue
                if q['now'] or not self._edit_pending(q['key']):
                    ready = (q, stream, clip)
                    break
            if not ready:
                return
            q, stream, clip = ready
            self.cancel(q['key'])
            key = q['key']
            out = render_path(stream, clip)
            out.parent.mkdir(parents=True, exist_ok=True)
            self.active = {'key': key, 'progress': 0.0, 'stage': 'rendering'}
            activity.say(f'Rendering {clip.get("title", key)}')

            def progress(fraction):
                self.active = {'key': key, 'progress': round(fraction, 3), 'stage': 'rendering'}
            try:
                render.render_clip(stream, clip, out, progress=progress)
            except Exception as e:
                activity.say(f'Render failed for {key}: {e}')
                self.active = None
                continue
            edl_file = stream.path('edits') / f"{clip['id']}.json"
            with lib.locked(lib.LIBRARY / 'renders.json'):
                renders = self.renders()
                renders[key] = {'path': out.relative_to(lib.LIBRARY).as_posix(),
                                'srt': out.with_suffix('.srt').relative_to(lib.LIBRARY).as_posix(),
                                'rendered_at': lib.now(), 'lossless': False,
                                'edl_mtime': edl_file.stat().st_mtime_ns if edl_file.exists() else None}
                lib.write_json(lib.LIBRARY / 'renders.json', renders)
            self.active = None
            activity.say(f'Ready: {out.name}')


pipeline_loop, agent_loop, renderer = PipelineLoop(3), AgentLoop(3), Renderer(2)


# ---------------------------------------------------------------- API

async def body(request):
    try:
        return await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, 'expected a JSON body')


def overview():
    streams = []
    kept = {k for k, v in decisions.load()['decisions'].items() if v['d'] == 'keep'}
    rendered = set(Renderer.renders())
    for _, s, cs in catalog._load():
        streams.append({
            'id': s.id, 'title': s.title, 'date': s.date, 'duration': s.meta.get('duration'),
            'source': {k: s.meta.get('source', {}).get(k) for k in ('kind', 'url')},
            'stages': {n: s.stage(n) for n in lib.STAGES},
            'clips': len(cs), 'top': sum((c.get('judge') or {}).get('bin') == 'top' for c in cs),
            'kept': sum(c['key'] in kept for c in cs), 'rendered': sum(c['key'] in rendered for c in cs),
            'judged': sum(bool(c.get('judge')) for c in cs), 'added': s.meta.get('added'),
            'poster': next((c['key'] for c in sorted(cs, key=lambda c: -((c.get('judge') or {}).get('stars') or 0))
                            if (c.get('judge') or {}).get('bin') == 'top'), cs[0]['key'] if cs else None),
        })
    all_tasks = tasks.list_tasks()
    count = {st: sum(t['state'] == st for t in all_tasks) for st in ('open', 'claimed', 'done', 'failed')}
    s = agents.settings()
    return {
        'streams': streams,
        'tasks': {**count, 'running': [{'id': t['id'], 'kind': t['kind'], 'agent': t.get('agent'),
                                         'since': t.get('claimed_at')} for t in all_tasks if t['state'] == 'claimed']},
        'agent': {'name': s['agent'], **s['agents'].get(s['agent'], {}), 'auto': s.get('auto', True),
                  'parallel': s['parallel']},
        'renders': {**renderer.state(), 'done': len(Renderer.renders())},
        'catalog': catalog.version,
        'activity': list(activity.lines)[-40:],
    }


@app.get('/api/overview')
def api_overview():
    return overview()


@app.get('/api/clips')
def api_clips():
    return {'version': catalog.version, 'clips': catalog.clips()}


@app.get('/api/clip/{sid}/{cid}')
def api_clip(sid: str, cid: str):
    from .judge import _sentences, clip_text
    stream, clip = catalog.find(f'{sid}/{cid}')
    full = {k: v for k, v in clip.items() if not k.startswith('_')}
    full['text'] = clip_text(_sentences(stream), clip) if stream.path('sentences.txt').exists() else ''
    full['stream'] = {'id': stream.id, 'title': stream.title, 'date': stream.date,
                      'duration': stream.meta.get('duration'), 'url': stream.meta.get('source', {}).get('url')}
    full['render'] = Renderer.renders().get(full['key'])
    return full


@app.get('/api/decisions')
def api_decisions():
    return decisions.load()


@app.post('/api/decide')
async def api_decide(request: Request):
    b = await body(request)
    key, d = b['key'], b.get('d')
    if d not in ('keep', 'maybe', 'cut', None):
        raise HTTPException(400, 'd must be keep, maybe, cut or null')
    catalog.find(key)
    before = decisions.decide(key, d, b.get('why'))
    if d == 'keep':
        renderer.enqueue(key)
    elif before and before['d'] == 'keep':
        renderer.forget(key)
    return {'ok': True, 'before': before}


@app.post('/api/reason')
async def api_reason(request: Request):
    b = await body(request)
    decisions.set_reason(b['key'], b.get('why'))
    return {'ok': True}


@app.post('/api/seen')
async def api_seen(request: Request):
    decisions.mark_seen((await body(request))['keys'])
    return {'ok': True}


@app.post('/api/post')
async def api_post(request: Request):
    b = await body(request)
    decisions.set_post(b['key'], b.get('text'))
    return {'ok': True}


@app.post('/api/merge')
async def api_merge(request: Request):
    from .merge import make_clip
    keys = (await body(request))['keys']
    sids = {k.split('/')[0] for k in keys}
    if len(sids) != 1:
        raise HTTPException(400, 'clips to combine must come from one stream')
    try:
        merged = make_clip(catalog.stream(sids.pop()), [k.split('/')[1] for k in keys])
    except ValueError as e:
        raise HTTPException(400, str(e))
    decisions.add_merge(keys)
    return {'ok': True, 'key': merged['key']}


@app.get('/api/renders')
def api_renders():
    return Renderer.renders()


@app.get('/api/tasks')
def api_tasks():
    return tasks.list_tasks()


@app.get('/api/health')
def api_health():
    from .doctor import checks
    return [{'status': {'ok': 'ok', '--': 'warn', 'NO': 'fail'}[s], 'text': t} for s, t in checks()]


@app.get('/api/settings')
def api_settings():
    return {**agents.settings(), 'available': agents.available()}


@app.post('/api/settings')
async def api_set_settings(request: Request):
    b = await body(request)
    s = agents.settings()
    for k in ('agent', 'parallel', 'auto'):
        if k in b:
            s[k] = b[k]
    for name, cfg in (b.get('agents') or {}).items():
        s['agents'].setdefault(name, {}).update({k: v for k, v in cfg.items() if k in ('model', 'effort', 'command')})
    agents.save_settings(s)
    pipeline_loop.poke()
    agent_loop.poke()
    return s


@app.post('/api/ingest')
async def api_ingest(request: Request):
    from .ingest import add
    b = await body(request)
    source = (b.get('url') or b.get('path') or '').strip().strip('"')
    if not source:
        raise HTTPException(400, 'give a url or a path')
    try:
        stream = await asyncio.to_thread(add, source)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))
    activity.say(f'Added {stream.title}')
    pipeline_loop.poke()
    return {'id': stream.id}


@app.put('/api/upload')
async def api_upload(request: Request, name: str):
    from .ingest import add
    safe = _safe(Path(name).name, 150)
    if not re.search(r'\.(mp4|mkv|mov|flv|ts|m4v|webm)$', safe, re.I):
        raise HTTPException(400, 'drop a video file (mp4, mkv, mov, flv, ts, m4v, webm)')
    incoming = lib.LIBRARY / 'incoming'
    incoming.mkdir(parents=True, exist_ok=True)
    part = incoming / (safe + '.part')
    with open(part, 'wb') as f:
        async for chunk in request.stream():
            await asyncio.to_thread(f.write, chunk)
    final = incoming / safe
    os.replace(part, final)
    stream = await asyncio.to_thread(add, final, None, None, 'move')
    activity.say(f'Added {stream.title}')
    pipeline_loop.poke()
    return {'id': stream.id}


@app.post('/api/stream/{sid}/retry')
async def api_retry(sid: str, request: Request):
    b = await body(request)
    stream = catalog.stream(sid)
    stage = b.get('stage') or next((n for n in lib.STAGES if stream.stage(n)['state'] == 'failed'), None)
    if stage:
        pipeline.reset(stream, stage)
        for t in tasks.list_tasks(kind=stage, stream=sid):
            if t['state'] == 'failed':
                tasks.reopen(t['id'])
    pipeline_loop.poke()
    return {'ok': True, 'stage': stage}


@app.post('/api/task/{tid}/retry')
def api_task_retry(tid: str):
    tasks.reopen(tid)
    agent_loop.poke()
    return {'ok': True}


@app.get('/api/edit/{sid}/{cid}')
def api_edit(sid: str, cid: str):
    from . import edit
    stream, clip = catalog.find(f'{sid}/{cid}')
    return edit.view(stream, clip)


@app.post('/api/edit/{sid}/{cid}')
async def api_edit_update(sid: str, cid: str, request: Request):
    from . import edit
    stream, clip = catalog.find(f'{sid}/{cid}')
    edl = edit.update(stream, clip, await body(request))
    if decisions.load()['decisions'].get(clip['key'], {}).get('d') == 'keep':
        renderer.enqueue(clip['key'], now=True)
    return edl


@app.post('/api/render/{sid}/{cid}')
def api_render(sid: str, cid: str):
    renderer.enqueue(f'{sid}/{cid}', now=True)
    return {'ok': True}


@app.get('/api/publish')
def api_publish():
    from . import publish
    return publish.state()


@app.post('/api/publish/{action}')
async def api_publish_action(action: str, request: Request):
    from . import publish
    b = await body(request)
    if action == 'approve':
        return publish.approve(b['key'], b.get('fields') or {})
    if action == 'metadata':
        from . import titles
        ids = titles.open_tasks_for(b.get('keys') or _kept_youtube())
        agent_loop.poke()
        return {'tasks': ids}
    if action == 'schedule':
        return publish.schedule(b['keys'], b['start'], b.get('per_day', 1), b.get('at_time', '17:00'), b.get('tz'))
    if action in ('signin', 'channel', 'sheet', 'sync'):
        return {'result': await asyncio.to_thread(getattr(publish, action))}
    if action == 'upload':
        if b.get('confirm') != 'upload':
            raise HTTPException(400, 'uploads need {"confirm": "upload"}')
        return {'result': await asyncio.to_thread(publish.upload, b['keys'], activity.say)}
    raise HTTPException(404, f'no publish action {action}')


def _kept_youtube():
    kept = [k for k, v in decisions.load()['decisions'].items() if v['d'] == 'keep']
    out = []
    for k in kept:
        try:
            _, clip = catalog.find(k)
        except HTTPException:
            continue
        if (clip.get('judge') or {}).get('side') != 'community':
            out.append(k)
    return out


@app.get('/api/events')
async def api_events(request: Request):
    """Server-sent events: the overview whenever it changes (checked every second)."""
    async def stream():
        last = None
        while not await request.is_disconnected():
            snap = json.dumps(await asyncio.to_thread(overview), ensure_ascii=False)
            if snap != last:
                last = snap
                yield f'data: {snap}\n\n'
            else:
                yield ': keep-alive\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.get('/api/wave/{sid}')
async def api_wave(sid: str, a: float | None = None, b: float | None = None, n: int = 600):
    from . import waves
    stream = catalog.stream(sid)
    if not stream.media or not stream.media.exists():
        raise HTTPException(404, 'this stream has no video yet')
    if a is None:
        return waves.overview(stream)
    return await asyncio.to_thread(waves.clip, stream, max(0.0, a), b if b is not None else a + 60, n)


@app.get('/media/{sid}')
def media(sid: str):
    stream = catalog.stream(sid)
    if not stream.media or not stream.media.exists():
        raise HTTPException(404, 'this stream has no video yet')
    return FileResponse(stream.media, media_type='video/mp4')


@app.get('/thumb/{sid}/{cid}')
def thumb(sid: str, cid: str):
    stream = catalog.stream(sid)
    path = stream.path('thumbs') / f'{cid}.jpg'
    if not path.exists():  # planning skipped it (e.g. the disk was busy): make it now
        from .plan import thumbnail
        _, clip = catalog.find(f'{sid}/{cid}')
        path.parent.mkdir(exist_ok=True)
        if not (stream.media and stream.media.exists() and thumbnail(stream.media, clip, path)):
            raise HTTPException(404)
    return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control': 'max-age=86400'})


@app.get('/out/{key:path}')
def rendered(key: str):
    entry = Renderer.renders().get(key)
    if not entry:
        raise HTTPException(404, 'not rendered yet')
    return FileResponse(lib.LIBRARY / entry['path'], media_type='video/mp4')


@app.post('/api/reveal')
async def reveal(request: Request):
    """Show a rendered clip in Explorer / Finder."""
    entry = Renderer.renders().get((await body(request))['key'])
    if not entry:
        raise HTTPException(404)
    path = lib.LIBRARY / entry['path']
    if os.name == 'nt':
        import subprocess
        subprocess.Popen(['explorer', '/select,', str(path)])
    else:
        import subprocess
        subprocess.Popen(['open', '-R', str(path)])
    return {'ok': True}


@app.get('/{path:path}')
def web(path: str):
    target = (WEB / path).resolve() if path else WEB / 'index.html'
    if not target.is_relative_to(WEB.resolve()) or not target.is_file():
        target = WEB / 'index.html'
    return FileResponse(target, headers={'Cache-Control': 'no-store'})  # small local files; always the current app


def _warm_up():
    """Import the heavy editing libraries now, so the first Keep doesn't wait on thousands of file reads."""
    try:
        from . import edit, render  # noqa: F401
        import transformers  # noqa: F401
        from transformers import Wav2Vec2ForCTC  # noqa: F401
    except Exception as e:
        activity.say(f'Editing libraries not available: {e}')


def serve(port=8765, open_browser=True):
    threading.Thread(target=_warm_up, daemon=True).start()
    for loop in (pipeline_loop, agent_loop, renderer):
        loop.start()
    kept = [k for k, v in decisions.load()['decisions'].items() if v['d'] == 'keep']
    done = Renderer.renders()
    for k in kept:
        if k not in done:
            renderer.enqueue(k)
    url = f'http://127.0.0.1:{port}/'
    print(f'Clip Scout is running at {url}  (Ctrl+C to stop)')
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')
