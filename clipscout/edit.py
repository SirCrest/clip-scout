"""Edit plans: cut dead air, fillers and detours out of a clip so the talk keeps moving.

Per clip, in the stream folder's edits/:
  <clip id>.detect.json  what the rules found: the clip's words re-transcribed with fillers kept (plus ~5 s of
                         context either side, flagged "m"), pauses, fillers, shot changes, the source's video facts
  <clip id>.rms.npy      the audio level every 10 ms over the same span (for snapping cut points to quiet)
  <clip id>.json         the edit decision list (EDL) that render.py follows:
    {"clip", "version", "source": "rules"|"agent"|"human", "layout", "punch_ok", "range": [in, out],
     "segments": [{"src_in", "src_out", "zoom"}], "removed": [{"id", "from", "to", "kind", "reason", "by"}],
     "cuts": [{"i", "at", "from", "to", "style", "why", "tight"}], "stats", "agent", "human", "updated"}
  `tight` marks a cut whose edge still lands in speech because the words run together: worth a listen.
  Removed kinds: pause and filler (rules), content (agent or person), trim (start or end moved in).
  The EDL is always rebuilt from detect + the agent's answer + the person's changes, so a later agent answer never
  overwrites what a person did.

Defaults come from how staff edited the clips they approved (17 of 73 had cuts inside): they removed pauses from
0.38 s up and cut them to almost nothing, took out some "uh"s, removed whole detours (a 62 s tangent, network-trouble
chatter, "later today we'll show you..."), and used plain hard cuts. Cut style here is chosen per cut: a hard cut
where the picture changes anyway or where zooming would crop stream graphics, a slight punch-in on a clean camera
shot so a jump doesn't show.
"""
import hashlib
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import library as lib

PAUSE_MIN = 0.45       # silences longer than this are cut
KEEP_MID = 0.12        # silence left where a pause inside a sentence is cut
KEEP_END = 0.22        # ... and between sentences
MIN_CUT = 0.18         # a cut must remove at least this much
MARGIN = 5.0           # context transcribed either side of the clip
ZOOM = 1.08            # punch-in scale
SHOT_GUARD = 0.3       # a cut this close to a shot change is a hard cut
SR, HOP = 16000, 0.01
ALIGN_TRUST = -2.0     # mean log-prob below which a word's aligned time isn't trusted
FILLERS = {'um', 'umm', 'uh', 'uhh', 'uhm', 'erm', 'er', 'ah', 'ahh', 'hmm', 'hm', 'mm', 'mhm'}
FILLER_PROMPT = ("Um, so, uh, I was like, you know, hmm... Uh, yeah. Um, I mean, it's, uh, the Stream Deck, um, "
                 "and Wave Link. ")
LAYOUTS = ('camera', 'camera_graphics', 'multi_cam', 'screen', 'product', 'mixed')
VERSION = 1


def _norm(word):
    return re.sub(r"[^a-z0-9']", '', word.lower())


def folder(stream):
    f = stream.path('edits')
    f.mkdir(exist_ok=True)
    return f


# ---------------------------------------------------------------- audio level

def audio(src, start, end):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{start:.3f}', '-i', str(src), '-t', f'{end - start:.3f}',
                          '-vn', '-ac', '1', '-ar', str(SR), '-f', 's16le', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


class Level:
    """Audio level in dB every 10 ms from t0, with a speech threshold set from this clip's own loud and quiet."""

    def __init__(self, db, t0):
        self.db, self.t0 = np.asarray(db, np.float32), t0
        floor, speech = np.percentile(self.db, 10), np.percentile(self.db, 90)
        self.thr = float(max(floor + 6, floor + 0.35 * (speech - floor)))

    @classmethod
    def of(cls, samples, t0):
        n = len(samples) // int(SR * HOP)
        frames = samples[:n * int(SR * HOP)].reshape(n, -1)
        return cls(20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6), t0)

    def _i(self, t):
        return int(min(max((t - self.t0) / HOP, 0), len(self.db) - 1))

    def at(self, t):
        return float(self.db[self._i(t)])

    def quietest(self, lo, hi):
        a, b = self._i(lo), self._i(hi)
        if b <= a:
            return (lo + hi) / 2
        return self.t0 + (a + int(np.argmin(self.db[a:b + 1]))) * HOP + HOP / 2

    def silent_runs(self, lo, hi, min_len):
        a, b = self._i(lo), self._i(hi)
        quiet = self.db[a:b + 1] < self.thr
        runs, start = [], None
        for k, q in enumerate(np.r_[quiet, False]):
            if q and start is None:
                start = k
            elif not q and start is not None:
                if (k - start) * HOP >= min_len:
                    runs.append((self.t0 + (a + start) * HOP, self.t0 + (a + k) * HOP))
                start = None
        return runs


def level(stream, clip):
    f = folder(stream) / f"{clip['id']}.rms.npy"
    det = load_detect(stream, clip)
    if f.exists() and det:
        return Level(np.load(f).astype(np.float32), det['level_t0'])
    lo, hi = span(stream, clip)
    return Level.of(audio(stream.media, lo, hi), lo)


# ---------------------------------------------------------------- detection

def span(stream, clip):
    dur = stream.meta.get('duration') or 1e9
    return max(0.0, clip['hook_at'] - MARGIN), min(dur, clip['source_out'] + MARGIN)


