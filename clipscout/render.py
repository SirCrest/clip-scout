"""Render a clip to a video file, following its edit decision list (edit.py), or losslessly without edits.

Edited renders read the source stream directly, in one ffmpeg run per pass:
  video  keeps the frames of each kept piece (their edges sit on the frame grid), renumbers them, and overlays a
         zoomed copy over the punched-in stretches; H.264 on NVENC (VideoToolbox on a Mac, else libx264)
  audio  trims each kept piece with a 6 ms fade in and out so joins don't click, joins them, and normalises the
         loudness to -14 LUFS / -1 dBTP in two passes (measure, then apply linearly)
  srt    beside the video: word times moved through the edit, transcript corrections and name fixes applied
Lossless renders stream-copy from the keyframe at or before the hook (the year set's cut: fast, exact quality,
but it starts with a word or two of pre-roll and has no edits). Previews are 720p with fast settings, one-pass
loudness, for the app's Edit view.
"""
import json
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from . import library as lib

FADE = 0.006
LOUDNESS = 'I=-14:TP=-1.5:LRA=11'  # -1.5 so the true peak stays under -1 dBTP after AAC encoding
CAPTION_CHARS, LINE_CHARS = 84, 42


@lru_cache
def encoders():
    out = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True).stdout
    return {name for name in ('h264_nvenc', 'h264_videotoolbox', 'libx264') if f' {name} ' in out}


@lru_cache
def nvenc_works():
    if 'h264_nvenc' not in encoders():
        return False
    r = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-f', 'lavfi', '-i', 'color=black:s=256x256:d=0.1',
                        '-c:v', 'h264_nvenc', '-f', 'null', '-'], capture_output=True)
    return r.returncode == 0


def video_codec(fps, preview):
    gop = str(int(round(fps * 2)))
    if nvenc_works():
        if preview:
            return ['-c:v', 'h264_nvenc', '-preset', 'p2', '-rc', 'vbr', '-cq', '28', '-b:v', '0', '-g', gop]
        return ['-c:v', 'h264_nvenc', '-preset', 'p7', '-tune', 'hq', '-rc', 'vbr', '-cq', '18', '-b:v', '0',
                '-profile:v', 'high', '-spatial-aq', '1', '-temporal-aq', '1', '-rc-lookahead', '32', '-bf', '3',
                '-g', gop]
    if 'h264_videotoolbox' in encoders():
        return ['-c:v', 'h264_videotoolbox', '-q:v', '45' if preview else '70', '-profile:v', 'high', '-g', gop]
    return ['-c:v', 'libx264', '-preset', 'veryfast' if preview else 'slow', '-crf', '26' if preview else '17',
            '-profile:v', 'high', '-g', gop]


def _fps_expr(fps):
    return {23.976: '24000/1001', 29.97: '30000/1001', 59.94: '60000/1001'}.get(fps, f'{fps:g}')


def _pieces(segments):
    """Contiguous runs of segments (a zoom that ends at a shot change splits a segment without a cut)."""
    runs = []
    for s in segments:
        if runs and abs(runs[-1][1] - s['src_in']) < 1e-6:
            runs[-1][1] = s['src_out']
        else:
            runs.append([s['src_in'], s['src_out']])
    return runs


def audio_graph(segments, S):
    runs = _pieces(segments)
    lines = [f"[0:a]asplit={len(runs)}" + ''.join(f'[a{k}]' for k in range(len(runs)))] if len(runs) > 1 else []
    for k, (a, b) in enumerate(runs):
        src = f'[a{k}]' if len(runs) > 1 else '[0:a]'
        length = b - a
        lines.append(f'{src}atrim=start={a - S:.4f}:end={b - S:.4f},asetpts=PTS-STARTPTS,'
                     f'afade=t=in:st=0:d={FADE},afade=t=out:st={max(length - FADE, 0):.4f}:d={FADE}[p{k}]')
    lines.append(''.join(f'[p{k}]' for k in range(len(runs))) + f'concat=n={len(runs)}:v=0:a=1[acat]')
    return lines


def video_graph(segments, S, facts, preview):
    fps = facts['fps']
    eps = 0.5 / fps
    keep = '+'.join(f"between(t,{s['src_in'] - S - eps:.4f},{s['src_out'] - S - eps:.4f})" for s in segments)
    w, h = facts['width'], facts['height']
    small = ''
    if preview:
        w, h = int(round(w * 720 / h / 2)) * 2, 720
        small = f',scale={w}:{h}:flags=bicubic'
    lines = [f"[0:v]select='{keep}',setpts=N/({_fps_expr(fps)})/TB{small}[vs]"]
    zooms = {s['zoom'] for s in segments if s['zoom'] != 1.0}
    last = 'vs'
    if zooms:
        z = max(zooms)
        t, spans = 0.0, []
        for s in segments:
            length = s['src_out'] - s['src_in']
            if s['zoom'] != 1.0:
                spans.append((t, t + length))
            t += length
        enable = '+'.join(f'between(t,{a - eps:.4f},{b - eps:.4f})' for a, b in spans)
        lines += [f'[vs]split[vb][vz]',
                  f'[vz]crop=iw/{z}:ih/{z}:(iw-iw/{z})/2:(ih-ih/{z})*0.42,scale={w}:{h}:flags=lanczos,setsar=1[vzz]',
                  f"[vb][vzz]overlay=0:0:enable='{enable}'[vo]"]
        last = 'vo'
    lines.append(f'[{last}]setsar=1[v]')
    return lines


