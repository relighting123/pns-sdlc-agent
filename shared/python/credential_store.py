"""Resolve an operator-selected credential at the client boundary."""
import json
import os
from pathlib import Path
import re

STORE = Path(__file__).resolve().parents[2] / 'wiki' / 'credentials'


def resolve(config, name):
    ref = config.get(name + '_ref')
    if ref is None:
        return os.environ.get(config.get(name + '_env', ''), '')
    if not isinstance(ref, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', ref):
        raise ValueError('Invalid credential reference')
    try:
        path = STORE / (ref + '.json')
        value = json.loads(path.read_text(encoding='utf-8'))['value']
        if isinstance(value, str) and value:
            return value
    except (OSError, KeyError, TypeError, ValueError):
        pass
    raise ValueError('Credential unavailable')