@lru_cache
def video_facts(src):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height,avg_frame_rate,r_frame_rate', '-of', 'json', str(src)],
                         capture_output=True, text=True).stdout
    s = json.loads(out)['streams'][0]
    num, den = (s.get('avg_frame_rate') or s['r_frame_rate']).split('/')
    fps = float(num) / float(den) if float(den) else 60.0
    for nominal in (23.976, 24, 25, 29.97, 30, 50, 59.94, 60):  # Twitch reports e.g. 19837000/330617
        if abs(fps - nominal) < 0.05:
            fps = nominal
    return {'width': s['width'], 'height': s['height'], 'fps': fps}


def transcribe_fillers(samples, offset):
    """Filler words ("um", "uh"...) in the audio. Stream transcripts drop them (0 in the year set's test clips), so
    the clip is transcribed again with an initial prompt full of disfluencies and no voice filter, which finds 5-16
    per 2 minutes. Only the fillers are used: without the voice filter the rest of that text loses its punctuation
    after the first minute, so the stream transcript stays the source of the words."""
    from . import elgato, transcribe
    whisper = transcribe.model().model  # the pipeline's WhisperModel; clip-length audio needs no batching
    # temperature 0 with no fallback thresholds: the default falls back to random sampling when a window "fails",
    # which made the same clip give 7 fillers on one run and none on the next
    segments, _ = whisper.transcribe(samples, language='en', beam_size=5, word_timestamps=True, vad_filter=False,
                                     condition_on_previous_text=False, initial_prompt=FILLER_PROMPT + elgato.glossary(),
                                     temperature=0.0, compression_ratio_threshold=None, log_prob_threshold=None,
                                     no_speech_threshold=None)
    return [{'start': round(offset + w.start, 3), 'end': round(offset + w.end, 3), 'w': w.word.strip(),
             'p': round(w.probability, 2)} for s in segments for w in (s.words or []) if is_filler(w.word)]


ALIGN_MODEL = 'facebook/wav2vec2-base-960h'
FRAME = 0.02  # one wav2vec2 frame
_aligner = None


def _load_aligner():
    """(torch, model, vocab, device) or None when torch/transformers aren't installed (the `music` extra)."""
    global _aligner
    if _aligner is None:
        try:
            import torch
            from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
            # ctranslate2 (Whisper) loads its own cudnn64_9.dll; when both are in one process torch's cuDNN calls
            # fail ("Could not load symbol cudnnGetLibConfig"). Plain CUDA kernels are plenty fast for this model.
            torch.backends.cudnn.enabled = False
            proc = Wav2Vec2Processor.from_pretrained(ALIGN_MODEL)
            dev = 'cuda' if torch.cuda.is_available() else 'cpu'
            model = Wav2Vec2ForCTC.from_pretrained(ALIGN_MODEL).to(dev).eval()
            _aligner = (torch, model, proc.tokenizer.get_vocab(), dev)
        except Exception:
            _aligner = False
    return _aligner or None


def emissions(samples, chunk=20.0, context=2.0):
    """CTC log-probabilities every 20 ms, computed in overlapping chunks (attention over minutes won't fit)."""
    torch, model, _, dev = _load_aligner()
    x = (samples - samples.mean()) / np.sqrt(samples.var() + 1e-7)
    step, ctx, out = int(chunk * SR), int(context * SR), []
    with torch.inference_mode():
        for a in range(0, len(x), step):
            lo, hi = max(0, a - ctx), min(len(x), a + step + ctx)
            logits = model(torch.from_numpy(x[lo:hi]).to(dev)[None]).logits[0].float()
            lp = torch.log_softmax(logits, -1).cpu().numpy()
            skip = int(round((a - lo) / SR / FRAME))
            keep = int(round((min(a + step, len(x)) - a) / SR / FRAME))
            out.append(lp[skip:skip + keep])
    return np.concatenate(out) if out else np.zeros((0, 32), np.float32)


def ctc_path(lp, tokens, blank=0):
    """Viterbi forced alignment: for each token, the frames it occupies (list of (first, last)); None if it can't
    fit."""
    T, n = len(lp), len(tokens)
    if n == 0 or T < n:
        return None
    ext = np.full(2 * n + 1, blank)
    ext[1::2] = tokens
    S, NEG = len(ext), -1e9
    skip_ok = np.zeros(S, bool)
    skip_ok[2:] = (ext[2:] != blank) & (ext[2:] != ext[:-2])
    dp = np.full(S, NEG)
    dp[0], dp[1] = lp[0, blank], lp[0, ext[1]]
    back = np.zeros((T, S), np.int8)
    emit = lp[:, ext]
    for t in range(1, T):
        p1 = np.r_[NEG, dp[:-1]]
        p2 = np.where(skip_ok, np.r_[NEG, NEG, dp[:-2]], NEG)
        best = np.maximum(np.maximum(dp, p1), p2)
        back[t] = np.where(best == dp, 0, np.where(best == p1, 1, 2))
        dp = best + emit[t]
    s = S - 1 if dp[S - 1] >= dp[S - 2] else S - 2
    spans = [None] * n
    for t in range(T - 1, -1, -1):
        if s % 2:
            k = s // 2
            spans[k] = (t, spans[k][1]) if spans[k] else (t, t)
        s -= int(back[t, s])
    return spans


def _letters(word):
    return re.sub(r"[^A-Z']", '', word.upper())