def _run(cmd, total, progress, lo, hi):
    """Run ffmpeg with -progress, reporting lo..hi of the whole job. Returns stderr text."""
    proc = subprocess.Popen(cmd + ['-progress', 'pipe:1', '-nostats'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding='utf-8', errors='replace')
    err = []
    import threading
    reader = threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True)
    reader.start()
    for line in proc.stdout:
        if progress and line.startswith('out_time_us=') and total > 0:
            try:
                done = int(line.split('=')[1]) / 1e6
            except ValueError:
                continue
            progress(lo + (hi - lo) * min(done / total, 1.0))
    proc.wait()
    reader.join()
    text = ''.join(err)
    if proc.returncode:
        raise RuntimeError(f'ffmpeg failed ({proc.returncode}): {text[-1500:]}')
    return text


def _input(src, S, T):
    # CPU decoding: on the 4090 machine NVDEC with full-size frames copied back for the filters ran 16x slower
    # than the CPU decoder (74 s vs 4.6 s for 30 s of 1440p60 HEVC).
    return ['-ss', f'{S:.4f}', '-t', f'{T:.4f}', '-i', str(src)]


def measure_loudness(src, segments, S, T, progress=None):
    with tempfile.TemporaryDirectory(prefix='scout-render-') as tmp:
        script = Path(tmp) / 'audio.txt'
        script.write_text(';\n'.join(audio_graph(segments, S) + [f'[acat]loudnorm={LOUDNESS}:print_format=json[aout]']),
                          encoding='utf-8')
        err = _run(['ffmpeg', '-hide_banner', '-y', '-vn', '-ss', f'{S:.4f}', '-t', f'{T:.4f}', '-i', str(src),
                    '-/filter_complex', str(script), '-map', '[aout]', '-f', 'null', '-'],
                   sum(s['src_out'] - s['src_in'] for s in segments), progress, 0.0, 0.12)
    m = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', err, re.S)
    return json.loads(m[-1]) if m else None


def render_edl(src, edl, facts, out_path, preview=False, progress=None):
    segments = edl['segments']
    if not segments:
        raise ValueError(f"clip {edl['clip']}: the edit keeps nothing")
    fps = facts['fps']
    S = max(0.0, round(round((segments[0]['src_in'] - 1.0) * fps) / fps, 4))
    T = segments[-1]['src_out'] - S + 0.5
    total = sum(s['src_out'] - s['src_in'] for s in segments)
    if preview:
        loud = f'[acat]loudnorm={LOUDNESS},aresample=48000[aout]'
        lo = 0.0
    else:
        m = measure_loudness(src, segments, S, T, progress)
        lo = 0.12
        if m and m.get('input_i') not in (None, '-inf'):
            loud = (f"[acat]loudnorm={LOUDNESS}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                    f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
                    f"linear=true,aresample=48000[aout]")
        else:  # silent clip: nothing to normalise
            loud = '[acat]aresample=48000[aout]'
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    part = out_path.with_name(out_path.stem + '.part' + out_path.suffix)
    with tempfile.TemporaryDirectory(prefix='scout-render-') as tmp:
        script = Path(tmp) / 'graph.txt'
        script.write_text(';\n'.join(video_graph(segments, S, facts, preview) + audio_graph(segments, S) + [loud]),
                          encoding='utf-8')
        cmd = (['ffmpeg', '-hide_banner', '-y'] + _input(src, S, T) +
               ['-/filter_complex', str(script), '-map', '[v]', '-map', '[aout]', '-fps_mode', 'cfr',
                '-r', _fps_expr(fps), '-pix_fmt', 'yuv420p'] + video_codec(fps, preview) +
               ['-c:a', 'aac', '-b:a', '128k' if preview else '192k', '-ar', '48000', '-movflags', '+faststart',
                str(part)])
        _run(cmd, total, progress, lo, 1.0)
    part.replace(out_path)
    return out_path


def render_lossless(src, clip, out_path):
    k, out_t = clip.get('key_in', clip['hook_at']), clip['source_out']
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    part = out_path.with_name(out_path.stem + '.part' + out_path.suffix)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{k + 0.001:.3f}', '-i', str(src), '-t', f'{out_t - k:.3f}',
                    '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy', '-avoid_negative_ts', 'make_zero',
                    '-movflags', '+faststart', str(part)], check=True)
    part.replace(out_path)
    return out_path


# ---------------------------------------------------------------- captions

def srt_time(t):
    ms = int(round(max(t, 0) * 1000))
    return f'{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}'


