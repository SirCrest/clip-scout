"""Hands open tasks to the command-line agent the user already has, so a dropped stream becomes judged clips
without anyone driving a chat session.

Supported: Claude Code, Codex, Gemini CLI, opencode (which can run DeepSeek, GLM and others), or any command set in
settings.json as `custom`. The agent gets a one-line prompt pointing at the task's TASK.md and writes output.json;
we submit it, and when it's rejected, run the agent again with the errors in errors.txt (MAX_ATTEMPTS in total).
The prompt stays one plain line because npm-installed CLIs on Windows go through .cmd wrappers that mangle quotes
and newlines.
"""
import json
import shlex
import shutil
import subprocess
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from . import library as lib
from . import tasks

MAX_ATTEMPTS = 3
TIMEOUT_S = 60 * 60
DEFAULT_SETTINGS = {
    'agent': 'claude',
    'parallel': 2,
    'agents': {
        'claude': {'model': '', 'effort': ''},
        'codex': {'model': '', 'effort': ''},
        'gemini': {'model': ''},
        'opencode': {'model': ''},
        'custom': {'command': ''},
    },
}
AGENT_NAMES = tuple(DEFAULT_SETTINGS['agents'])


def settings():
    path = lib.LIBRARY / 'settings.json'
    saved = lib.read_json(path)
    if saved is None:
        lib.write_json(path, DEFAULT_SETTINGS)
        saved = {}
    merged = {**DEFAULT_SETTINGS, **saved}
    merged['agents'] = {k: {**DEFAULT_SETTINGS['agents'].get(k, {}), **saved.get('agents', {}).get(k, {})}
                        for k in {*DEFAULT_SETTINGS['agents'], *saved.get('agents', {})}}
    return merged


def save_settings(value):
    lib.write_json(lib.LIBRARY / 'settings.json', value)


def available():
    """Which agent CLIs are on PATH."""
    exe = {'claude': 'claude', 'codex': 'codex', 'gemini': 'gemini', 'opencode': 'opencode'}
    return {name: bool(shutil.which(cmd)) for name, cmd in exe.items()}


def prompt_for(tid, retry=False):
    base = tasks.rel(tasks.folder(tid))
    text = (f'Do Clip Scout task {tid}. Read {base}/TASK.md and follow it exactly, reading every input file it names '
            f'in full. Write your answer to {base}/output.json and change no other file.')
    if retry:
        text += (f' Your previous answer was rejected. The problems are listed in {base}/errors.txt. '
                 f'Fix {base}/output.json so none of them remain.')
    return text


def command(name, cfg, prompt):
    model, effort = cfg.get('model'), cfg.get('effort')
    outside = not lib.LIBRARY.resolve().is_relative_to(lib.ROOT)  # agents only see the repo unless told
    if name == 'claude':
        cmd = ['claude', '-p', prompt, '--output-format', 'json', '--permission-mode', 'acceptEdits',
               '--tools', 'Read,Write,Edit,Glob,Grep', '--no-session-persistence', '--strict-mcp-config']
        cmd += ['--model', model] if model else []
        cmd += ['--effort', effort] if effort else []
        cmd += ['--add-dir', str(lib.LIBRARY)] if outside else []
    elif name == 'codex':
        cmd = ['codex', 'exec', '--sandbox', 'workspace-write', '--skip-git-repo-check', '--ephemeral', '--json',
               '-C', str(lib.ROOT)]
        cmd += ['--add-dir', str(lib.LIBRARY)] if outside else []
        cmd += ['-m', model] if model else []
        cmd += ['-c', f'model_reasoning_effort={effort}'] if effort else []
        cmd += [prompt]
    elif name == 'gemini':  # geminicli.com/docs/cli/cli-reference: -p, -m, --approval-mode=yolo (replaces --yolo)
        cmd = ['gemini', '--approval-mode=yolo'] + (['-m', model] if model else [])
        cmd += ['--include-directories', str(lib.LIBRARY)] if outside else []
        cmd += ['-p', prompt]
    elif name == 'opencode':  # opencode.ai/docs/cli: `run [message]`, -m provider/model, --auto approves permissions
        cmd = ['opencode', 'run', '--auto'] + (['-m', model] if model else []) + [prompt]
    elif name == 'custom':
        template = cfg.get('command') or ''
        if '{prompt}' not in template:
            raise ValueError('settings.json agents.custom.command needs a {prompt} placeholder')
        cmd = [part.replace('{prompt}', prompt) for part in shlex.split(template, posix=False)]
    else:
        raise ValueError(f'unknown agent {name!r}; use one of {", ".join(AGENT_NAMES)}')
    exe = shutil.which(cmd[0])
    if not exe:
        raise FileNotFoundError(f'{cmd[0]} is not on PATH')
    return [exe] + cmd[1:]