def align(words, samples, t0):
    """Refine word times to ~20 ms with forced alignment; words get 'a': alignment confidence (mean log-prob).
    Unalignable words (no letters, e.g. "120") are placed between their aligned neighbours. No-op without torch."""
    al = _load_aligner()
    if not al or not words:
        return words
    _, _, vocab, _ = al
    lp = emissions(samples)
    sep = vocab.get('|')
    # groups of words between clear gaps, aligned inside a padded window each
    groups, cur = [], [0]
    for i in range(1, len(words)):
        if words[i]['start'] - words[i - 1]['end'] > 0.6 or len(cur) >= 40:
            groups.append(cur)
            cur = []
        cur.append(i)
    groups.append(cur)
    out = [dict(w) for w in words]
    for g in groups:
        lo = max(0.0, words[g[0]]['start'] - 0.5 - t0)
        hi = min(len(lp) * FRAME, words[g[-1]]['end'] + 0.5 - t0)
        f0, f1 = int(lo / FRAME), int(hi / FRAME)
        tokens, owner = [], []
        for i in g:
            chars = [vocab[c] for c in _letters(words[i]['w']) if c in vocab]
            if chars and tokens:
                tokens.append(sep)
                owner.append(None)
            tokens += chars
            owner += [i] * len(chars)
        spans = ctc_path(lp[f0:f1], tokens, blank=vocab.get('<pad>', 0))
        if not spans:
            continue
        per = {}
        for k, (sp, i) in enumerate(zip(spans, owner)):
            if i is None or sp is None:
                continue
            a, b = sp
            conf = float(lp[f0 + a:f0 + b + 1, tokens[k]].mean())
            s0, e0, c0 = per.get(i, (a, b, []))
            per[i] = (min(s0, a), max(e0, b), c0 + [conf])
        for i, (a, b, confs) in per.items():
            out[i]['start'] = round(t0 + (f0 + a) * FRAME, 3)
            out[i]['end'] = round(t0 + (f0 + b + 1) * FRAME, 3)
            out[i]['a'] = round(float(np.mean(confs)), 2)
    for i, w in enumerate(out):  # words with nothing to align sit in the gap their neighbours leave
        if 'a' in w:
            continue
        prev = next((out[j] for j in range(i - 1, -1, -1) if 'a' in out[j]), None)
        nxt = next((out[j] for j in range(i + 1, len(out)) if 'a' in out[j]), None)
        if prev and nxt and prev['end'] <= nxt['start']:
            w['start'], w['end'] = max(w['start'], prev['end']), min(max(w['end'], prev['end']), nxt['start'])
    for prev, w in zip(out, out[1:]):  # neighbouring groups' windows overlap; keep words in order
        if w['start'] < prev['end']:
            w['start'] = prev['end']
        w['end'] = max(w['end'], w['start'])
    return out


def merge_fillers(words, fillers):
    """Insert fillers into the word list by time, skipping any the transcript already has nearby."""
    out = list(words)
    for f in fillers:
        mid = (f['start'] + f['end']) / 2
        if any(is_filler(w['w']) and abs((w['start'] + w['end']) / 2 - mid) < 0.5 for w in out):
            continue
        out.append({**f, 'f': 1, 'wmid': round(mid, 3)})  # Whisper's guess, kept: alignment can't place fillers
    out.sort(key=lambda w: ((w['start'] + w['end']) / 2, w['start']))
    return out


def clip_bounds(words, clip):
    """First and last word index inside the clip's range."""
    a, b = clip['hook_at'], clip['source_out']
    inside = [i for i, w in enumerate(words) if w['start'] >= a - 0.15 and w['end'] <= b + 0.15]
    if not inside:
        inside = [i for i, w in enumerate(words) if a <= (w['start'] + w['end']) / 2 <= b] or [0]
    return inside[0], inside[-1]


def is_filler(word):
    return _norm(word) in FILLERS


def ends_sentence(word):
    return word.rstrip().endswith(('.', '?', '!'))


def find_pauses(words, w0, w1, lvl):
    pauses = []
    lo, hi = words[w0]['start'], words[w1]['end']
    for s, e in lvl.silent_runs(lo, hi, PAUSE_MIN):
        # Whisper stretches words over silence, but a short word sitting mostly inside the run is quiet speech
        spoken = [w for w in words[w0:w1 + 1] if not is_filler(w['w']) and w['end'] - w['start'] < 0.8
                  and min(e, w['end']) - max(s, w['start']) > 0.5 * (w['end'] - w['start'])]
        if spoken:
            continue
        before = [w for w in words[w0:w1 + 1] if w['start'] < s]
        keep = KEEP_END if before and ends_sentence(before[-1]['w']) else KEEP_MID
        cut = (round(s + keep / 2, 3), round(e - keep / 2, 3))
        if cut[1] - cut[0] >= MIN_CUT:
            pauses.append({'id': f'p{len(pauses) + 1}', 'from': cut[0], 'to': cut[1], 'gap': round(e - s, 2)})
    return pauses


def _voiced_runs(lvl, lo, hi, min_len=0.08):
    a, b = lvl._i(lo), lvl._i(hi)
    voiced = lvl.db[a:b + 1] > lvl.thr + 6
    runs, start = [], None
    for k, v in enumerate(np.r_[voiced, False]):
        if v and start is None:
            start = k
        elif not v and start is not None:
            if (k - start) * HOP >= min_len:
                runs.append((lvl.t0 + (a + start) * HOP, lvl.t0 + (a + k) * HOP))
            start = None
    return runs


