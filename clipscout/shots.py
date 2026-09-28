"""Shot boundaries inside a time range: where the picture changes at once (camera switch, scene change, screen
share appearing), so edits can hard-cut there instead of punching in.

Decodes on the GPU when it can (NVDEC), scales to 64x36 grey, samples 20 frames a second, and marks frames whose
difference from the previous frame is a spike well above the local level.
"""
import subprocess
from functools import lru_cache

import numpy as np

W, H, FPS = 64, 36, 20


@lru_cache
def _cuda_ok():
    probe = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda',
                            '-f', 'lavfi', '-i', 'color=black:s=64x64:d=0.1', '-f', 'null', '-'],
                           capture_output=True)
    return probe.returncode == 0


def _frames(src, start, duration):
    base = ['ffmpeg', '-hide_banner', '-v', 'error']
    tail = ['-an', '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    if _cuda_ok():  # skipping non-reference frames halves decoding; 20 samples/s is plenty for cut detection
        cmd = base + ['-skip_frame', 'noref', '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda',
                      '-ss', f'{start:.3f}', '-t', f'{duration:.3f}',
                      '-i', str(src), '-vf', f'scale_cuda={W}:{H},hwdownload,format=nv12,format=gray,fps={FPS}'] + tail
        out = subprocess.run(cmd, capture_output=True)
        if out.returncode == 0 and out.stdout:
            return np.frombuffer(out.stdout, np.uint8).reshape(-1, H, W)
    cmd = base + ['-ss', f'{start:.3f}', '-t', f'{duration:.3f}', '-i', str(src),
                  '-vf', f'fps={FPS},scale={W}:{H}:flags=area,format=gray'] + tail
    out = subprocess.run(cmd, capture_output=True, check=True)
    return np.frombuffer(out.stdout, np.uint8).reshape(-1, H, W)


def detect(src, start, end, min_gap=0.8):
    """Source times of shot boundaries in [start, end], and a per-second 'motion' level (for reference)."""
    frames = _frames(src, start, end - start).astype(np.float32)
    if len(frames) < 3:
        return []
    diff = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))  # diff[i]: frame i -> i+1
    hist = np.stack([np.histogram(f, bins=16, range=(0, 256))[0] for f in frames]).astype(np.float32) / (W * H)
    hdiff = np.abs(np.diff(hist, axis=0)).sum(axis=1)  # 0..2
    cuts, last = [], -1e9
    for i in range(len(diff)):
        lo, hi = max(0, i - 20), min(len(diff), i + 21)
        local = np.median(np.r_[diff[lo:i], diff[i + 1:hi]]) if hi - lo > 1 else 0
        spike = diff[i] > max(12.0, 4 * local + 4) and hdiff[i] > 0.25
        t = start + (i + 1) / FPS
        if spike and t - last >= min_gap:
            cuts.append(round(t, 2))
            last = t
    return cuts
