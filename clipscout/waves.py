"""Audio waveforms for the app: loudness of a stretch of a stream, for drawing.

A clip's waveform is decoded on demand (seconds of audio). The whole-stream overview is built during transcription
from the audio chunks it already decodes (wave.json: RMS every STEP seconds, growing as transcription runs), or,
for a stream transcribed before this existed, once in the background on first request.
"""
import subprocess
import threading
import wave as wavfile

import numpy as np

from . import library as lib

RATE = 8000
STEP = 2.0
_building = set()
_lock = threading.Lock()


def _pcm(path, start, length, rate):
    cmd = ['ffmpeg', '-v', 'error', '-nostdin']
    if start:
        cmd += ['-ss', f'{start:.3f}']
    cmd += ['-i', str(path)]
    if length:
        cmd += ['-t', f'{length:.3f}']
    cmd += ['-map', '0:a:0', '-vn', '-ac', '1', '-ar', str(rate), '-f', 's16le', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def _rms(x, buckets):
    if not len(x) or buckets <= 0:
        return [0.0] * max(buckets, 0)
    edges = np.linspace(0, len(x), buckets + 1).astype(int)
    return [float(np.sqrt(np.mean(x[a:b] ** 2))) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])]


def _scale(values):
    top = max(max(values, default=0), 1e-4)
    return [round(min(1.0, v / top), 3) for v in values]


def clip(stream, start, end, n=600):
    n = max(16, min(int(n), 4000))
    return {'start': start, 'end': end, 'peaks': _scale(_rms(_pcm(stream.media, start, end - start, RATE), n))}


def add_chunk(stream, wav_path, start):
    """Append one transcription chunk's loudness to wave.json (called by the transcribe stage)."""
    with wavfile.open(str(wav_path), 'rb') as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        seconds = w.getnframes() / w.getframerate()
    data = stream.load('wave.json') or {'step': STEP, 'rms': []}
    first = int(round(start / STEP))
    data['rms'] = data['rms'][:first] + [round(v, 5) for v in _rms(x, int(round(seconds / STEP)))]
    stream.save('wave.json', data)


def _build(stream):
    try:
        duration = stream.meta.get('duration') or 0
        x = _pcm(stream.media, 0, None, 400)
        stream.save('wave.json', {'step': STEP, 'rms': [round(v, 5) for v in _rms(x, int(duration / STEP))],
                                  'complete': True})
    finally:
        with _lock:
            _building.discard(stream.id)


def overview(stream):
    """The stream's loudness, or {'pending': True} while it's being built in the background."""
    data = stream.load('wave.json')
    if data and 'rms' not in data:
        data = None
    transcribing = stream.stage('transcribe')['state'] in ('running', 'pending')
    if data and (data.get('complete') or transcribing or stream.stage('transcribe')['state'] == 'done'
                 and len(data['rms']) * STEP >= (stream.meta.get('duration') or 0) - 2 * STEP):
        return {'step': data['step'], 'peaks': _scale(data['rms']), 'duration': stream.meta.get('duration')}
    if transcribing:
        return {'step': STEP, 'peaks': [], 'duration': stream.meta.get('duration')}
    with _lock:
        if stream.id not in _building:
            _building.add(stream.id)
            threading.Thread(target=_build, args=(stream,), daemon=True).start()
    return {'pending': True}