def find_fillers(words, w0, w1, lvl):
    """Where each "um"/"uh" really is, and whether a rule may cut it.

    Filler timestamps can't be trusted: Whisper puts them anywhere nearby, and the forced aligner (trained on read
    speech, which has none) squeezes them into a frame or two. The real words around a filler are aligned well,
    though, so its sound is the voiced burst in the gap between them. A filler is `safe` to cut when that burst is
    clear of both neighbours; one run straight into a word stays for the agent or a person to decide."""
    fillers = []
    for i in range(w0 + 1, w1 + 1):
        w = words[i]
        if not is_filler(w['w']):
            continue
        prev = next((words[j] for j in range(i - 1, -1, -1) if not is_filler(words[j]['w'])), None)
        nxt = next((words[j] for j in range(i + 1, len(words)) if not is_filler(words[j]['w'])), None)
        prev_end = prev['end'] if prev else w['start'] - 0.3
        next_start = nxt['start'] if nxt else w['end'] + 0.3
        entry = {'id': f'f{len(fillers) + 1}', 'word': i, 'text': w['w'], 'safe': False,
                 'from': round(w['start'], 3), 'to': round(w['end'], 3)}
        # a neighbour the aligner wasn't sure of may really be sitting in that gap (seen: "noise" placed on silence)
        trusted = all(x is None or x.get('a', 0) >= ALIGN_TRUST for x in (prev, nxt))
        if trusted and next_start - prev_end >= 0.12:
            mid = w.get('wmid', (w['start'] + w['end']) / 2)
            runs = _voiced_runs(lvl, prev_end + 0.02, next_start - 0.02)
            if runs:
                s, e = min(runs, key=lambda r: 0 if r[0] <= mid <= r[1] else min(abs(r[0] - mid), abs(r[1] - mid)))
                if e - s <= 1.0 and min(abs(s - mid), abs(e - mid), 0 if s <= mid <= e else 9) <= 0.6:
                    left = lvl.quietest(prev_end, s) if s - prev_end > 0.03 else s
                    right = lvl.quietest(e, next_start) if next_start - e > 0.03 else e
                    entry.update({'from': round(left, 3), 'to': round(right, 3), 'safe': True})
        fillers.append(entry)
    return fillers


def detect(stream, clip):
    """Run the rules on one clip and save edits/<clip id>.detect.json (+ .rms.npy). Returns the detect dict."""
    from . import shots
    src = stream.media
    lo, hi = span(stream, clip)
    samples = audio(src, lo, hi)
    lvl = Level.of(samples, lo)
    words = [{'start': round(w['start'], 3), 'end': round(w['end'], 3), 'w': w['word'].strip(), 'p': w.get('p', 1)}
             for w in stream.words() if lo <= w['start'] < hi and w['word'].strip()]
    fillers = transcribe_fillers(samples, lo)
    if not words:  # no stream transcript here: fall back to a plain transcription of the clip
        import tempfile
        from . import transcribe
        with tempfile.TemporaryDirectory(prefix='scout-edit-') as tmp:
            wav = Path(tmp) / 'clip.wav'
            transcribe.extract_audio(src, lo, hi - lo, wav)
            words = [{'start': x['start'], 'end': x['end'], 'w': x['word'].strip(), 'p': x['p']}
                     for s in transcribe.transcribe_file(wav, offset=lo) for x in s['words']]
    words = align(merge_fillers(words, fillers), samples, lo)
    w0, w1 = clip_bounds(words, clip)
    for i, w in enumerate(words):
        if i < w0 or i > w1:
            w['m'] = 1
        if is_filler(w['w']):
            w['f'] = 1
    sig = hashlib.sha1('|'.join(w['w'] for w in words).encode()).hexdigest()[:12]
    det = {'clip': clip['id'], 'range': [clip['hook_at'], clip['source_out']], 'sig': sig, 'w0': w0, 'w1': w1,
           'level_t0': lo, 'thr': round(lvl.thr, 1), 'words': words,
           'pauses': find_pauses(words, w0, w1, lvl), 'fillers': find_fillers(words, w0, w1, lvl),
           'shots': shots.detect(src, clip['hook_at'], clip['source_out']), 'video': video_facts(str(src)),
           'made': lib.now()}
    f = folder(stream)
    np.save(f / f"{clip['id']}.rms.npy", lvl.db.astype(np.float16))
    lib.write_json(f / f"{clip['id']}.detect.json", det, indent=None)
    return det


def load_detect(stream, clip):
    det = lib.read_json(folder(stream) / f"{clip['id']}.detect.json")
    if det and det.get('range') != [clip['hook_at'], clip['source_out']]:
        return None  # the clip was re-planned or trimmed upstream
    return det


# ---------------------------------------------------------------- the EDL

def _quant(t, fps):
    return round(round(t * fps) / fps, 6)


def _snap_before(words, i, lvl):
    """A quiet point just before word i (inside the gap from the previous word). When the two words run together
    there is no gap, so look a little wider for the dip between them."""
    w = words[i]
    prev_end = words[i - 1]['end'] if i > 0 else w['start'] - 0.3
    t = lvl.quietest(max(prev_end, w['start'] - 0.3), w['start'] + 0.02)
    if lvl.at(t) > lvl.thr + 6:
        t = lvl.quietest(max(prev_end - 0.08, w['start'] - 0.3), w['start'] + 0.08)
    return t


def _snap_after(words, i, lvl):
    w = words[i]
    next_start = words[i + 1]['start'] if i + 1 < len(words) else w['end'] + 0.3
    t = lvl.quietest(w['end'] - 0.02, min(next_start, w['end'] + 0.3))
    if lvl.at(t) > lvl.thr + 6:
        t = lvl.quietest(w['end'] - 0.08, min(next_start + 0.08, w['end'] + 0.3))
    return t


