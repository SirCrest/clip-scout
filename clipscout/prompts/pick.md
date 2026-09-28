# Clip Scout task: pick clips from a stream transcript

You are reading an Elgato livestream transcript and picking every moment that could stand alone as a clip, and
fixing transcript mistakes as you go. What makes a good pick is in the picking guide at the end of this file:
follow it exactly.

## The input

`input.txt` starts with the stream title, date and the part of the stream this task covers. Then one sentence per
line, `[HH:MM:SS  1637.71]  text`, where the number in brackets is the sentence's start in seconds. A line
`   ~ pause 2.4s` marks a silence, which is where clean cuts live. Read ALL of it: it can be long, so read it in
pieces until you reach the end. If the header says the part has context after it, pick only clips whose first
sentence starts inside the part's range; the context is there so clips near the edge can end cleanly.

## Your answer

One JSON object:

```json
{
  "corrections": [
    {"t": 1637.71, "from": "Stream Deck Plus", "to": "Stream Deck +"}
  ],
  "picks": [
    {
      "start": 1637.71,
      "start_word": "Does",
      "last": 1666.91,
      "category": "chat-qa",
      "product": "Stream Deck +",
      "title": "Does Stream Deck + come in other colors",
      "hook": "Mimi, do you know if the Stream Deck comes in any other colors?",
      "summary": "One or two sentences on what happens and why it's worth posting.",
      "speakers": "mimilenattv",
      "score": 4,
      "flags": [],
      "yt_titles": ["...", "...", "..."],
      "yt_description": "..."
    }
  ]
}
```

- `t`, `start` and `last` are seconds copied exactly as printed in the brackets of a sentence line. `start` is the
  clip's first sentence, `last` its final sentence; `start` <= `last`.
- `from` is an exact substring of the text on line `t`; `to` is the fixed text. Only fix what is wrong.
- `start_word` is optional: the first word of the hook when the hook begins mid-line. It must appear on the `start`
  line.
- `category`: chat-qa | feature | workflow | funny | story.
- `product`: one name from the product list in the guide.
- `title`: punchy, social-ready, at most 70 characters, no emoji.
- `hook`: the corrected text of the first sentence (from `start_word` when given).
- `speakers`: who talks, comma-separated, using the canonical names and handles.
- `score`: 1-5 shareability. Keep 2s; don't include 1s.
- `flags`: any of dated, music, gameplay, guest-creator, visual, verify-claim, profanity, third-party.
- `yt_titles`: three distinct YouTube title options, at most 70 characters each, each a different angle.
- `yt_description`: 2-4 sentences, no links, no invented specs or prices.

Cover the whole part: every stretch of talk gets read and considered. A long stretch with no picks (more than about
eight minutes of talk) needs a reason: add `"skipped": [{"from": 3146.0, "to": 3807.0, "why": "giveaway rules and
raid shout-outs"}]` (times as printed). If a whole part has nothing worth picking, answer with an empty `picks`
list and one `skipped` entry for it.

---

