import shutil
import subprocess

import pytest

from clipscout import ingest
from clipscout import library as lib


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, 'STREAMS', tmp_path / 'library' / 'streams')
    return tmp_path


def make_video(path, seconds=1):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc=duration={seconds}:size=64x36:rate=10',
                    '-f', 'lavfi', '-i', f'sine=duration={seconds}', '-shortest', '-c:v', 'libx264', '-c:a', 'aac',
                    str(path)], check=True)
    return path


needs_ffmpeg = pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg not installed')


@pytest.mark.parametrize('url,expected', [
    ('https://www.twitch.tv/videos/2805139766', ('twitch', '2805139766')),
    ('https://www.twitch.tv/elgato/video/2805139766?t=1h2m', ('twitch', '2805139766')),
    ('https://www.youtube.com/watch?v=jNQXAC9IVRw', ('youtube', 'jNQXAC9IVRw')),
    ('https://www.youtube.com/watch?feature=share&v=jNQXAC9IVRw', ('youtube', 'jNQXAC9IVRw')),
    ('https://youtu.be/jNQXAC9IVRw?si=abc', ('youtube', 'jNQXAC9IVRw')),
    ('https://www.youtube.com/live/jNQXAC9IVRw', ('youtube', 'jNQXAC9IVRw')),
    ('https://www.youtube.com/shorts/jNQXAC9IVRw', ('youtube', 'jNQXAC9IVRw')),
    ('https://vimeo.com/12345', ('url', None)),
])
def test_classify(url, expected):
    assert ingest.classify(url) == expected


def test_clean_title():
    assert ingest.clean_title('Wave XLR Pro Deep Dive + Q&A | !WaveXLRPro !giveaway') == 'Wave XLR Pro Deep Dive + Q&A'
    assert ingest.clean_title('Saxophones and Stream Decks [v2580717889]') == 'Saxophones and Stream Decks'


def test_stream_ids():
    assert lib.stream_id('twitch', 'v2805139766') == 'tw2805139766'
    assert lib.stream_id('youtube', 'jNQXAC9IVRw') == 'ytjNQXAC9IVRw'
    assert lib.stream_id('file', 'a.mp4|1') == lib.stream_id('file', 'a.mp4|1')
    assert lib.stream_id('file', 'a.mp4|1').startswith('f')


@needs_ffmpeg
def test_add_file_links_and_is_idempotent(library):
    src = make_video(library / '2026-09-15 Features you missed [v2805139766].mp4')
    s = ingest.add(src)
    assert s.date == '2026-09-15'
    assert s.title == 'Features you missed'
    assert s.id == 'tw2805139766'  # the yt-dlp tag keeps a downloaded VOD's Twitch identity
    assert s.meta['source']['kind'] == 'twitch' and s.meta['source']['path'] == str(src.resolve())
    assert s.media.name == 'source.mp4' and s.media.exists()
    assert ingest.add(src).id == s.id
    ingest.fetch(s)
    assert 0.9 < s.reload().meta['duration'] < 1.2


@needs_ffmpeg
def test_add_file_copy_happens_in_fetch(library):
    src = make_video(library / 'no date here.mp4')
    s = ingest.add(src, mode='copy')
    assert s.title == 'no date here'
    assert len(s.date) == 10
    assert not s.media.exists()
    seen = []
    ingest.fetch(s, lambda f, note='': seen.append(f))
    assert s.media.exists() and src.exists()
    assert seen and seen[-1] == 1.0


@needs_ffmpeg
def test_add_file_move(library):
    src = make_video(library / 'clip.mp4')
    s = ingest.add(src, mode='move', title='Moved', date='2026-01-02')
    assert not src.exists() and s.media.exists()
    assert (s.title, s.date) == ('Moved', '2026-01-02')


def test_missing_file(library):
    with pytest.raises(FileNotFoundError):
        ingest.add(library / 'nope.mp4')