def _tight(lvl, r):
    """A cut whose edge still sits in speech (the words run together): worth a listen."""
    return lvl.at(r['from']) > lvl.thr + 6 or lvl.at(r['to']) > lvl.thr + 6


def build(stream, clip, det, agent=None, human=None, lvl=None):
    """The EDL for a clip from its detection, an agent's answer and a person's changes (either may be None)."""
    words, fps = det['words'], det['video']['fps']
    agent, human = agent or {}, human or {}
    lvl = lvl or level(stream, clip)
    restored = set(human.get('restore', [])) | set(agent.get('keep', []))
    w0, w1 = det['w0'], det['w1']

    # the clip's range: from a quiet point just before its first word to a short tail after its last
    first = agent['start'] if agent.get('start') is not None else w0
    last = agent['end'] if agent.get('end') is not None else w1
    plan_in, plan_out = det['range']
    t_in = min(_snap_before(words, first, lvl), words[first]['start'] - 0.02)
    nxt = words[last + 1]['start'] if last + 1 < len(words) else 1e9
    t_out = min(words[last]['end'] + 0.35, nxt - 0.05)
    if last == w1:
        t_out = min(t_out, max(plan_out, words[last]['end'] + 0.05))
    t_out = max(t_out, words[last]['end'] + 0.02)
    trim = human.get('trim') or {}
    if 't0' in restored:
        t_in = min(t_in, plan_in)
    if 't1' in restored:
        t_out = max(t_out, plan_out)
    t_in, t_out = float(trim.get('in', t_in)), float(trim.get('out', t_out))

    def by(end):
        return 'human' if end in trim else 'agent' if agent.get('start' if end == 'in' else 'end') is not None else 'rules'
    removed = []
    if t_in - plan_in > 0.2:
        removed.append({'id': 't0', 'from': plan_in, 'to': round(t_in, 3), 'kind': 'trim',
                        'reason': 'start moved in', 'by': by('in')})
    if plan_out - t_out > 0.2:
        removed.append({'id': 't1', 'from': round(t_out, 3), 'to': plan_out, 'kind': 'trim',
                        'reason': 'dead air at the end' if by('out') == 'rules' else 'end moved in', 'by': by('out')})
    for p in det['pauses']:
        if p['id'] not in restored and t_in <= p['from'] and p['to'] <= t_out:
            removed.append({'id': p['id'], 'from': p['from'], 'to': p['to'], 'kind': 'pause',
                            'reason': f"{p['gap']:.1f} s pause", 'by': 'rules'})
    for f in det['fillers']:
        if f['safe'] and f['id'] not in restored and t_in <= f['from'] and f['to'] <= t_out:
            removed.append({'id': f['id'], 'from': f['from'], 'to': f['to'], 'kind': 'filler',
                            'reason': f"\"{f['text']}\"", 'by': 'rules'})
    for n, r in enumerate(agent.get('remove', []), 1):
        rid = f'c{n}'
        if rid in restored:
            continue
        a, b = max(r['from'], first), min(r['to'], last)
        if a > b:
            continue
        removed.append({'id': rid, 'from': round(_snap_before(words, a, lvl), 3), 'to': round(_snap_after(words, b, lvl), 3),
                        'kind': 'content', 'reason': r.get('reason', ''), 'by': 'agent', 'words': [a, b]})
    for n, r in enumerate(human.get('remove', []), 1):
        a, b = sorted((float(r['from']), float(r['to'])))
        a, b = lvl.quietest(a - 0.1, a + 0.1), lvl.quietest(b - 0.1, b + 0.1)
        removed.append({'id': f'h{n}', 'from': round(a, 3), 'to': round(b, 3), 'kind': 'content',
                        'reason': r.get('reason', 'removed by hand'), 'by': 'human'})

    for r in removed:
        if r['kind'] != 'trim' and _tight(lvl, r):
            r['tight'] = True
    segments = _keep(t_in, t_out, [r for r in removed if r['kind'] != 'trim'], words, fps, lvl)
    punch_ok = bool(human['punch_ok']) if 'punch_ok' in human else bool(agent.get('punch_in_ok', False))
    layout = agent.get('layout', 'unknown')
    agent_style = {}
    for s in agent.get('styles', []):  # {"after_word": i, "style": ...}: the join nearest that word's end
        t = words[min(s['after_word'], len(words) - 1)]['end']
        if len(segments) > 1:
            agent_style[min(range(len(segments) - 1), key=lambda k: abs(segments[k]['src_out'] - t))] = s['style']
    human_style = {int(k): v for k, v in (human.get('style') or {}).items()}
    segments, cuts = _styles(segments, det['shots'], punch_ok, human_style, agent_style, fps)
    edited = sum(s['src_out'] - s['src_in'] for s in segments)
    by_kind = {}
    for r in removed:
        by_kind[r['kind']] = round(by_kind.get(r['kind'], 0) + r['to'] - r['from'], 2)
    source = 'human' if human else 'agent' if agent else 'rules'
    for c in cuts:  # a join is tight when a removal touching it is
        c['tight'] = any(r.get('tight') and (abs(r['from'] - c['from']) < 0.05 or abs(r['to'] - c['to']) < 0.05)
                         for r in removed)
    return {'clip': clip['id'], 'version': VERSION, 'det_sig': det.get('sig'), 'source': source, 'layout': layout,
            'punch_ok': punch_ok,
            'range': [round(t_in, 3), round(t_out, 3)], 'segments': segments, 'removed': removed, 'cuts': cuts,
            'stats': {'original': round(plan_out - plan_in, 2), 'edited': round(edited, 2),
                      'removed': by_kind, 'cuts': len(cuts)},
            'agent': agent or None, 'human': human or None, 'note': agent.get('note'), 'updated': lib.now()}


