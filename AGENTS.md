# Clip Scout: notes for AI agents

Clip Scout turns Elgato livestreams into ready-to-post clips. The app does the mechanical work (download,
transcribe, cut, render, upload). The judgement calls (fixing the transcript, picking moments, judging them, planning
edits, writing titles) are **tasks** that an agent like you does. Every task is self-contained.

## Doing tasks (the usual reason you're here)

Repeat until there's nothing left:

1. `uv run scout task next` claims a task and prints where its instructions are.
2. Read that `TASK.md` in full, and every input file it names in full (they can be long; read them in pieces).
3. Write your answer to the task's `output.json`, exactly in the format TASK.md gives.
4. `uv run scout task submit <task id>`. If it lists problems, fix `output.json` and submit again.

`uv run scout task list` shows every task and its state. Only ever write a task's `output.json`: don't edit anything
else under `library/`, and don't change the guides in `elgato/` unless the user asks.

Never upload, publish or post anything, and never delete media. Those need the user.

## Working on the code

- Python 3.12 via `uv` (`uv sync --all-extras`, `uv run scout ...`, `uv run pytest`); a plain `uv sync` removes
  the music and publish extras. Windows first; keep code Mac-ready.
- `clipscout/`: `library.py` (on-disk format, read it first), `pipeline.py` (stages), `tasks.py` + `agents.py`
  (agent tasks and the CLI runners), one module per stage or task kind, `server.py` + `web/` (the app).
- `clipscout/prompts/`: each task kind's instructions (`<kind>.md`) and answer format (`<kind>.schema.json`).
- `elgato/`: everything Elgato-specific: picking guide, channel guide, glossary, products, benchmark.
- `library/` (not in git): streams, tasks, decisions and rendered clips.
- Clips are cut points over the source stream, not files. A file is rendered only when a clip is kept.
