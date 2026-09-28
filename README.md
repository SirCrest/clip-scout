# Clip Scout

Drop in an Elgato stream (a video file or a Twitch/YouTube link) and Clip Scout finds the moments worth posting,
judges them against Elgato's channel guide, edits them so they keep moving, and gets them onto the Elgato Clips
YouTube channel.

It runs on your machine. The thinking (fixing the transcript, picking moments, judging, planning edits, writing
titles) is done by the AI agent you already use: Claude Code, Codex, Gemini CLI, or opencode (which covers
DeepSeek, GLM and others). No API keys go into Clip Scout itself.

## Start

1. Install [uv](https://docs.astral.sh/uv/) and ffmpeg (`winget install Gyan.FFmpeg`). An NVIDIA GPU makes
   transcription and rendering fast; without one it still works, slowly.
2. Install at least one agent CLI and sign in to it once (e.g. `claude`, `codex`).
3. Double-click **Clip Scout.bat**. The first run installs everything (a few minutes), then the app opens in your
   browser.

`uv run scout doctor` checks the machine and says how to fix anything missing.

## How it works

```
file or link ─► fetch ─► transcribe ─► pick* ─► plan ─► music ─► judge* ─► review ─► edit* ─► render ─► publish
                                  (* = done by your agent as tasks)
```

- **Transcribe**: Whisper large-v3-turbo on the GPU with an Elgato glossary (about 80x realtime on an RTX 4090).
- **Pick**: the agent reads the transcript, fixes misheard names, and picks every self-contained talking point
  (`elgato/picking-guide.md`).
- **Plan**: picks become cut points over the source, with thumbnails. Clips are never pre-cut into files.
- **Music**: an audio classifier flags copyrighted-music risk.
- **Judge**: the agent bins each clip (top, effort, off, dupe) with stars and a reason, following
  `elgato/channel-guide.md`. Off and dupe clips stay out of review except for spot checks.
- **Review**: people Keep, Maybe or Cut in the app.
- **Edit**: kept clips get dead air, fillers, false starts and detours removed. The cut style is chosen per cut:
  a hard cut where the shot changes anyway, a subtle punch-in on a single talking head. You can adjust every cut.
- **Render**: near-lossless NVENC encode at -14 LUFS, with captions, into `library/approved/<YouTube|X>/<Topic>/`.
- **Publish**: the agent writes three titles (A/B/C) and a description; you approve; Clip Scout uploads to the
  Elgato Clips channel (private until you schedule it), or gives you a sheet to copy from.

## Agents

Settings in the app (or `library/settings.json`) choose the agent, its model and reasoning effort, and how many
tasks run at once. Each task is a folder under `library/tasks/` with a self-contained `TASK.md`, so you can also do
them from any agent session: open the agent in this folder and ask it to "do the Clip Scout tasks" (it reads
`AGENTS.md`), or in Claude Code run `/clip-scout`. Answers are checked against a strict format; rejected answers
go back to the agent with the problems listed.

## Command line

| Command | What it does |
|---|---|
| `scout serve` | the app (what Clip Scout.bat runs) |
| `scout add <file or url>` | add a stream |
| `scout run [--agent codex]` | process every stream and work its tasks until nothing is left |
| `scout status` | stage progress per stream |
| `scout task list / next / submit <id>` | the task queue |
| `scout work --agent <name>` | run an agent on open tasks |
| `scout edit <key>` / `scout render <key>` | plan edits / render a clip (`<stream id>/<clip id>`) |
| `scout bench` | score the judge against clips staff approved |
| `scout publish metadata / signin / channel / upload / sheet` | YouTube |
| `scout doctor` | check the machine |

## Layout

| Path | What's there |
|---|---|
| `clipscout/` | the engine; `library.py` documents the on-disk format |
| `clipscout/prompts/` | each task's instructions and answer format |
| `elgato/` | everything Elgato-specific: guides, glossary, products, YouTube house style, benchmark |
| `web/` | the app (no build step) |
| `library/` | streams, tasks, decisions, rendered clips (not in git) |