def _keep(t_in, t_out, removals, words, fps, lvl=None):
    """Kept pieces of [t_in, t_out] once removals are taken out, edges on the frame grid. A short kept sliver is
    dropped only when it holds no word and no sound: word times can be wrong, the audio isn't."""
    spans = sorted((max(r['from'], t_in), min(r['to'], t_out)) for r in removals if r['to'] > t_in and r['from'] < t_out)
    union = []
    for a, b in spans:
        if union and a <= union[-1][1] + 0.02:
            union[-1][1] = max(union[-1][1], b)
        else:
            union.append([a, b])
    pieces, cur = [], t_in
    for a, b in union:
        if a > cur:
            pieces.append((cur, a))
        cur = max(cur, b)
    if t_out > cur:
        pieces.append((cur, t_out))
    mids = [(w['start'] + w['end']) / 2 for w in words if not is_filler(w['w'])]
    segs = []
    for a, b in pieces:
        qa, qb = _quant(a, fps), _quant(b, fps)
        has_word = any(a <= m <= b for m in mids)
        has_sound = bool(lvl and _voiced_runs(lvl, a, b, min_len=0.06))
        if qb - qa < 1 / fps or (qb - qa < 0.4 and not has_word and not has_sound):
            continue
        if segs and qa <= segs[-1]['src_out']:
            segs[-1]['src_out'] = qb
            continue
        segs.append({'src_in': qa, 'src_out': qb, 'zoom': 1.0})
    return segs


def _styles(segments, shot_times, punch_ok, human_style, agent_style, fps):
    """Hard cut or punch-in for each join; zooms alternate on punch-ins and never carry across a shot change.
    Returns (segments with zoom, cuts). A segment split only to end a zoom at a shot change is contiguous with
    the next one (same source time), which is not a cut."""
    out, cuts, zoom = [], [], 1.0
    for k, seg in enumerate(segments):
        seg = dict(seg)
        if k:
            prev = segments[k - 1]
            crosses = any(prev['src_out'] - SHOT_GUARD <= s <= seg['src_in'] + SHOT_GUARD for s in shot_times)
            rule = 'hard' if crosses or not punch_ok else 'punch'
            style = human_style.get(k - 1) or agent_style.get(k - 1) or rule
            why = ('by hand' if k - 1 in human_style else 'agent' if k - 1 in agent_style else
                   'shot change' if crosses else 'zoom would crop the picture' if not punch_ok else 'same shot')
            if style == 'punch':
                zoom = ZOOM if zoom == 1.0 else 1.0
            elif crosses:
                zoom = 1.0
            cuts.append({'i': k - 1, 'from': prev['src_out'], 'to': seg['src_in'], 'style': style, 'why': why})
        seg['zoom'] = zoom
        inside = [s for s in shot_times if seg['src_in'] + 0.1 < s < seg['src_out'] - 0.1]
        if zoom != 1.0 and inside:
            split = _quant(inside[0], fps)
            out.append({**seg, 'src_out': split})
            seg = {'src_in': split, 'src_out': seg['src_out'], 'zoom': 1.0}
            zoom = 1.0
        out.append(seg)
    t, starts = 0.0, []
    for seg in out:
        starts.append(t)
        t += seg['src_out'] - seg['src_in']
    joins = [n for n in range(1, len(out)) if out[n - 1]['src_out'] != out[n]['src_in']]
    for c, n in zip(cuts, joins):
        c['at'] = round(starts[n], 3)
    return out, cuts


# ---------------------------------------------------------------- files and the app's calls

def edl_path(stream, clip):
    return folder(stream) / f"{clip['id']}.json"


def load_edl(stream, clip):
    edl = lib.read_json(edl_path(stream, clip))
    if edl and edl.get('version') == VERSION and load_detect(stream, clip):
        return edl
    return None


def save(stream, clip, edl):
    lib.write_json(edl_path(stream, clip), edl, indent=None)
    return edl


def clip_by_id(stream, cid):
    for c in stream.clips():
        if c['id'] == cid:
            return c
    raise KeyError(f'{stream.id}: no clip {cid}')


def ensure(stream, clip, open_task=True):
    """The clip's EDL; when missing, detect + the rules-only EDL now, and an agent task to refine it.

    After a re-detection the agent's answer (word numbers) is kept only if the words are exactly the same;
    otherwise its task is cancelled and a new one opened. A person's changes (times) always carry over."""
    edl = load_edl(stream, clip)
    if edl:
        return edl
    det = load_detect(stream, clip) or detect(stream, clip)
    old = lib.read_json(edl_path(stream, clip)) or {}
    agent = old.get('agent') if old.get('det_sig') and old.get('det_sig') == det.get('sig') else None
    edl = save(stream, clip, build(stream, clip, det, agent=agent, human=old.get('human'), lvl=level(stream, clip)))
    if not agent:
        stale = _task_for(stream, clip)
        if stale and stale['state'] in ('done', 'failed'):
            from . import tasks
            tasks._save({**stale, 'state': 'cancelled', 'reason': 'the clip was detected again'})
        if open_task:
            open_tasks_for([f"{stream.id}/{clip['id']}"])
    return edl


