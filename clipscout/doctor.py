"""`scout doctor`: check this machine has what Clip Scout needs, and say how to fix what's missing."""
import shutil
import subprocess

from . import library as lib

OK, WARN, FAIL = 'ok', '--', 'NO'


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ''


def check_ffmpeg():
    rows = []
    if not shutil.which('ffmpeg'):
        return [(FAIL, 'ffmpeg not found on PATH (install it, e.g. `winget install Gyan.FFmpeg`)')]
    version = (_run(['ffmpeg', '-hide_banner', '-version']).split('\n') or [''])[0].replace('ffmpeg version ', '')
    encoders = _run(['ffmpeg', '-hide_banner', '-encoders'])
    nvenc = [e for e in ('h264_nvenc', 'hevc_nvenc', 'av1_nvenc') if e in encoders]
    rows.append((OK, f"ffmpeg {version.split(' ')[0]}"))
    rows.append((OK, f"GPU encoding: {', '.join(nvenc)}") if nvenc else
                (WARN, 'no NVENC encoders: edited clips will render on the CPU (slower)'))
    rows.append((OK, 'ffprobe') if shutil.which('ffprobe') else (FAIL, 'ffprobe not found on PATH'))
    return rows


def check_gpu():
    rows = []
    smi = _run(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'])
    if smi.strip():
        rows.append((OK, 'GPU: ' + smi.strip().splitlines()[0]))
    else:
        rows.append((WARN, 'no NVIDIA GPU found: transcription will run on the CPU (much slower)'))
    from .transcribe import cuda_devices
    n = cuda_devices()
    rows.append((OK, f'CUDA for transcription ({n} device{"s" if n != 1 else ""})') if n else
                (WARN, 'transcription can\'t use CUDA; check the NVIDIA driver'))
    if n:
        import ctypes
        missing = []
        for dll in ('cublas64_12.dll', 'cudnn64_9.dll'):
            try:
                ctypes.WinDLL(dll)
            except (OSError, AttributeError):
                missing.append(dll)
        if missing:
            rows.append((WARN, f"CUDA libraries not loadable: {', '.join(missing)} (run `uv sync`)"))
    return rows


def check_model():
    from .transcribe import MODEL_REPO, model_path
    path = model_path(download=False)
    return [(OK, f'Whisper model cached ({MODEL_REPO.split("/")[-1]})') if path else
            (WARN, f'Whisper model not cached yet; it downloads (~1.6 GB) on the first transcription')]


def check_torch():
    try:
        import torch
        cuda = torch.cuda.is_available()
        rows = [(OK, f"torch {torch.__version__} ({'CUDA' if cuda else 'CPU only'}) for the music check and editing")]
    except ImportError:
        return [(WARN, 'torch not installed: music check skipped, filler timing rougher (run `uv sync --all-extras`)')]
    from pathlib import Path
    import os
    hub = Path(os.environ.get('HF_HOME', Path.home() / '.cache' / 'huggingface')) / 'hub'
    for repo, use in (('MIT/ast-finetuned-audioset-10-10-0.4593', 'music check'),
                      ('facebook/wav2vec2-base-960h', 'filler timing')):
        cached = any((hub / f"models--{repo.replace('/', '--')}").glob('snapshots/*/*'))
        rows.append((OK, f'{use} model cached') if cached else
                    (WARN, f'{use} model downloads on first use ({repo})'))
    return rows


def check_agents():
    found = [a for a in ('claude', 'codex', 'gemini', 'opencode') if shutil.which(a)]
    missing = [a for a in ('claude', 'codex', 'gemini', 'opencode') if a not in found]
    if not found:
        return [(WARN, 'no agent CLI found (claude, codex, gemini, opencode): tasks can still be done by hand')]
    note = f" (not found: {', '.join(missing)})" if missing else ''
    return [(OK, f"agents: {', '.join(found)}{note}")]


def check_library():
    try:
        lib.LIBRARY.mkdir(parents=True, exist_ok=True)
        probe = lib.LIBRARY / '.write-test'
        probe.write_text('ok')
        probe.unlink()
    except OSError as e:
        return [(FAIL, f'library not writable: {lib.LIBRARY} ({e})')]
    free = shutil.disk_usage(lib.LIBRARY).free / 2**30
    status = OK if free > 50 else WARN
    return [(status, f'library {lib.LIBRARY} ({free:,.0f} GB free{"; a stream needs ~5-15 GB" if free <= 50 else ""})')]


def checks():
    rows = []
    for check in (check_ffmpeg, check_gpu, check_model, check_torch, check_agents, check_library):
        try:
            rows += check()
        except Exception as e:
            rows.append((WARN, f'{check.__name__[6:]} check failed: {e}'))
    return rows


def run():
    print('Clip Scout doctor')
    rows = checks()
    for status, text in rows:
        print(f'  {status:3} {text}')
    failed = [r for r in rows if r[0] == FAIL]
    print('Ready.' if not failed else f'{len(failed)} problem(s) to fix before Clip Scout can run.')
    return 1 if failed else 0
