"""Work for an agent: any model CLI (Claude Code, Codex, Gemini CLI...) or a person can do a task.

A task is a folder library/tasks/<task id>/:
  task.json    {id, kind, stream, name, keys, state, created, claimed_at, attempts, errors, agent}
  TASK.md      self-contained instructions; paths in it are relative to the repo root
  input.txt    the material to work on
  output.json  written by whoever does the task

`submit` validates output.json against clipscout/prompts/<kind>.schema.json plus the kind's own checks, then
applies it. States: open -> claimed -> done, or back to open with `errors` listed when a submission fails.

Each kind lives in its own module, registered in KINDS as "module" with these functions:
  open_tasks(stream) -> [task id]          (stage kinds only: create the stream's tasks with create())
  check(task, output) -> [error str]        (optional: checks beyond the schema, e.g. one answer per clip)
  apply_task(task, output) -> None          (store the result where the pipeline expects it)
"""
import importlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import jsonschema

from . import library as lib

KINDS = {
    'pick': 'clipscout.pick',
    'judge': 'clipscout.judge',
    'edit': 'clipscout.edit',
    'titles': 'clipscout.titles',
}
PROMPTS = Path(__file__).resolve().parent / 'prompts'
CLAIM_TTL = timedelta(hours=2)


def _module(kind):
    return importlib.import_module(KINDS[kind])


def folder(tid):
    return lib.TASKS / tid


def load(tid):
    task = lib.read_json(folder(tid) / 'task.json')
    if task is None:
        raise KeyError(f'no task {tid!r}')
    return task


def _save(task):
    lib.write_json(folder(task['id']) / 'task.json', task)


