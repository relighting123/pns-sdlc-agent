import argparse
import json
import os
import re
import sys
from execution_policy import PolicyError
from execution_result import error_result, emit
from .common import QueryError, read_json
from .connections import load_profile
from .query_executor import run_batch
from .write_executor import CommitUnknown, prepare, run_write


def main(effect):
    parser = argparse.ArgumentParser(description='Oracle ' + effect + ' execution')
    parser.add_argument('--config', default=os.environ.get('ORACLE_ACCESS_CONFIG') or os.environ.get('ORACLE_QUERY_CONFIG'))
    parser.add_argument('--database', required=True)
    parser.add_argument('--request', required=True)
    if effect == 'write': parser.add_argument('--apply', action='store_true')
    args=parser.parse_args()
    started=False
    try:
        if not args.config: raise QueryError('Missing external config')
        profile=load_profile(args.config,args.database)
        request=json.load(sys.stdin) if args.request=='-' else read_json(args.request)
        if effect=='write':
            prepare(profile, request, args.apply)
            started=True
            result=run_write(profile,request,args.apply)
        else:
            result=run_batch(profile,request)
            result['outcome']='read'
        result['database']=args.database
        emit(result)
        return 0
    except CommitUnknown:
        emit(error_result('commit-unknown','unknown'))
    except (QueryError,PolicyError):
        emit(error_result('validation-or-row-count','unknown' if started else 'not-started'))
    except Exception as error:
        code=getattr(error.args[0],'full_code',None) if error.args else None
        if not isinstance(code,str) or not re.fullmatch(r'(ORA|DPY|DPI)-\d+',code): code=None
        emit(error_result('oracle-execution','unknown' if started else 'failed',code))
    return 1
