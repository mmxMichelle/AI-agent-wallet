"""Stable token overlap retrieval; the guardrail always reads the whole policy."""
import re
from .models import jsonable
from .policy import WalletPolicy


def retrieve(policy: WalletPolicy, query: str, limit: int = 5) -> list[dict]:
    tokens = set(re.findall(r'\w+', query.lower()))
    excerpts = []
    for key, value in jsonable(policy).items():
        body = f'{key.replace("_", " ")}: {value}'
        score = len(tokens & set(re.findall(r'\w+', body.lower())))
        excerpts.append({'reference': f'policy.{key}', 'text': body, 'score': score})
    return sorted(excerpts, key=lambda x: (-x['score'], x['reference']))[:limit]
