"""Provider-reported cache accounting; unknown values remain unknown."""
from __future__ import annotations


def normalize_usage(kind: str, usage: dict) -> dict:
    def count(key):
        value = usage.get(key)
        return value if type(value) is int and value >= 0 else None
    incoming, outgoing = count('input_tokens'), count('output_tokens')
    if kind == 'codex':
        read, write = count('cached_input_tokens'), None
        total = incoming
        fresh = incoming - read if incoming is not None and read is not None and read <= incoming else None
        if incoming is not None and read is not None and read > incoming:
            read = None
    elif kind == 'claude':
        read, write = count('cache_read_input_tokens'), count('cache_creation_input_tokens')
        fresh = incoming
        total = incoming + read + write if all(v is not None for v in (incoming, read, write)) else None
    else:
        total, fresh, read, write = incoming, None, None, None
    return {'input_tokens': total, 'uncached_input_tokens': fresh, 'cache_read_input_tokens': read,
            'cache_write_input_tokens': write, 'output_tokens': outgoing}


def summarize(calls: list[dict]) -> dict:
    remote = [c for c in calls if not c.get('cache_hit')]
    usage = [c.get('normalized_usage', {}) for c in remote]
    def total(field):
        values = [u.get(field) for u in usage]
        known = [v for v in values if v is not None]
        return {'reported_total': sum(known) if known else None, 'reporting_calls': len(known)}
    return {'model_calls': len(remote), 'result_cache_hits': len(calls) - len(remote),
            'estimated_tokens_avoided_by_result_cache': sum(c.get('estimated_input_tokens', 0) for c in calls if c.get('cache_hit')),
            'submitted_prompt_bytes': sum(c['prompt_bytes'] for c in remote),
            'context_build_ms': sum(c.get('context_build_ms', 0) for c in calls),
            'token_accounting': {key: total(key) for key in
                ('input_tokens', 'uncached_input_tokens', 'cache_read_input_tokens', 'cache_write_input_tokens', 'output_tokens')},
            'ttft_ms': None,
            'measurement_note': 'Latency covers the full provider process, not isolated prefill or first-token time. Missing usage is unknown. Prefix bytes do not prove a provider cache hit.'}
