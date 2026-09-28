# Clip Scout task: write YouTube titles and descriptions for kept clips

These clips were kept by Elgato staff for the **Elgato Clips** YouTube channel. For each one, write the copy it
will be published with: three title options for YouTube's A/B/C title test, a description, tags and a playlist.
The channel's house style is at the end of this file: follow it closely, it was learned from the channel itself.

## The input

`input.txt` has one `## <clip id>` block per clip: the product and topic, the stream it came from, the judge's
verdict, flags, the links you may use, the picker's draft titles and description (a starting point, not the final
copy), and the words spoken in the clip. Base every claim on those words. Never invent specs, prices, dates or
features the clip doesn't state.

## Your answer

A JSON array with exactly one object per clip, in the same order as the input:

```json
[
  {
    "id": "t016377",
    "titles": [
      "Elgato Stream Deck +: Control Every App with Dial Stacks",
      "One Dial, Five Jobs? How Stream Deck + Dial Stacks Work",
      "How to Stack Multiple Actions on One Stream Deck + Dial"
    ],
    "description": "Paragraph 1 ...\n\nParagraph 2 ...\n\nExplore Stream Deck: https://www.elgato.com/us/en/s/stream-deck",
    "hashtags": ["#StreamDeck", "#Elgato"],
    "tags": ["Stream Deck +", "dial stack", "Elgato"],
    "playlist": "Stream Deck",
    "hold": [],
    "note": null
  }
]
```

- `titles`: three genuinely different angles, not rewordings of one idea. Title A (the first) is the one uploaded,
  so make it the strongest and most searchable; B and C are tested against it later in YouTube Studio. Each is at
  most 100 characters (aim for 55-75, key words first), with no `<` or `>`, and pays off in the clip itself.
- `description`: the two short paragraphs and the link lines from the house style, using **only** the links listed
  for that clip. Don't add the "full stream" line, the "Connect with Elgato" block or hashtags to the text:
  Clip Scout adds those. No `<` or `>`.
- `hashtags`: optional, 0-6, like `#StreamDeck`. They go on the last line.
- `tags`: up to 8 short search tags (product names, the feature). Plain words, no commas inside a tag.
- `playlist`: the suggested playlist given for the clip (the topic name), unless it's clearly the wrong topic; then
  another topic name from the house style's list.
- `hold`: reasons this clip shouldn't go out as-is, from: "dated" (a price, deal, launch date or "today only" that
  has passed or will), "music" (copyrighted music audible), "verify-claim" (a spec, compatibility or roadmap claim
  someone should check), "profanity", "rights" (a guest creator or third-party content needing approval), "other".
  Leave it empty when the clip is fine. Still write full copy for held clips.
- `note`: when `hold` isn't empty, one sentence saying what to check or fix; otherwise null.

---

