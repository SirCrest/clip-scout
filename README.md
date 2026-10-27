# Clip Scout

An internal Elgato tool. Put a livestream in and get finished clips out, ready for Elgato's clips channel on
YouTube or for X.

Clip Scout does the mechanical work: downloading, transcribing, cutting, rendering, uploading. The judgement calls
(which moments are worth posting, how to tighten them, what to title them) are done by an AI agent you already use,
and every decision that matters goes past a person before anything is posted.

## The workflow

1. **Add a stream.** Drop a video file on the app, or paste a Twitch or YouTube link.
2. **Transcribe.** Clip Scout transcribes the stream on your machine, using an Elgato glossary so product names come
   out right.
3. **Pick.** The agent reads the transcript, fixes misheard words, and picks every self-contained talking point
   (`elgato/picking-guide.md`).
4. **Judge.** The agent rates each pick against the channel guide (`elgato/channel-guide.md`): channel-worthy, weak,
   off-topic or a duplicate. Clips with copyright-music risk are flagged.
5. **Review.** You sort the picks, best first: keep, maybe or cut. Staff-led clips and community clips are in
   separate lanes (YouTube and X).
6. **Edit.** Kept clips arrive already tightened: pauses, fillers, false starts and detours removed. You can put any
   word back or cut more, and choose a hard cut or a punch-in at each join.
7. **Render.** Each kept clip is rendered at source quality, with loudness levelled and captions.
8. **Publish.** The agent drafts titles and a description in the channel's style. You edit and approve, and Clip
   Scout uploads privately on your schedule, or exports a sheet to copy from.

Clips are cut points over the source video until you keep one, so nothing is rendered that won't be used.
