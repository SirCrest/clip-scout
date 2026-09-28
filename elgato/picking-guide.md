# Picking guide: finding clip-worthy moments in Elgato streams

The picker reads a whole stream and finds every moment that might be worth posting. It errs on the side of too
many: the judge (elgato/channel-guide.md) and people cut down later. The transcript has no speaker labels, so infer
speakers from context; hosts and creators are usually named in the talk and the stream title.

## What to pick
- **chat-qa**: a question from chat (usually read aloud) and the direct answer. Start ON the question.
- **feature**: the host showing off or explaining a product feature, spec, or capability.
- **workflow**: someone walking through how they actually use the gear: a Stream Deck profile, an editing setup,
  audio routing, a multi-action, a lighting setup, a creator's clever trick.
- **funny**: genuine laughs, bits, chaos, banter, fails, reactions that stand alone without context.
- **story**: heartfelt or personal moments that stand alone: a creator's journey, accessibility testimonials,
  heritage/pride/community talk, how someone got into streaming. Use this instead of forcing them into the others.

## Start strong: the most important rule
- The first sentence must be the hook: the question, the claim, the "here's how I…", or the setup of the joke.
- Never open on filler or a back-reference ("So yeah, anyway…", "And that's why…", "It also…" where *it* is
  undefined). Skip the lead-in and start where the thought becomes self-contained.
- If the strong part begins mid-line (e.g. `Anyways, though, I set up hotkeys…`), keep `start` as that line's
  timestamp and add `"start_word": "I"`: the first word of the hook, which must appear in that line. Use this
  whenever a line opens with So / But / And / Anyways / Okay / Um / Yeah before the real hook.
- Where two openings are equally strong, prefer the one right after a `~ pause` line.
- There is no minimum or maximum number of clips per stream. Capture every moment that might be good.
- For calibration: on a staff demo or Q&A stream, a good pass finds roughly one moment every one to three
  minutes of talk (a two-hour stream usually gives 40 to 90 picks, many of them 30 s to 3 min). Takeover and
  gameplay streams give fewer. If you have far fewer, you are judging too early: pick, and let the judge cut.

## End clean
- End after the thought fully lands: the answer is complete, the demo pays off, the laugh happens. Don't trail into
  the next topic, a giveaway reminder, or "anyway, moving on".
- No length limit. A 10 s joke and a 4 min workflow walkthrough are both fine. One idea per clip. Split a long
  segment into several clips when it covers separate ideas; overlaps are OK when both versions stand alone.

## Titles and descriptions
YouTube is the destination for staff clips. Titles should make someone click: a question, a bold claim, or a
curiosity gap. Don't repeat the same pattern three times, and don't use clickbait the clip doesn't deliver. The
description is 2-4 sentences: what the viewer learns or sees, the product named, natural keywords, no hashtag spam,
no invented specs or prices, no links.

## Flags
- `dated`: sale prices, % off, "today only", deal events, giveaways, "launching tomorrow", anything that expires.
  DO pick punchy deal/price moments; just flag them.
- `music`: copyrighted music is likely audible (music streams, background tracks, singing along).
- `gameplay`: third-party game footage/audio is prominent.
- `guest-creator`: a non-staff creator is the main speaker (takeovers). Rights check needed before posting.
- `visual`: the value depends on seeing the screen/product.
- `verify-claim`: a spec/compatibility/roadmap claim that could be wrong, unreleased, or a joke (e.g. April 1).
- `profanity`: swearing or content that may need a bleep.
- `third-party`: mostly about a non-Elgato product or game (still pick it if it's funny or useful).

## Skip
BRB/starting-soon screens, giveaway mechanics, raids and shout-out lists, dead air, long silent gameplay, reading out
sub/follow alerts (unless the reaction is funny), and non-English segments.

## Transcript corrections
Fix misrecognitions using Elgato / streaming / content-creation context: product names (`Stream Deck Plus` →
`Stream Deck +`, `Elgado` → `Elgato`, `wave link` → `Wave Link`, `Gobi` → `Govee`, `Face cam` → `Facecam`,
`camera hub` → `Camera Hub`), software and jargon (OBS, Streamlabs, multi-action, VST, plugin, Premiere Pro,
DaVinci Resolve, bitrate, HDR, passthrough), creator handles, and words that are clearly misheard given the context.
Do not rewrite style, grammar or filler. Only fix what is wrong. Corrected text feeds titles and captions, so it
matters most inside picked clips.

## Canonical names (Elgato staff who host streams)
Use these spellings in corrections, `speakers`, titles and descriptions. Whisper often mishears them.
Phil (Technical Marketing Manager), **Brito** (Angelica Brito, Community Marketing Manager; NOT "Burrito"/"Bruno"/
"Frito"), Julian Fest (SVP & GM), Stephan (Principal Product Architect), Dominik (Product Manager), Yannick (Software
Manager), Chris (Senior Tech Marketing Specialist), Jared (Senior Manager, Digital Product Innovation), Mark
(FiniteSingularity, OBS Plugin Developer, contractor; counts as staff), Jasmine (Senior Community Specialist), James
(Tech Marketing Specialist), Steggy (Product Manager), Stephanie (Maker Relations Specialist), Brett (SirCrest,
technical video producer; appears on audio streams).
Recurring creators (use these handles): copacaxi (heard "Coppa"/"Kopa Kaxi"), rouxal, mimilenattv (Mimi/Mimilena),
mellonzlord, lexilemonhead, bigcheese, deafgamerstv, mcd00dle, theking, hyjules, zunebula.
Guest creators: use their Twitch handle from the stream title where possible. Don't invent a name you can't confirm;
write "host" or "guest" instead. Never assume a Twitch handle belongs to a staff member unless the stream says so.
Generation suffixes are written "MK.2" (Wave:3 MK.2, Wave XLR MK.2, XLR Dock MK.2, Key Light Air MK.2, Facecam
MK.2), never "Mark II"/"Mk2". Stream Deck with dials is "Stream Deck +", the big one "Stream Deck + XL".

## Product list
Stream Deck, Stream Deck +, Stream Deck + XL, Stream Deck XL, Stream Deck Neo, Stream Deck Mini, Stream Deck Pedal,
Stream Deck Mobile, Stream Deck Studio, Stream Deck Software, Marketplace, Marketplace Connect, Wave Link, Wave Next,
Wave:3, Wave DX, Wave XLR, Wave XLR Pro, XLR Dock, Wave Neo, Wave Mic Arm, Wave Mic Arm LP, Wave Mic Arm Pro, Wave FX,
Voice Focus, Wave Cast, Facecam, Facecam 4K, Facecam MK.2, Facecam Pro, Prompter, Prompter XL, Key Light, Key Light
Air, Key Light Mini, Light Strip, Ring Light, Game Capture, 4K X, 4K S, 4K Pro, HD60 X, Neo, Cam Link, Chat Link Pro,
Camera Hub, Elgato Studio, Embrace, Galleon 100 SD, Green Screen, Multi Mount, Lighting, Setup, Streaming Tips,
Elgato, Community.
