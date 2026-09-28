"""Moves each stream through its stages in order.

Mechanical stages are functions `run(stream, progress)` that raise on failure; `progress(fraction, note)` reports
how far along they are. Agent stages (pick, judge) open tasks for an agent (tasks.py) and wait; submitting the
last task of a stage marks it done, and the next `advance` carries on from there.
"""
import importlib
import time

from . import library as lib

RUNNERS = {
    'fetch': 'clipscout.ingest:fetch',
    'transcribe': 'clipscout.transcribe:run',
    'plan': 'clipscout.plan:run',
    'music': 'clipscout.music:run',
}


def _runner(name):
    module, fn = RUNNERS[name].split(':')
    return getattr(importlib.import_module(module), fn)


def _progress(stream, name):
    last = [0.0]

    def report(fraction, note=''):
        if time.monotonic() - last[0] < 2 and fraction < 1:
            return
        last[0] = time.monotonic()
        stream.set_stage(name, 'running', progress=round(fraction, 3), note=note)
    return report


def advance(stream, until=None, log=print):
    """Run the stream's pending stages in order. Returns 'done', 'waiting' (on an agent) or 'failed'."""
    from . import tasks
    for name in lib.STAGES:
        state = stream.stage(name)['state']
        if state in ('done', 'skipped'):
            if name == until:
                return 'done'
            continue
        if name in lib.AGENT_STAGES:
            if tasks.stage_complete(stream, name):
                stream.set_stage(name, 'done')
                continue
            opened = tasks.open_stage_tasks(stream, name)
            stream.set_stage(name, 'waiting', tasks=opened)
            log(f'{stream.id}: {name} waiting on {len(opened)} agent task(s)')
            return 'waiting'
        stream.set_stage(name, 'running', progress=0)
        log(f'{stream.id}: {name}')
        try:
            result = _runner(name)(stream, _progress(stream, name))
        except Exception as e:
            stream.set_stage(name, 'failed', error=f'{type(e).__name__}: {e}')
            log(f'{stream.id}: {name} failed: {e}')
            return 'failed'
        if isinstance(result, tuple) and result[0] == 'skipped':  # e.g. optional dependency missing
            stream.set_stage(name, 'skipped', note=result[1])
        else:
            stream.set_stage(name, 'done')
        if name == until:
            return 'done'
    return 'done'


def process(ids=None, until=None, log=print):
    streams = [lib.get_stream(i) for i in ids] if ids else lib.all_streams()
    return {s.id: advance(s, until, log) for s in streams}


def reset(stream, name):
    """Mark a stage and every later stage pending so they run again."""
    later = lib.STAGES[lib.STAGES.index(name):]
    stream.update(lambda meta: [meta.setdefault('stages', {}).pop(n, None) for n in later])


def status(ids=None):
    streams = [lib.get_stream(i) for i in ids] if ids else lib.all_streams()
    marks = {'done': '#', 'skipped': '-', 'running': '>', 'waiting': '?', 'failed': '!', 'pending': '.'}
    rows = [f"{'stream':16} {' '.join(n[:5].ljust(5) for n in lib.STAGES)}  title"]
    for s in streams:
        cells = []
        for n in lib.STAGES:
            st = s.stage(n)
            cell = marks.get(st['state'], '?')
            if st['state'] == 'running' and 'progress' in st:
                cell = f"{int(st['progress'] * 100)}%"
            cells.append(cell.ljust(5))
        rows.append(f"{s.id:16} {' '.join(cells)}  {s.date} {s.title[:60]}")
    return '\n'.join(rows)