def update(stream, clip, changes):
    """Apply a person's changes (see module doc) on top of the agent's answer and save. Returns the new EDL."""
    edl = ensure(stream, clip, open_task=False)
    human = dict(edl.get('human') or {})
    for rid in changes.get('restore', []):
        if rid.startswith('h'):  # undoing one's own removal drops it
            n = int(rid[1:]) - 1
            rem = human.get('remove', [])
            if 0 <= n < len(rem):
                human['remove'] = rem[:n] + rem[n + 1:]
        elif rid in ('t0', 't1'):
            trim = dict(human.get('trim') or {})
            trim.pop('in' if rid == 't0' else 'out', None)
            human['trim'] = trim
            human['restore'] = sorted(set(human.get('restore', [])) | {rid})
        else:
            human['restore'] = sorted(set(human.get('restore', [])) | {rid})
    for r in changes.get('remove', []):
        human.setdefault('remove', []).append({'from': float(r['from']), 'to': float(r['to']),
                                               'reason': r.get('reason', 'removed by hand')})
    for k, style in (changes.get('style') or {}).items():
        human.setdefault('style', {})[str(k)] = style
    if changes.get('trim'):
        trim = dict(human.get('trim') or {})
        trim.update({k: float(v) for k, v in changes['trim'].items() if k in ('in', 'out')})
        human['trim'] = trim
        human['restore'] = [r for r in human.get('restore', []) if r not in ('t0', 't1')]
    if 'punch_ok' in changes:
        human['punch_ok'] = bool(changes['punch_ok'])
    human = {k: v for k, v in human.items() if v not in ({}, [], None)}
    det = load_detect(stream, clip)
    return save(stream, clip, build(stream, clip, det, agent=edl.get('agent'), human=human))


def _task_for(stream, clip):
    key = f"{stream.id}/{clip['id']}"
    from . import tasks
    for t in tasks.list_tasks(kind='edit', stream=stream.id):
        if key in t.get('keys', []) and t['state'] != 'cancelled':
            return t
    return None


def view(stream, clip):
    """Everything the Edit screen shows for one clip."""
    edl = ensure(stream, clip, open_task=False)
    det = load_detect(stream, clip)
    task = _task_for(stream, clip)
    return {'clip': clip['id'], 'edl': edl,
            'words': [{'i': i, 's': w['start'], 'e': w['end'], 'w': w['w'], **({'f': 1} if w.get('f') else {}),
                       **({'m': 1} if w.get('m') else {})} for i, w in enumerate(det['words'])],
            'pauses': det['pauses'], 'fillers': det['fillers'], 'shots': det['shots'], 'video': det['video'],
            'task': {'id': task['id'], 'state': task['state']} if task else None}


# ---------------------------------------------------------------- agent task

def _resolve(keys):
    """[(stream, clip)] for "<stream>/<clip>" keys, or every kept/maybe (else judge-top) clip of a bare stream id."""
    out = []
    decisions = lib.read_json(lib.LIBRARY / 'decisions.json', {}) or {}
    decisions = decisions.get('decisions', decisions)
    for key in keys:
        if '/' in key:
            sid, cid = key.split('/', 1)
            stream = lib.get_stream(sid)
            out.append((stream, clip_by_id(stream, cid)))
            continue
        stream = lib.get_stream(key)
        clips = stream.clips()
        kept = [c for c in clips if (lambda d: (d.get('d') if isinstance(d, dict) else d) in ('keep', 'maybe'))(
            decisions.get(f"{stream.id}/{c['id']}", ''))]
        if not kept:
            judge = stream.load('judge.json', {}) or {}
            kept = [c for c in clips if (judge.get(c['id']) or c.get('judge') or {}).get('bin') == 'top']
        out += [(stream, c) for c in kept]
    return out


def _sentences(words, lo, hi, pauses_by_end):
    lines, cur = [], []
    for i in range(lo, hi + 1):
        w = words[i]
        if cur and w['start'] - words[i - 1]['end'] > 1.0:
            lines.append(cur)
            cur = []
        cur.append(i)
        if ends_sentence(w['w']):
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return lines


def packet(stream, clip, det, frames):
    words, w0, w1 = det['words'], det['w0'], det['w1']
    lines = [f"=== CLIP {clip['id']} ===",
             f"title: {clip.get('title', '')}",
             f"summary: {clip.get('summary', '')}",
             f"length: {clip['source_out'] - clip['hook_at']:.1f} s (stream {clip['hook_at']:.1f}-{clip['source_out']:.1f} s)",
             f"frames: {', '.join(frames) if frames else '(none)'}",
             f"shot changes at (stream s): {', '.join(f'{s:.1f}' for s in det['shots']) or 'none'}",
             f"words in the clip: {w0}-{w1}; words before {w0} and after {w1} are context only.", '']
    pause_after = {}
    for p in det['pauses']:
        before = [i for i in range(w0, w1 + 1) if words[i]['end'] <= p['from'] + 0.2]
        if before:
            pause_after[before[-1]] = p
    filler_ids = {f['word']: f for f in det['fillers'] if f['safe']}
    for idx in _sentences(words, 0, len(words) - 1, pause_after):
        tag = ' (context)' if all(words[i].get('m') for i in idx) else ''
        parts = []
        for i in idx:
            w = words[i]['w']
            if i in filler_ids:
                parts.append(f"{i}:{w}*{filler_ids[i]['id']}")
            else:
                parts.append(f'{i}:{w}')
            if i in pause_after:
                p = pause_after[i]
                parts.append(f"~{p['gap']:.1f}s:{p['id']}")
        lines.append(f"[{words[idx[0]]['start']:.1f}]{tag} " + ' '.join(parts))
    return '\n'.join(lines) + '\n'


