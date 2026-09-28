---
name: clip-scout
description: Work Clip Scout's task queue (pick clips from stream transcripts, judge clips, plan edits, write YouTube titles), add a stream by file or URL, or check pipeline status. Use when the user asks to process a stream, find clips, "do the Clip Scout tasks", or run the queue.
---

# Clip Scout

Run everything from the repo root with `uv run scout ...`.

## Add and process a stream
1. `uv run scout add "<file path or Twitch/YouTube URL>"` prints the stream id.
2. `uv run scout process <id>` runs the mechanical stages (download, transcribe, plan, music check). It stops at a
   stage that needs judgement and opens tasks for it.
3. Do the tasks (below), then `uv run scout process <id>` again. Repeat until `uv run scout status <id>` shows every
   stage done.

## Do the open tasks yourself
Loop until `uv run scout task next` says there are none:
1. `uv run scout task next` claims one and prints its TASK.md path.
2. Read TASK.md in full, then the input file it names, all of it, in pieces if long.
3. Write the answer to that task's `output.json`.
4. `uv run scout task submit <task id>`. If it lists problems, fix output.json and submit again.

When several tasks are open, and subagents are available, give each subagent one task with the same four steps.

## Or let a CLI agent do them in the background
`uv run scout work --agent claude` (or codex, gemini, opencode, custom) runs the agent headlessly on every open task,
retrying rejected answers. `uv run scout run` processes all streams and works their tasks until nothing is left.

## Rules
- Only write task `output.json` files; don't edit other library files or the guides in `elgato/`.
- Never upload, publish, post or delete media without the user saying so.
