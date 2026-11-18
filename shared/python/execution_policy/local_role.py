"""Authorize a selected role against the logged-in OS principal and target profile."""
import csv
import os
import subprocess

from . import PolicyError


def principal():
    if os.name == 'nt':
        # SID stays stable across display-name changes and Windows locales.
        import ctypes
        directory = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetSystemDirectoryW(directory, len(directory)):
            raise PolicyError('Cannot identify system directory')
        command = os.path.join(directory.value, 'whoami.exe')
        rows = subprocess.check_output([command, '/user', '/fo', 'csv', '/nh'])
        return next(csv.reader(rows.decode('ascii', errors='replace').splitlines()))[1]
    import pwd
    return pwd.getpwuid(os.geteuid()).pw_name


def authorize(profile, effect):
    role = os.environ.get('SDLC_DATA_ROLE')
    policy = profile.get('role_access')
    if role and isinstance(policy, dict):
        members = policy.get(role)
        if isinstance(members, dict):
            effects = members.get(principal())
            if isinstance(effects, list) and effect in effects:
                return
    raise PolicyError('Local role has no grant on this profile')