def usage(name, stdout):
    """Model, cost and token counts from the agent's machine-readable output, when it gives them."""
    out = {}
    try:
        if name == 'claude':
            data = json.loads(stdout.strip())
            if isinstance(data, list):  # newer versions print every event; the result is the last one
                data = next(e for e in reversed(data) if isinstance(e, dict) and e.get('type') == 'result')
            out['cost_usd'] = data.get('total_cost_usd')
            out['turns'] = data.get('num_turns')
            out['models'] = list((data.get('modelUsage') or {}).keys())
            u = data.get('usage') or {}
            out['tokens_in'] = sum(u.get(k, 0) or 0 for k in ('input_tokens', 'cache_read_input_tokens',
                                                             'cache_creation_input_tokens'))
            out['tokens_out'] = u.get('output_tokens')
        elif name == 'codex':
            tin = tout = 0
            for line in stdout.splitlines():
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                u = ev.get('usage') or (ev.get('msg') or {}).get('usage') or {}
                tin += u.get('input_tokens', 0) or 0
                tout += u.get('output_tokens', 0) or 0
            out['tokens_in'], out['tokens_out'] = tin or None, tout or None
    except (ValueError, IndexError, AttributeError):
        pass
    return {k: v for k, v in out.items() if v not in (None, [], '')}


def run_task(task, name, cfg, log=print):
    """Run the agent on one claimed task until it's accepted or MAX_ATTEMPTS runs fail. Returns True if done."""
    tid = task['id']
    folder = tasks.folder(tid)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.monotonic()
        cmd = command(name, cfg, prompt_for(tid, retry=attempt > 1))
        try:
            proc = subprocess.run(cmd, cwd=lib.ROOT, capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as e:
            stdout, stderr, code = e.stdout or '', f'timed out after {TIMEOUT_S}s', -1
        with open(folder / 'agent.log', 'a', encoding='utf-8') as f:
            f.write(f'\n===== attempt {attempt} {lib.now()} {name} exit {code}\n{stderr[-4000:]}\n{stdout[-8000:]}\n')
        meta = {'agent': name, 'model': cfg.get('model') or 'default', 'effort': cfg.get('effort') or 'default',
                'attempt': attempt, 'seconds': round(time.monotonic() - started), 'exit': code,
                **usage(name, stdout or '')}
        errors = tasks.submit(tid, meta)
        if not errors:
            log(f'{tid}: done by {name} in {meta["seconds"]}s (attempt {attempt})')
            return True
        (folder / 'errors.txt').write_text('\n'.join(f'- {e}' for e in errors) + '\n', encoding='utf-8')
        log(f'{tid}: attempt {attempt} rejected ({len(errors)} problems)')
        if attempt < MAX_ATTEMPTS and not tasks.claim(tid, name):
            return False
    tasks.fail(tid, f'rejected {MAX_ATTEMPTS} times; see errors.txt and agent.log')
    return False


class Worker(threading.Thread):
    """Keeps up to `parallel` agent runs going. With stop_when_idle it returns once no task is left."""

    def __init__(self, agent=None, parallel=None, kind=None, limit=None, stop_when_idle=True, log=print):
        super().__init__(daemon=True)
        s = settings()
        self.name_ = agent or s['agent']
        self.cfg = s['agents'].get(self.name_, {})
        self.parallel = parallel or s['parallel']
        self.kind, self.limit, self.stop_when_idle, self.log = kind, limit, stop_when_idle, log
        self.stop = threading.Event()
        self.started_count = 0

    def run(self):
        with ThreadPoolExecutor(self.parallel) as pool:
            running = set()
            while not self.stop.is_set():
                while len(running) < self.parallel and (self.limit is None or self.started_count < self.limit):
                    task = tasks.claim_next(kind=self.kind, agent=self.name_)
                    if not task:
                        break
                    self.started_count += 1
                    self.log(f"{task['id']}: {self.name_} started")
                    running.add(pool.submit(run_task, task, self.name_, self.cfg, self.log))
                if not running:
                    if self.stop_when_idle:
                        return
                    self.stop.wait(5)
                    continue
                done, running = wait(running, timeout=5, return_when=FIRST_COMPLETED)
                for f in done:
                    if f.exception():
                        self.log(f'agent run crashed: {f.exception()}')


def work(agent=None, parallel=None, kind=None, limit=None, log=print):
    Worker(agent, parallel, kind, limit, stop_when_idle=True, log=log).run()


def run_all(agent=None, parallel=None, log=print):
    """Process every stream while an agent worker does the tasks they open, until nothing can move."""
    from . import pipeline
    worker = Worker(agent, parallel, stop_when_idle=False, log=log)
    worker.start()
    try:
        while True:
            try:
                pipeline.process(log=log)
            except Exception as e:  # one bad stream or a file hiccup must not stop the whole run
                log(f'pipeline error: {type(e).__name__}: {e}')
            # A stream still 'waiting' after a pass has open tasks, or tasks that failed; once none are open or
            # claimed, nothing further can happen without a person.
            if not tasks.list_tasks(state='open') and not tasks.list_tasks(state='claimed'):
                break
            time.sleep(5)
    finally:
        worker.stop.set()
        worker.join()
    log(pipeline.status())
