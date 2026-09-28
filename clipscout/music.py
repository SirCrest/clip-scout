"""The 'music' stage: measure audible music in each clip (copyright-claim risk on YouTube).

An AudioSet classifier (AST) scores 10 s windows of the clip's source range; a clip's `share` is the fraction of
windows where a music-type class (Music, Singing, instrument families, Video game music...) exceeds 0.25, and
`peak` the highest such score. Writes music.json {clip id: {share, peak}} and sets the `music` / `music-faint`
flags on clips.json (plan.music_flags). Needs the optional `music` extra (torch + transformers).
"""
import subprocess

import numpy as np

from .plan import music_flags

MODEL = 'MIT/ast-finetuned-audioset-10-10-0.4593'
MUSIC_WORDS = ('music', 'singing', 'song', 'guitar', 'piano', 'drum', 'synthesizer', 'saxophone', 'orchestra',
               'hip hop', 'rock', 'pop', 'electronic', 'techno', 'jazz', 'choir', 'rapping', 'bass', 'ukulele')
SR, WIN, THRESH, BATCH = 16000, 10, 0.25, 16
_model = None


def _load():
    global _model
    if _model is None:
        import torch
        from transformers import ASTFeatureExtractor, ASTForAudioClassification
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        model = ASTForAudioClassification.from_pretrained(MODEL).to(device).eval()
        if device == 'cuda':
            model = model.half()
        labels = model.config.id2label
        ids = [i for i, label in labels.items()
               if any(w in label.lower() for w in MUSIC_WORDS) and 'speech' not in label.lower()]
        _model = (ASTFeatureExtractor.from_pretrained(MODEL), model, ids, device)
    return _model


def audio(src, start, duration):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{start:.3f}', '-i', str(src), '-t', f'{duration:.3f}',
                          '-vn', '-ac', '1', '-ar', str(SR), '-f', 's16le', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def score(x):
    import torch
    extractor, model, ids, device = _load()
    wins = [x[i:i + SR * WIN] for i in range(0, max(len(x) - SR * 2, 1), SR * WIN)]
    peaks = []
    with torch.no_grad():
        for b in range(0, len(wins), BATCH):
            feats = extractor(wins[b:b + BATCH], sampling_rate=SR, return_tensors='pt')['input_values'].to(device)
            if device == 'cuda':
                feats = feats.half()
            probs = torch.sigmoid(model(feats).logits.float())[:, ids].max(dim=1).values
            peaks += probs.cpu().tolist()
    if not peaks:
        return {'share': 0.0, 'peak': 0.0}
    return {'share': round(sum(p > THRESH for p in peaks) / len(peaks), 3), 'peak': round(max(peaks), 3)}


def run(stream, progress=lambda f, note='': None):
    clips = stream.clips()
    done = stream.load('music.json', {})
    todo = [c for c in clips if c['id'] not in done]
    if todo:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return ('skipped', 'install the music extra: uv sync --extra music')
    for n, c in enumerate(todo, 1):
        start = min(c.get('key_in', c['hook_at']), c['hook_at'])
        done[c['id']] = score(audio(stream.media, start, c['source_out'] - start))
        if n % 10 == 0 or n == len(todo):
            stream.save('music.json', done)
            progress(n / len(todo), f'{n}/{len(todo)} clips')
    for c in clips:
        if c['id'] in done:
            music_flags(c, done[c['id']])
    stream.save('clips.json', clips)
