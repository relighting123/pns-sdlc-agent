import json
import re
from pathlib import Path

class QueryError(Exception):
    pass


def read_json(path):
    with Path(path).expanduser().open(encoding='utf-8') as stream:
        return json.load(stream)


def integer(value, low, high, field):
    if type(value) is not int or not low <= value <= high:
        raise QueryError('Invalid limit: ' + field)
    return value
