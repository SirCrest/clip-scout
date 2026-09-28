# Clip Scout

Drop in an Elgato stream (a video file or a Twitch/YouTube link) and Clip Scout finds the moments worth posting,
judges them against Elgato's channel guide, edits them so they keep moving, and gets them onto the Elgato Clips
YouTube channel (staff clips) or ready for X (community clips).

It runs on your machine. The thinking (fixing the transcript, picking moments, judging, planning edits, writing
titles) is done by the AI agent you already use: Claude Code, Codex, Gemini CLI, or opencode (which covers
DeepSeek, GLM and others). No API keys go into Clip Scout itself.

## Start

1. Install [uv](https://docs.astral.sh/uv/) and ffmpeg (`winget install Gyan.FFmpeg`). An NVIDIA GPU makes
   transcription and rendering fast; without one it still works, slowly.
2. Install at least one agent CLI and sign in to it once (for example `claude` or `codex`).
3. Double-click **Clip Scout.bat**. The first run installs everything (a few minutes), then the app opens at
   http://127.0.0.1:8765.

`uv run scout doctor` checks the machine and says how to fix anything missing.

## The app

| Space | What you do there |
|---|---|
| **Streams** | Drop a video anywhere on the window, or paste a link or a file path. Watch it download, transcribe, get picked and judged, with clips appearing as they're found. |
| **Review** | Sort the judge's picks, best first: **K** keep, **M** maybe, **X** cut, arrows to move, **Space** to play, **U** to undo. After a cut or maybe, a number key (1-5) says why. YouTube (staff) and X (community) are separate lanes; the strip at the bottom shows where every clip sits in its stream. |
| **Edit** | Every kept clip, already tightened. The transcript shows removed words struck through: click one to put it back, shift-click to remove a stretch, or drag across the waveform. Choose a hard cut or a punch-in at each join. |
| **Publish** | Your agent writes three titles (A/B/C) and a description per clip in the channel's house style; you edit and approve; Clip Scout uploads to Elgato Clips as private videos on the schedule you set, or exports a sheet to copy from. |
| **Settings** | Which agent, its model and effort, how many tasks run at once, autopilot on or off, the machine check, and every agent task with who did it, how long it took and what it cost. |

## How it works

```
file or link ─► fetch ─► transcribe ─► pick* ─► plan ─► music ─► judge* ─► review ─► edit* ─► render ─► publish*
                                                   (* = done by your agent as tasks)
```

- **Transcribe**: Whisper large-v3-turbo on the GPU with an Elgato glossary (about 80x realtime on an RTX 4090).
- **Pick**: the agent reads the transcript in ~40-minute parts, fixes misheard names, and picks every
  self-contained talking point (`elgato/picking-guide.md`). A long stretch of talk with no picks is sent back to
  the agent unless it says why nothing there fits.
- **Plan**: picks become cut points over the source, with thumbnails. Clips are never pre-cut into files.
- **Music**: an audio classifier flags copyright-music risk.
- **Judge**: the agent bins each clip (top, effort, off, dupe) with stars and a reason (`elgato/channel-guide.md`).
  Off and dupe clips stay out of review except for spot checks.
- **Edit**: when you keep a clip, pauses over 0.45 s are closed, clean fillers ("um", "uh") are cut, and the agent
  removes false starts, repeats and detours. Most cuts are hard cuts, like Elgato staff's own edits; a subtle
  punch-in is used only where the layout allows it. Cuts where words run together are flagged for a listen.
- **Render**: frame-exact, NVENC, source resolution, -14 LUFS, 2-5x realtime, with captions, into
  `library/approved/<YouTube|X>/<Topic>/`. It re-renders by itself when the agent's or your edits change.
- **Publish**: see "YouTube" below.

A two-hour stream took about 40 minutes from drop to judged clips in testing (most of it the agent reading), and
about $3-4 of agent usage on Claude Sonnet.

## Agents

Settings choose the agent. Tested end to end: **Claude Code** and **Codex**. Built from their docs, not yet run
here: **Gemini CLI** (`gemini --approval-mode=yolo -p`) and **opencode** (`opencode run --auto`, which is how
to use DeepSeek or GLM). **Other** runs any command with a `{prompt}` placeholder.

Each task is a folder under `library/tasks/` with a self-contained `TASK.md`, so you can also do them from any
agent session: open the agent in this folder and ask it to "do the Clip Scout tasks" (it reads `AGENTS.md`), or
in Claude Code run `/clip-scout`. Answers are checked against a strict format; rejected answers go back to the
agent with the problems listed (three tries).

`uv run scout bench` scores the judge against the 97 clips Elgato staff approved, so models can be compared.

## YouTube

Until Elgato Clips is connected, approve copy in Publish and use **Sheet** (`library/publish-sheet.csv`).
To connect:

1. In Google Cloud, enable the YouTube Data API v3 and create an OAuth client of type **Desktop app**. An
   **Internal** consent screen (Elgato's Workspace) avoids having to sign in again every 7 days.
2. Save the client file as `secrets/google-client.json` (git ignores `secrets/`).
3. In Publish, **Sign in** with the account that manages Elgato Clips. Clip Scout refuses to write to any other
   channel.
4. Uploads from an unaudited Google Cloud project stay private. Test one video before relying on scheduling, and
   apply for Google's audit if needed. Details: `clipscout/publish.py` (header) and `elgato/youtube.md`.

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
| `scout publish metadata / signin / channel / upload / sync / sheet` | YouTube |
| `scout doctor` | check the machine |

## Layout

| Path | What's there |
|---|---|
| `clipscout/` | the engine; `library.py` documents the on-disk format |
| `clipscout/prompts/` | each task's instructions and answer format |
| `elgato/` | everything Elgato-specific: guides, glossary, products, YouTube house style, benchmark |
| `web/` | the app (no build step) |
| `library/` | streams, tasks, decisions, rendered clips (not in git); `library/samples/editing/` has example edits |
| `tools/migrate_year.py` | the one-time move of the 2025-26 year set into the library (`--undo` reverses it) |
