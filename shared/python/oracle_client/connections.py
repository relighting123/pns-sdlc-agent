import os
from credential_store import resolve
import importlib
from .common import QueryError, read_json, integer

def load_profile(config, database):
    profiles = read_json(config).get('databases', {})
    if database not in profiles:
        raise QueryError('Unknown database ID')
    profile = profiles[database]
    if profile.get('mode') not in ('thin', 'thick'):
        raise QueryError('Profile mode must be thin or thick')
    for key in ('dsn_env', 'user_env', 'password_env'):
        if key[:-4] + '_ref' not in profile and not os.environ.get(profile.get(key, '')):
            raise QueryError('Missing profile credential environment: ' + key)
    return profile


def connect(profile):
    driver = importlib.import_module('oracledb')
    if profile['mode'] == 'thick':
        kwargs = {}
        for key in ('lib_dir', 'config_dir'):
            if profile.get(key):
                kwargs[key] = profile[key]
        driver.init_oracle_client(**kwargs)
    kwargs = dict(dsn=resolve(profile, 'dsn'), user=resolve(profile, 'user'),
                  password=resolve(profile, 'password'))
    if profile.get('config_dir'):
        kwargs['config_dir'] = profile['config_dir']
    conn = driver.connect(**kwargs)
    try:
        if bool(conn.thin) != (profile['mode'] == 'thin'):
            raise QueryError('Driver mode differs from requested profile')
        conn.autocommit = False
        conn.call_timeout = integer(profile.get('call_timeout_ms', 15000), 1, 120000, 'call_timeout_ms')
        return conn
    except Exception:
        conn.close()
        raise
