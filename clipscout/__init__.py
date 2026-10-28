"""Clip Scout: stream in, best clips out."""
from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version('clip-scout')
except PackageNotFoundError:  # running from a folder uv hasn't installed
    __version__ = 'dev'
