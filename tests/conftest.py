import pytest

from clipscout import library as lib


@pytest.fixture
def library(tmp_path, monkeypatch):
    """An empty library in a temp folder."""
    monkeypatch.setattr(lib, 'LIBRARY', tmp_path)
    monkeypatch.setattr(lib, 'STREAMS', tmp_path / 'streams')
    monkeypatch.setattr(lib, 'TASKS', tmp_path / 'tasks')
    return tmp_path


SENTENCES = """# v1  Test stream
# duration 00:10:00

[00:00:10  10.00]  Welcome back to the stream everyone.
   ~ pause 2.0s
[00:00:14  14.50]  So, does the Stream Deck Plus come in white?
[00:00:18  18.20]  It does, the white one launched last year.
   ~ pause 1.5s
[00:00:25  25.00]  Anyways, though, I set up hotkeys on my Wave Link.
[00:00:30  30.40]  That's the trick.
"""
