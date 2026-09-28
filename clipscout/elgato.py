"""Elgato knowledge, loaded from the repo's elgato/ folder (the only place it's written down)."""
import json
import re
from functools import lru_cache

from .library import ELGATO


@lru_cache
def _products():
    return json.loads((ELGATO / 'products.json').read_text(encoding='utf-8'))


def topics():
    return list(_products()['topics'])


def topic(product):
    for name, products in _products()['topics'].items():
        if product in products:
            return name
    return 'Other'


def products():
    return [p for ps in _products()['topics'].values() for p in ps]


def glossary():
    return (ELGATO / 'glossary.txt').read_text(encoding='utf-8').strip()


def fix_names(text):
    for pattern, replacement in _products()['name_fixes']:
        text = re.sub(pattern, replacement, text)
    return text