def rel(path):
    """A path as the agent should see it: relative to the repo root when inside it."""
    path = Path(path).resolve()
    try:
        return path.relative_to(lib.ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def create(kind, stream_id, name, instructions, input_text, keys=None, meta=None):
    """Create (or keep) task '<kind>-<stream>-<name>'. Existing open/claimed/done tasks are left alone."""
    tid = f'{kind}-{stream_id}-{name}' if name else f'{kind}-{stream_id}'
    existing = lib.read_json(folder(tid) / 'task.json')
    if existing and existing['state'] != 'cancelled':
        return tid
    f = folder(tid)
    f.mkdir(parents=True, exist_ok=True)
    (f / 'input.txt').write_text(input_text, encoding='utf-8')
    footer = (
        f"\n\n---\nTask id: `{tid}`. Input: `{rel(f / 'input.txt')}`. Write your answer to `{rel(f / 'output.json')}` "
        f"(valid JSON, UTF-8, nothing else in the file). Its format is checked against "
        f"`{rel(PROMPTS / (kind + '.schema.json'))}`. If you can run commands, finish with "
        f"`uv run scout task submit {tid}` and fix anything it reports. Don't change any other file.\n")
    (f / 'TASK.md').write_text(instructions.rstrip() + footer, encoding='utf-8')
    (f / 'output.json').unlink(missing_ok=True)
    _save({'id': tid, 'kind': kind, 'stream': stream_id, 'name': name, 'keys': keys or [], 'state': 'open',
           'created': lib.now(), 'claimed_at': None, 'attempts': 0, 'errors': [], 'agent': None, **(meta or {})})
    return tid


def list_tasks(state=None, kind=None, stream=None):
    if not lib.TASKS.exists():
        return []
    out = []
    for p in sorted(lib.TASKS.iterdir()):
        task = lib.read_json(p / 'task.json')
        if not task:
            continue
        if state and task['state'] != state or kind and task['kind'] != kind or stream and task['stream'] != stream:
            continue
        out.append(task)
    return out


def _claimable(task):
    if task['state'] == 'open':
        return True
    if task['state'] == 'claimed' and task.get('claimed_at'):
        return datetime.now() - datetime.fromisoformat(task['claimed_at']) > CLAIM_TTL
    return False


def claim(tid, agent=None):
    with lib.locked(folder(tid) / 'task.json'):
        task = load(tid)
        if not _claimable(task):
            return None
        task.update(state='claimed', claimed_at=lib.now(), agent=agent or task.get('agent'))
        _save(task)
    return task


def claim_next(kind=None, agent=None):
    for task in list_tasks(kind=kind):
        if _claimable(task) and (claimed := claim(task['id'], agent)):
            return claimed
    return None


def read_output(tid):
    """Parse output.json, tolerating a Markdown code fence around the JSON."""
    path = folder(tid) / 'output.json'
    if not path.exists():
        return None, [f'{rel(path)} does not exist']
    text = path.read_text(encoding='utf-8-sig').strip()
    fence = re.match(r'^```(?:json)?\s*(.*?)\s*```$', text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text), []
    except json.JSONDecodeError as e:
        return None, [f'output.json is not valid JSON: {e}']


def validate(task, output):
    schema = json.loads((PROMPTS / f"{task['kind']}.schema.json").read_text(encoding='utf-8'))
    errors = []
    for e in sorted(jsonschema.Draft202012Validator(schema).iter_errors(output), key=lambda e: list(e.path)):
        where = '/'.join(str(p) for p in e.path) or '(top level)'
        errors.append(f'{where}: {e.message[:200]}')
        if len(errors) >= 25:
            errors.append('... more errors; fix these first')
            break
    if not errors and hasattr(mod := _module(task['kind']), 'check'):
        errors = mod.check(task, output)
    return errors


def submit(tid, agent_meta=None):
    """Validate and apply a task's output. Returns a list of errors (empty when accepted)."""
    task = load(tid)
    if task['state'] == 'done':  # the agent already submitted it itself; still record who did the work
        if agent_meta:
            task.setdefault('runs', []).append(agent_meta)
            _save(task)
        return []
    output, errors = read_output(tid)
    if not errors:
        errors = validate(task, output)
    task['attempts'] = task.get('attempts', 0) + 1
    if agent_meta:
        task.setdefault('runs', []).append(agent_meta)
    if errors:
        task.update(state='open', errors=errors, claimed_at=None)
        _save(task)
        return errors
    _module(task['kind']).apply_task(task, output)
    task.update(state='done', errors=[], finished=lib.now())
    _save(task)
    _finish_stage(task)
    return []


def _finish_stage(task):
    if task['kind'] not in lib.AGENT_STAGES:
        return
    stream = lib.get_stream(task['stream'])
    if stage_complete(stream, task['kind']):
        stream.set_stage(task['kind'], 'done')


def reopen(tid):
    task = load(tid)
    task.update(state='open', claimed_at=None, errors=[])
    _save(task)


def cancel(tid, reason):
    task = load(tid)
    task.update(state='cancelled', claimed_at=None, cancelled=lib.now(), reason=reason)
    _save(task)


def fail(tid, reason):
    task = load(tid)
    task.update(state='failed', claimed_at=None, failed=lib.now(), reason=reason)
    _save(task)


def open_stage_tasks(stream, stage):
    return _module(stage).open_tasks(stream)


def stage_complete(stream, stage):
    mine = list_tasks(kind=stage, stream=stream.id)
    return bool(mine) and all(t['state'] in ('done', 'cancelled') for t in mine)


def prompt(kind):
    return (PROMPTS / f'{kind}.md').read_text(encoding='utf-8')


def cli(args):
    if args.action == 'list':
        for t in list_tasks(state=args.state):
            err = f"  ({len(t['errors'])} errors)" if t.get('errors') else ''
            print(f"{t['state']:8} {t['id']}{err}")
    elif args.action == 'next':
        task = claim_next(kind=args.type, agent='manual')
        if not task:
            print('No open tasks.')
            return 0
        f = folder(task['id'])
        print(f"Task {task['id']}\nInstructions: {rel(f / 'TASK.md')}\nWrite: {rel(f / 'output.json')}\n"
              f"Then: uv run scout task submit {task['id']}")
    elif args.action == 'show':
        print((folder(args.id) / 'TASK.md').read_text(encoding='utf-8'))
    elif args.action == 'submit':
        errors = submit(args.id)
        if errors:
            print('Not accepted. Fix these in output.json and submit again:')
            print('\n'.join(f'- {e}' for e in errors))
            return 1
        print(f'Accepted: {args.id}')
    elif args.action == 'reopen':
        reopen(args.id)
    return 0
