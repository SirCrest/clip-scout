"""Source videos that open fast.

Some downloads (yt-dlp's Twitch VODs since early 2026) are fragmented MP4: tens of thousands of small fragments and
no index up front, so every tool that opens the file (ffprobe, each thumbnail, the music check, the editor, the
browser's player) first walks all of them. That costs a minute or more per open on a multi-hour stream. A lossless
remux with the index at the front (`-c copy -movflags +faststart`) fixes it for good. The new file is checked
against the old one before it replaces it: content length, audio/video offset, and at three points the decoded
audio must line up with zero lag and sound the same.
"""
import os
import struct
import subprocess
from pathlib import Path


def is_fragmented(path):
    """True when the MP4's media sits in moof fragments (the top-level boxes are read, nothing is decoded)."""
    path = Path(path)
    try:
        total = path.stat().st_size
        with open(path, 'rb') as f:
            pos = 0
            for _ in range(12):
                f.seek(pos)
                h = f.read(16)
                if len(h) < 8:
                    return False
                size, typ = struct.unpack('>I4s', h[:8])
                if size == 1:
                    size = struct.unpack('>Q', h[8:16])[0]
                if typ == b'moof':
                    return True
                if typ == b'mdat':
                    return False
                pos += size or total
    except OSError:
        return False
    return False


def _duration(path):
    """Content length in seconds: end minus start. Twitch's fragmented files often start at a timestamp like 62 s
    and report the end timestamp as their duration; every Clip Scout time counts from the first frame instead."""
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration,start_time', '-of', 'json',
                          str(path)], capture_output=True, text=True).stdout
    import json
    fmt = (json.loads(out or '{}').get('format') or {})
    duration = float(fmt.get('duration') or 0)
    start = float(fmt.get('start_time') or 0)
    return max(0.0, duration - start)


def _pcm(path, at, length=4.0):
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-ss', f'{at:.3f}', '-i', str(path), '-t', f'{length}',
                          '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-f', 's16le', '-'], capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32)


def same_sound(a, b, max_lag=800):
    """(aligned, difference): the two decodes line up with zero lag and differ by less than a few percent. Seeking
    into a remuxed file can land the decoder a fraction of a millisecond differently in the first packet, so the
    samples aren't bit-identical, but a shifted timeline would show up as a lag."""
    import numpy as np
    n = min(len(a), len(b))
    if n < 4 * max_lag or not np.any(a[:n]):
        return False, 1.0
    a, b = a[:n], b[:n]
    core = b[max_lag:n - max_lag]
    corr = np.correlate(a, core, 'valid')
    lag = int(np.argmax(corr)) - max_lag
    diff = float(np.sqrt(np.mean((a - b) ** 2)) / (np.sqrt(np.mean(a ** 2)) + 1e-9))
    return abs(lag) <= 1, diff


def _start_offset(path):
    """Video start minus audio start, in seconds."""
    import json
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,start_time', '-of', 'json',
                          str(path)], capture_output=True, text=True).stdout
    starts = {s['codec_type']: float(s.get('start_time') or 0) for s in json.loads(out or '{}').get('streams', [])}
    return starts.get('video', 0.0) - starts.get('audio', 0.0)


def defragment(path, progress=lambda fraction, note='': None):
    """Remux a fragmented MP4 in place, losslessly. Returns a summary; raises if the result doesn't match."""
    path = Path(path)
    tmp = path.with_name(path.stem + '.remux.mp4')
    progress(0.05, 'reading the fragmented video')
    before = _duration(path)
    progress(0.3, 'writing the index to the front')
    r = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(path), '-map', '0', '-map', '-0:d?',
                        '-c', 'copy', '-movflags', '+faststart', str(tmp)], capture_output=True, text=True)
    if r.returncode or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f'remux failed: {r.stderr.strip()[-300:]}')
    progress(0.75, 'checking the new file')
    after = _duration(tmp)
    if abs(after - before) > 0.25:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f'remux changed the duration ({before:.2f} s -> {after:.2f} s); kept the original')
    if abs(_start_offset(path) - _start_offset(tmp)) > 0.005:
        tmp.unlink(missing_ok=True)
        raise RuntimeError('remux changed the audio/video offset; kept the original')
    for at in (min(60.0, before * 0.2), before / 2, max(0.0, before - 120) if before > 240 else before * 0.8):
        aligned, diff = same_sound(_pcm(path, at), _pcm(tmp, at))
        if not aligned or diff > 0.05:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f'remuxed audio differs at {at:.0f} s (aligned {aligned}, difference {diff:.1%}); '
                               'kept the original')
    os.replace(tmp, path)
    progress(1.0, 'done')
    return {'duration': round(after, 3), 'size': path.stat().st_size}


def fix_stream(stream, progress=lambda fraction, note='': None):
    """Defragment a stream's source when needed; cached keyframe times are dropped so they're read again."""
    if not stream.media or not is_fragmented(stream.media):
        return None
    result = defragment(stream.media, progress)
    stream.path('keyframes.json').unlink(missing_ok=True)
    stream.update(lambda meta: meta.update(duration=result['duration']))
    return result
