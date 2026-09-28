# Edit task: tighten clips so the talk keeps moving

You're editing clips cut from Elgato's livestreams for Elgato's YouTube channel. Rules have already cut the dead
air (pauses) and the "um"s and "uh"s. Your job is what rules can't see: the words that slow a clip down or make no
sense outside the live stream. The goal is a clip where every sentence moves the explanation, the demo or the joke
forward, and nothing a viewer needs is lost.

## Input

`input.txt` has one block per clip: title, summary, length, frame images, shot changes, and every word numbered,
one sentence per line with its time in stream seconds:

    [1650.2] 41:Did 42:you 43:know 44:that ...

- `*f3` after a word: a filler the rules already cut (id f3).
- `~0.9s:p2` after a word: a pause the rules already cut after it (id p2).
- Lines marked `(context)` are just before or after the clip. They're there so you understand it; don't cut them.

## What to remove (by word numbers)

Staff edits of clips they approved removed exactly these kinds of things:

- **Live-stream logistics and technical trouble:** "I think we're having network issues", "can you hear me?",
  "chat, let me know", "hold on, let me pull that up", reading out usernames, giveaway/raid/sub alerts.
- **References to the stream itself:** "like I said yesterday", "later today we'll show you", "we'll get to that in
  a bit": anything that only makes sense live.
- **Tangents** that leave the clip's topic and come back (a side story, a joke about something else), even long ones.
- **False starts and restarts:** "So the, the way it... so what it does is" keeps only the clean restart.
- **Repeats:** the same point said twice in a row; keep the better one.
- **Waiting:** narrating a loading bar, or filling time while something happens on screen.
- **Crosstalk** and off-mic chatter that goes nowhere.

Keep:

- everything the explanation needs, including brief setup and the payoff;
- the joke, the reaction and the laugh when they are the point of the clip;
- the host's natural voice: don't strip every "so" or "you know", only the ones that stall a sentence;
- the first sentence (the hook). You may start later only to drop a lead-in like "So yeah, anyway," (use `start`).

When unsure, keep it. Cut whole phrases or sentences so what's left is still grammatical; never leave half a
sentence dangling.

## Layout and punch-ins (look at the frame images if you can view images)

At each cut the picture jumps. On a clean shot from one camera a slight zoom (a punch-in) hides the jump. When
there are graphics near the edges, a screen share, several cameras in a grid, or a product close-up, zooming would
crop something that matters, so those clips get plain cuts.

- `layout`: `camera` (people on one camera, nothing important near the edges), `camera_graphics` (a camera shot
  with name tags, logos or headers near the edges), `multi_cam`, `screen`, `product` or `mixed`.
- `punch_in_ok`: true only when zooming about 8% into the centre crops nothing that matters (logos, name tags,
  on-screen text, app UI). If you can't view the frames, answer false.
- `styles` (optional): override the style of one cut, e.g. `{"after_word": 57, "style": "hard"}` or `"punch"`.

## Answer: output.json

```json
{"clips": [
  {"clip": "t016377", "layout": "camera_graphics", "punch_in_ok": false, "start": null, "end": null,
   "remove": [{"from": 120, "to": 158, "reason": "tangent about the weather"}],
   "keep": [], "note": "Cut an aside about the weather (18 s)."}
]}
```

- One entry for every clip in `input.txt`, with its clip id.
- `remove`: inclusive ranges of word numbers inside the clip, each with a reason of a few words. An empty list is a
  fine answer when the clip already flows.
- `start` / `end`: the numbers of the first / last word to keep, or null to leave them as they are.
- `keep`: ids of rule cuts that should stay after all (a `p…` pause kept for comic timing, an `f…` filler that
  was really a word).
- `note`: one line on what you changed, for the person reviewing the edit.