def remap(words, segments):
    """Words kept by the edit, with times on the edited timeline: [(start, end, text, ends_sentence)]."""
    out, offset = [], 0.0
    for s in segments:
        a, b = s['src_in'], s['src_out']
        for w in words:
            mid = (w['start'] + w['end']) / 2
            if a <= mid < b:
                out.append((offset + max(w['start'], a) - a, offset + min(w['end'], b) - a, w['w'],
                            w['w'].rstrip().endswith(('.', '?', '!'))))
        offset += b - a
    return out


def cues(mapped):
    """Group words into caption cues of up to two 42-character lines, breaking at sentence ends and pauses."""
    out, cur = [], []
    for item in mapped:
        text = ' '.join(x[2] for x in cur + [item])
        if cur and (len(text) > CAPTION_CHARS or item[0] - cur[-1][1] > 1.0 or item[1] - cur[0][0] > 7):
            out.append(cur)
            cur = []
        cur.append(item)
        if item[3]:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _two_lines(text):
    if len(text) <= LINE_CHARS:
        return text
    words = text.split()
    cut = min(range(1, len(words)), key=lambda m: abs(len(' '.join(words[:m])) - len(text) / 2))
    return ' '.join(words[:cut]) + '\n' + ' '.join(words[cut:])


def _join(tokens):
    """Words back into text: Whisper splits some words ("broadcast" "-ready", "2" ".0"); glue those back on."""
    text = ''
    for t in tokens:
        text += t if text and re.match(r"^[-.'’][\w]", t) else (' ' + t if text else t)
    return text


def captions(words, segments, fixes=()):
    from . import edit, elgato
    kept = _fix_pairs([w for w in words if not edit.is_filler(w['w'])], elgato.fix_names)
    groups = cues(remap(kept, segments))
    lines = []
    for n, group in enumerate(groups):
        text = _join([x[2] for x in group]).strip()
        after_sentence = n == 0 or groups[n - 1][-1][3]
        if after_sentence and text[:1].islower():  # a cut can leave a sentence starting mid-way
            text = text[0].upper() + text[1:]
        for f in fixes:
            text = text.replace(f['from'], f['to'])
        text = elgato.fix_names(text)
        start, end = group[0][0], group[-1][1]
        nxt = groups[n + 1][0][0] if n + 1 < len(groups) else end + 1
        end = min(max(end + 0.2, start + 0.8), nxt - 0.02) if nxt > start + 0.3 else max(end, start + 0.3)
        lines.append(f'{n + 1}\n{srt_time(start)} --> {srt_time(end)}\n{_two_lines(text)}\n')
    return '\n'.join(lines)


def _fix_pairs(words, fix):
    """Name fixes that span two words ("Mark II" -> "MK.2", "Wave 3" -> "Wave:3") could fall on either side of a
    caption break, so apply them to neighbouring word pairs first, merging a pair that becomes one token."""
    out, i = [], 0
    while i < len(words):
        if i + 1 < len(words):
            pair = f"{words[i]['w']} {words[i + 1]['w']}"
            fixed = fix(pair)
            if fixed != pair and ' ' not in fixed.strip():
                out.append({**words[i], 'w': fixed.strip(), 'end': words[i + 1]['end']})
                i += 2
                continue
        out.append(words[i])
        i += 1
    return out


def _fixes(stream, a, b):
    return [f for f in stream.load('corrections.json', []) or [] if a - 5 <= f['t'] <= b + 5]


# ---------------------------------------------------------------- the app's and CLI's calls

def render_clip(stream, clip, out_path, lossless=False, preview=False, progress=None):
    """Render one clip to out_path (+ .srt beside it). progress(fraction) is called as it goes."""
    from . import edit
    src = stream.media
    out_path = Path(out_path)
    if lossless:
        render_lossless(src, clip, out_path)
        det = edit.load_detect(stream, clip)
        words = det['words'] if det else [{'start': w['start'], 'end': w['end'], 'w': w['word'].strip()}
                                          for w in stream.words()]
        segs = [{'src_in': clip.get('key_in', clip['hook_at']), 'src_out': clip['source_out'], 'zoom': 1.0}]
    else:
        edl = edit.ensure(stream, clip)
        det = edit.load_detect(stream, clip)
        render_edl(src, edl, det['video'], out_path, preview=preview, progress=progress)
        words, segs = det['words'], edl['segments']
    if not preview:
        out_path.with_suffix('.srt').write_text(
            captions(words, segs, _fixes(stream, segs[0]['src_in'], segs[-1]['src_out'])), encoding='utf-8')
    if progress:
        progress(1.0)
    return out_path


def render_keys(keys, lossless=False):
    """`scout render`: files go to library/renders/<stream id>/<clip id>.mp4."""
    from . import edit
    for stream, clip in edit._resolve(keys):
        out = lib.LIBRARY / 'renders' / stream.id / f"{clip['id']}.mp4"
        import time
        t = time.time()
        render_clip(stream, clip, out, lossless=lossless)
        print(f"{stream.id}/{clip['id']}  {time.time() - t:.1f}s  {out}")
