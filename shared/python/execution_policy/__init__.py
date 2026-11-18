"""Execution checks shared by service-specific skill entrypoints."""


class PolicyError(ValueError):
    pass


def require_effect(operation, effect, allow_write=False, apply=False):
    if effect not in ('read', 'write') or operation.get('effect') != effect:
        raise PolicyError('Operation effect does not match this skill')
    if effect == 'write' and (allow_write is not True or apply is not True):
        raise PolicyError('Writes require profile allow_write=true and explicit --apply')


def bounded_int(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise PolicyError('Invalid limit: ' + name)
    return value
