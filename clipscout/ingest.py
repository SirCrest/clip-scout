"""Bring a stream into the library: a local video file, or any URL yt-dlp understands (Twitch VODs, YouTube...).

`add` registers the stream right away (metadata only for URLs; files are hard-linked or moved into place when
that's instant). The 'fetch' stage then downloads URLs, copies files that couldn't be linked, and records the
duration.
"""
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from . import library as lib
from .transcribe import probe_duration

URL = re.compile(r'^https?://', re.I)
TWITCH = re.compile(r'twitch\.tv/(?:[^/?#]+/)?videos?/(\d+)', re.I)
YOUTUBE = re.compile(r'(?:youtube\.com/(?:watch\?(?:[^#]*&)?v=|live/|shorts/|embed/)|youtu\.be/)([\w-]{11})', re.I)
DATED = re.compile(r'^(\d{4}-\d{2}-\d{2})[\s_-]*(.*)$')
# H.264/AAC in MP4 first so any browser can play the source; anything else is merged into MP4.
FORMAT = 'bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[vcodec^=avc1]/bv*+ba/b'
COPY_BLOCK = 16 * 1024 * 1024


def classify(url):
    """('twitch', vod id) | ('youtube', video id) | ('url', None)."""
    if m := TWITCH.search(url):
        return 'twitch', m.group(1)
    if m := YOUTUBE.search(url):
        return 'youtube', m.group(1)
    return 'url', None


def clean_title(title):
    """Drop Twitch-style '| !giveaway !takeover' tails and trailing '[id]' tags."""
    title = re.sub(r'\s*[|｜].*$', '', title or '')
    title = re.sub(r'\s*\[v?\d{6,}\]\s*$', '', title)
    return title.strip()


def _existing(sid):
    try:
        return lib.get_stream(sid)
    except KeyError:
        return None


def add(source, title=None, date=None, mode=None):
    """Register a stream from a file path or URL and return it (an existing stream is returned unchanged)."""
    if URL.match(str(source)):
        return _add_url(str(source), title, date)
    return _add_file(Path(source), title, date, mode)


def _info(url):
    import yt_dlp
    opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'noplaylist': True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get('_type') in ('playlist', 'multi_video'):
        raise ValueError('That link is a playlist or channel; add one stream at a time.')
    return info


def _info_date(info):
    if info.get('timestamp'):
        return datetime.fromtimestamp(info['timestamp']).date().isoformat()
    d = info.get('upload_date') or info.get('release_date')
    if d and len(d) == 8:
        return f'{d[:4]}-{d[4:6]}-{d[6:]}'
    return datetime.now().date().isoformat()


def _add_url(url, title, date):
    kind, ref = classify(url)
    if ref and (s := _existing(lib.stream_id(kind, ref))):
        return s
    info = _info(url)
    if kind == 'url':
        sid = lib.stream_id('url', f"{info.get('extractor_key', '')}:{info.get('id', url)}")
        if s := _existing(sid):
            return s
    else:
        sid = lib.stream_id(kind, ref)
    source = {'kind': kind, 'url': info.get('webpage_url') or url, 'id': info.get('id')}
    return lib.create_stream(sid, title or clean_title(info.get('title')) or sid, date or _info_date(info), source,
                             media=None, duration=info.get('duration'))


def _same_volume(a, b):
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _add_file(path, title, date, mode):
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f'no such file: {path}')
    size = path.stat().st_size
    twitch = re.search(r'\[v?(\d{9,11})\]', path.stem)  # yt-dlp names: "<date> <title> [v2805139766]"
    sid = lib.stream_id('twitch', twitch.group(1)) if twitch else lib.stream_id('file', f'{path.name}|{size}')
    if s := _existing(sid):
        return s
    m = DATED.match(path.stem)
    date = date or (m.group(1) if m else datetime.fromtimestamp(path.stat().st_mtime).date().isoformat())
    title = title or clean_title(m.group(2) if m else path.stem) or path.stem
    lib.STREAMS.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = 'link' if _same_volume(path.parent, lib.STREAMS) else 'copy'
    source = {'kind': 'file', 'path': str(path), 'name': path.name, 'size': size, 'mode': mode}
    if twitch:
        source.update(kind='twitch', id=twitch.group(1), url=f'https://www.twitch.tv/videos/{twitch.group(1)}')
    stream = lib.create_stream(sid, title, date, source, media=f'source{path.suffix.lower()}')
    dest = stream.media
    try:
        if mode == 'move':
            shutil.move(str(path), str(dest))
        elif mode == 'link':
            try:
                os.link(path, dest)
            except OSError:  # different volume or filesystem without hard links: copy in the fetch stage
                stream.update(lambda meta: meta['source'].update(mode='copy'))
    except Exception:
        shutil.rmtree(stream.folder, ignore_errors=True)
        raise
    return stream


def _copy(src, dest, progress):
    total = src.stat().st_size or 1
    part = dest.with_name(dest.name + '.part')
    done = 0
    with open(src, 'rb') as r, open(part, 'wb') as w:
        while block := r.read(COPY_BLOCK):
            w.write(block)
            done += len(block)
            progress(done / total, f'copying {done / 2**30:.1f} of {total / 2**30:.1f} GB')
    os.replace(part, dest)
    shutil.copystat(src, dest)


def _download(stream, progress):
    import yt_dlp

    def hook(d):
        if d.get('status') != 'downloading':
            return
        if d.get('fragment_count'):
            fraction = (d.get('fragment_index') or 0) / d['fragment_count']
        else:
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            fraction = (d.get('downloaded_bytes') or 0) / total if total else 0
        speed = d.get('speed')
        progress(min(fraction, 0.999), f'downloading {speed / 2**20:.1f} MB/s' if speed else 'downloading')

    opts = {
        'format': FORMAT, 'merge_output_format': 'mp4', 'outtmpl': str(stream.folder / 'source.%(ext)s'),
        'noplaylist': True, 'quiet': True, 'no_warnings': True, 'noprogress': True, 'progress_hooks': [hook],
        'continuedl': True, 'concurrent_fragment_downloads': 8, 'retries': 20, 'fragment_retries': 50,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(stream.meta['source']['url'], download=True)
    downloads = info.get('requested_downloads') or [{}]
    path = Path(downloads[0].get('filepath') or stream.folder / 'source.mp4')
    stream.update(lambda meta: meta.update(media=path.name))


def fetch(stream, progress=lambda fraction, note='': None):
    """The 'fetch' stage: make sure the stream's video is in its folder, then record its duration."""
    source = stream.meta['source']
    if source.get('path'):  # added from a local file (possibly a downloaded Twitch VOD)
        dest = stream.media
        if not dest.exists():
            src = Path(source['path'])
            if not src.exists():
                raise FileNotFoundError(f'the original file is gone: {src}')
            _copy(src, dest, progress)
    elif not stream.media or not stream.media.exists():
        _download(stream, progress)
    from .media import fix_stream  # fragmented MP4s open slowly everywhere: put the index up front, losslessly
    fix_stream(stream, lambda f, note='': progress(0.9 + 0.1 * f, note))
    duration = probe_duration(stream.media)
    if duration <= 0:
        raise ValueError(f'{stream.media.name} has no readable duration; is it a video file?')
    stream.update(lambda meta: meta.update(duration=round(duration, 3)))
