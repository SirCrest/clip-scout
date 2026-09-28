# Clip Scout task: judge a stream's clips for Elgato's channels

You are judging the clips found in one Elgato livestream against Elgato's channel guide, which is at the end of this
file. The guide is the standard: read it in full first and follow it exactly.

## The input

`input.txt` lists every clip of the stream in time order. Each `## <id>` block is one clip: its time range in the
stream, its length, the picker's guesses (category, product, stars, speakers, flags), title, summary, and the words
spoken in the clip. Neighbouring clips can overlap. Clips marked `[APPROVED EXAMPLE]` were really posted by Elgato
staff: they are your reference for what `top` looks like. The file can be long; read it in pieces to the end.

## How to judge

1. First decide for the stream as a whole: staff-hosted, a takeover/community stream, or mixed. Then judge each
   clip, deciding `side` from who actually leads that clip.
2. Compare the clips with each other to spot dupes and set stars. There is no quota: every complete, worthwhile
   Elgato talking point is `top`. Never move a good clip down to keep a count small.

## Your answer

A JSON array with exactly one object per clip in the input, in the same order:

```json
[
  {"id": "t016377", "side": "staff", "bin": "top", "stars": 5,
   "reason": "Answers a real buyer question (MK.1 faceplates on MK.2) in a minute; nothing dated.",
   "dupe_of": null, "merge": null, "post": null}
]
```

- `side`: "staff" or "community". `bin`: "top", "effort", "off" or "dupe". `stars`: 1-5.
- `reason`: one line under 120 characters, plain words, specific to this clip.
- `dupe_of`: the id of the better clip when `bin` is "dupe", otherwise null.
- `merge`: for one continuous discussion spread over consecutive clips, their ids in order (e.g.
  ["t016377", "t016912", "t017450"]), on the FIRST clip of the run only; otherwise null. Still bin each clip on
  its own.
- `post`: community `top` clips only, a draft X post under 240 characters crediting the creator's @handle if known;
  otherwise null.

---