def _frames(stream, clip, det, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    a, b = clip['hook_at'], clip['source_out']
    times = [a + 1.0, (a + b) / 2, b - 1.0] if b - a > 4 else [(a + b) / 2]
    paths = []
    for n, t in enumerate(times, 1):
        f = out_dir / f"{clip['id']}-{n}.jpg"
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(stream.media), '-frames:v', '1',
                        '-vf', 'scale=640:-2', '-q:v', '5', str(f)], capture_output=True)
        if f.exists():
            paths.append(f)
    return paths


def open_tasks_for(keys, batch_clips=5, batch_words=2500):
    """Open edit tasks for these clips (several clips of one stream per task). Returns the task ids."""
    from . import tasks
    pairs = _resolve(keys)
    by_stream = {}
    for stream, clip in pairs:
        by_stream.setdefault(stream.id, (stream, []))[1].append(clip)
    ids = []
    for sid, (stream, clips) in by_stream.items():
        batch, n_words = [], 0
        batches = []
        for clip in clips:
            if _task_for(stream, clip):
                continue
            det = load_detect(stream, clip) or detect(stream, clip)
            size = det['w1'] - det['w0'] + 1
            if batch and (len(batch) >= batch_clips or n_words + size > batch_words):
                batches.append(batch)
                batch, n_words = [], 0
            batch.append((clip, det))
            n_words += size
        if batch:
            batches.append(batch)
        for batch in batches:
            name = batch[0][0]['id'] + (f'+{len(batch) - 1}' if len(batch) > 1 else '')
            keys_ = [f"{sid}/{c['id']}" for c, _ in batch]
            tid = tasks.create('edit', sid, name, tasks.prompt('edit'), '', keys=keys_)
            frames_dir = tasks.folder(tid) / 'frames'
            text = []
            for clip, det in batch:
                frames = [tasks.rel(p) for p in _frames(stream, clip, det, frames_dir)]
                text.append(packet(stream, clip, det, frames))
            (tasks.folder(tid) / 'input.txt').write_text('\n'.join(text), encoding='utf-8')
            ids.append(tid)
    return ids


def check(task, output):
    errors = []
    answers = {a['clip']: a for a in output.get('clips', [])}
    want = [k.split('/', 1)[1] for k in task['keys']]
    stream = lib.get_stream(task['stream'])
    for cid in want:
        if cid not in answers:
            errors.append(f'clips: no answer for clip {cid}')
    for cid, a in answers.items():
        if cid not in want:
            errors.append(f'clips: {cid} is not a clip in this task')
            continue
        det = load_detect(stream, clip_by_id(stream, cid))
        if not det:
            errors.append(f'{cid}: the clip changed since this task was made; answer can\'t be applied')
            continue
        n, w0, w1 = len(det['words']), det['w0'], det['w1']
        first = a.get('start') if a.get('start') is not None else w0
        last = a.get('end') if a.get('end') is not None else w1
        if not (0 <= first < n and 0 <= last < n):
            errors.append(f'{cid}: start/end must be word numbers between 0 and {n - 1}')
            continue
        if first > w0 + 25:
            errors.append(f'{cid}: start {first} is too far into the clip; the hook (word {w0}) must stay first')
        if last < first + 5:
            errors.append(f'{cid}: end {last} leaves almost nothing')
        total = 0
        for r in a.get('remove', []):
            if r['from'] > r['to']:
                errors.append(f"{cid}: remove {r['from']}-{r['to']}: from must be <= to")
            elif r['from'] <= first or r['to'] >= last:
                errors.append(f"{cid}: remove {r['from']}-{r['to']} must be inside the kept words "
                              f"({first + 1}-{last - 1}); use start/end to trim the ends")
            total += r['to'] - r['from'] + 1
        if total > 0.6 * (last - first + 1):
            errors.append(f'{cid}: removes {total} of {last - first + 1} words; too much of the clip')
        ids = {p['id'] for p in det['pauses']} | {f['id'] for f in det['fillers']}
        for k in a.get('keep', []):
            if k not in ids:
                errors.append(f'{cid}: keep "{k}" is not a pause or filler id in this clip')
        for s in a.get('styles', []):
            if not 0 <= s['after_word'] < n:
                errors.append(f"{cid}: styles after_word {s['after_word']} is not a word number")
    return errors


def apply_task(task, output):
    stream = lib.get_stream(task['stream'])
    for a in output['clips']:
        clip = clip_by_id(stream, a['clip'])
        det = load_detect(stream, clip)
        old = lib.read_json(edl_path(stream, clip)) or {}
        answer = {k: v for k, v in a.items() if k != 'clip'}
        save(stream, clip, build(stream, clip, det, agent=answer, human=old.get('human')))


def plan_keys(keys):
    """`scout edit`: rules-only EDLs now for every clip, then agent tasks to refine them."""
    pairs = _resolve(keys)
    for stream, clip in pairs:
        edl = ensure(stream, clip, open_task=False)
        s = edl['stats']
        print(f"{stream.id}/{clip['id']}  {s['original']:.1f}s -> {s['edited']:.1f}s  {s['cuts']} cuts  "
              f"{clip.get('title', '')[:60]}")
    ids = open_tasks_for([f"{s.id}/{c['id']}" for s, c in pairs])
    if ids:
        print(f'{len(ids)} edit task(s) open for an agent: ' + ', '.join(ids))
