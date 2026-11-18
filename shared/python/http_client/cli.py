import argparse
import json
import os
import sys
from pathlib import Path
from execution_policy import PolicyError
from execution_result import error_result, emit
from .client import HttpClient, load_json


def main(service, effect):
    parser=argparse.ArgumentParser(description=service+' '+effect+' execution')
    parser.add_argument('--config',default=os.environ.get('HTTP_ACCESS_CONFIG'))
    parser.add_argument('--profile',required=True)
    parser.add_argument('--request',required=True)
    if effect=='write': parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    started=False
    try:
        if not args.config: raise PolicyError('External config required')
        profiles=load_json(args.config)['profiles']
        profile=profiles[args.profile]
        if profile.get('service')!=service: raise PolicyError('Profile service mismatch')
        catalog_path=Path(profile['operations_file']).expanduser()
        if not catalog_path.is_absolute(): raise PolicyError('operations_file must be absolute')
        catalog=load_json(catalog_path)
        data=json.load(sys.stdin) if args.request=='-' else load_json(args.request)
        requests=data if isinstance(data,list) else [data]
        if not 1<=len(requests)<=10 or (effect=='write' and len(requests)!=1):
            raise PolicyError('Read batch 1..10; write exactly one operation')
        with HttpClient(profile,catalog) as client:
            # Validate all requests before any side effect.
            for request in requests: client.prepare(request,effect,getattr(args,'apply',False))
            results=[]
            remaining=client.budget
            for request in requests:
                started=True
                result=client.request(request,effect=effect,apply=getattr(args,'apply',False))
                size=len(json.dumps(result.get('body'),ensure_ascii=False).encode())
                if size>remaining:
                    result['body']=None
                    result['truncated']=True
                else: remaining-=size
                results.append(result)
                if not result['ok']: break
        ok=all(r['ok'] for r in results) and len(results)==len(requests)
        emit({'ok':ok,'service':service,'profile':args.profile,'results':results})
        return 0 if ok else 1
    except (ValueError,KeyError,TypeError,OSError):
        emit(error_result('configuration-or-validation','unknown' if effect=='write' and started else 'not-started'))
    except Exception:
        emit(error_result('http-execution','unknown' if effect=='write' and started else 'failed'))
    return 1
