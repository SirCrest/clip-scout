"""Word-timestamped transcription and the sentence view the picker reads.

faster-whisper large-v3-turbo on the GPU (CPU int8 when there is none), prompted with the Elgato glossary so
product names come out right. Works through the stream in 10-minute chunks and saves after each one, so an
interrupted run picks up where it stopped. Output shape (transcript.json):
  {"id", "title", "source", "model", "duration", "processed", "complete",
   "segments": [{"start", "end", "text", "words": [{"start", "end", "word", "p"}]}]}
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import elgato
from . import library as lib

MODEL_REPO = 'mobiuslabsgmbh/faster-whisper-large-v3-turbo'
CHUNK = 600
PAUSE = 1.2

_pipeline = None
_dll_handles = []


def _add_cuda_dlls():
    """Windows: make the CUDA libraries from the nvidia-* wheels loadable before ctranslate2 is imported."""
    if os.name != 'nt' or _dll_handles:
        return
    import importlib.util
    spec = importlib.util.find_spec('nvidia')
    if not spec or not spec.submodule_search_locations:
        return
    for base in spec.submodule_search_locations:
        for lib_name in ('cublas', 'cudnn', 'cuda_runtime', 'cuda_nvrtc'):
            bin_dir = Path(base) / lib_name / 'bin'
            if bin_dir.is_dir():
                _dll_handles.append(os.add_dll_directory(str(bin_dir)))
                os.environ['PATH'] = str(bin_dir) + os.pathsep + os.environ.get('PATH', '')


def cuda_devices():
    _add_cuda_dlls()
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def device():
    """(device, compute_type): CUDA float16 when a GPU is usable, else CPU int8 (much slower)."""
    if cuda_devices() > 0:
        return 'cuda', 'float16'
    print('warning: no CUDA GPU found; transcribing on the CPU, which is much slower', file=sys.stderr)
    return 'cpu', 'int8'


MODEL_FILES = ['config.json', 'preprocessor_config.json', 'model.bin', 'tokenizer.json', 'vocabulary.*']


def model_path(download=True):
    from huggingface_hub import snapshot_download
    try:
        return snapshot_download(MODEL_REPO, allow_patterns=MODEL_FILES, local_files_only=True)
    except Exception:
        if not download:
            return None
        return snapshot_download(MODEL_REPO, allow_patterns=MODEL_FILES)


def model():
    """The process-wide BatchedInferencePipeline (loaded once)."""
    global _pipeline
    if _pipeline is None:
        _add_cuda_dlls()
        from faster_whisper import BatchedInferencePipeline, WhisperModel
        dev, compute = device()
        _pipeline = BatchedInferencePipeline(model=WhisperModel(model_path(), device=dev, compute_type=compute))
        _pipeline.clip_scout_device = dev
    return _pipeline


def probe_duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def extract_audio(src, start, length, wav):
    """16 kHz mono WAV of [start, start+length) of src."""
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{start:.3f}', '-i', str(src), '-t', f'{length:.3f}',
                    '-vn', '-ac', '1', '-ar', '16000', str(wav)], check=True)


def transcribe_file(wav, offset=0.0, prompt=None, batch_size=None):
    """Segments of one audio file, times shifted by offset, in transcript.json's segment shape."""
    pipe = model()
    if batch_size is None:
        batch_size = 24 if getattr(pipe, 'clip_scout_device', 'cuda') == 'cuda' else 8
    segments, _ = pipe.transcribe(str(wav), language='en', beam_size=5, batch_size=batch_size,
                                  word_timestamps=True, vad_filter=True, condition_on_previous_text=False,
                                  initial_prompt=prompt if prompt is not None else elgato.glossary())
    out = []
    for s in segments:
        out.append({
            'start': round(offset + s.start, 3), 'end': round(offset + s.end, 3), 'text': s.text.strip(),
            'words': [{'start': round(offset + w.start, 3), 'end': round(offset + w.end, 3), 'word': w.word,
                       'p': round(w.probability, 3)} for w in (s.words or [])]})
    return out


def run(stream, progress=lambda fraction, note='': None):
    """The 'transcribe' stage."""
    data = stream.load('transcript.json') or {
        'id': stream.id, 'title': stream.title, 'source': stream.meta.get('media'), 'model': MODEL_REPO,
        'segments': [], 'processed': 0}
    if not data.get('complete'):
        src = stream.media
        if not src or not src.exists():
            raise FileNotFoundError(f'{stream.id}: no media to transcribe')
        duration = stream.meta.get('duration') or probe_duration(src)
        if duration <= 0:
            raise ValueError(f'{stream.id}: could not read the duration of {src.name}')
        with tempfile.TemporaryDirectory(prefix='scout-asr-') as tmp:
            wav = Path(tmp) / 'chunk.wav'
            start = float(data.get('processed', 0))
            while duration - start >= 0.1:
                progress(start / duration, f'{lib.hms(start)} of {lib.hms(duration)}')
                length = min(CHUNK, duration - start)
                extract_audio(src, start, length, wav)
                data['segments'] += transcribe_file(wav, offset=start)
                start += length
                data.update(processed=round(start, 3), duration=duration,
                            complete=duration - start < 0.1)
                stream.save('transcript.json', data)
        data['complete'] = True
        stream.save('transcript.json', data)
    progress(1.0, 'sentences')
    write_sentences(stream)


def sentences(words):
    """Yield (words of one sentence, gap after it). A sentence ends at . ? ! or a pause over PAUSE seconds."""
    cur = []
    for i, w in enumerate(words):
        if cur and w['start'] - cur[-1]['end'] > PAUSE:
            yield cur, w['start'] - cur[-1]['end']
            cur = []
        cur.append(w)
        if w['word'].rstrip().endswith(('.', '?', '!')):
            yield cur, (words[i + 1]['start'] - w['end'] if i + 1 < len(words) else 0)
            cur = []
    if cur:
        yield cur, 0


def corrections_by_time(stream):
    fixes = {}
    for f in stream.load('corrections.json', []) or []:
        fixes.setdefault(round(f['t'], 2), []).append(f)
    return fixes


def render_sentences(stream_id, title, duration, words, fixes):
    lines = [f'# {stream_id}  {title}', f'# duration {lib.hms(duration or 0)}', '']
    for sent, gap in sentences(words):
        t = round(sent[0]['start'], 2)
        text = ''.join(w['word'] for w in sent).strip()
        for f in fixes.get(t, []):
            text = text.replace(f['from'], f['to'])
        lines.append(f'[{lib.hms(t)}  {t:.2f}]  {text}')
        if gap > PAUSE:
            lines.append(f'   ~ pause {gap:.1f}s')
    return '\n'.join(lines) + '\n'


def write_sentences(stream):
    """(Re)write sentences.txt, applying corrections.json when present."""
    data = stream.load('transcript.json', {})
    text = render_sentences(stream.id, stream.title, data.get('duration') or stream.meta.get('duration'),
                            stream.words(), corrections_by_time(stream))
    stream.path('sentences.txt').write_text(text, encoding='utf-8')
    return stream.path('sentences.txt')
