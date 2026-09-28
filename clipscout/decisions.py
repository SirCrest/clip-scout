"""Reviewers' calls, kept apart from anything a model wrote.

library/decisions.json = {"version": 3,
  "decisions": {"<stream id>/<clip id>": {"d": "keep"|"maybe"|"cut", "why": str|null, "at": iso}},
  "seen": {key: "YYYY-MM-DD"}, "merges": [[key, ...]], "posts": {key: X post text}}
"""
from datetime import date

from . import library as lib

EMPTY = {'version': 3, 'decisions': {}, 'seen': {}, 'merges': [], 'posts': {}}


def _path():
    return lib.LIBRARY / 'decisions.json'


def load():
    data = lib.read_json(_path(), None) or {}
    return {**EMPTY, **data, 'version': 3}


def _change(fn):
    with lib.locked(_path()):
        data = load()
        result = fn(data)
        lib.write_json(_path(), data)
    return result


def decide(key, d, why=None):
    """Record keep/maybe/cut for a clip; d=None removes the decision (undo). Returns the previous one."""
    def fn(data):
        before = data['decisions'].get(key)
        if d is None:
            data['decisions'].pop(key, None)
        else:
            data['decisions'][key] = {'d': d, 'why': why, 'at': lib.now()}
        return before
    return _change(fn)


def set_reason(key, why):
    def fn(data):
        if key in data['decisions']:
            data['decisions'][key]['why'] = why
    _change(fn)


def mark_seen(keys):
    today = date.today().isoformat()

    def fn(data):
        for k in keys:
            data['seen'].setdefault(k, today)
    _change(fn)


def set_post(key, text):
    def fn(data):
        if text:
            data['posts'][key] = text
        else:
            data['posts'].pop(key, None)
    _change(fn)


def add_merge(keys):
    def fn(data):
        data['merges'] = [m for m in data['merges'] if not set(m) & set(keys)] + [list(keys)]
    _change(fn)
