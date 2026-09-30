"""Dependency-free local unsupervised kNN. No services, downloads or serialized code."""
from dataclasses import replace
from decimal import Decimal
from math import sqrt
from random import Random
from statistics import median
from typing import Protocol
from .features import TransactionFeatures, build_features
from .models import PaymentIntent, Transaction, WalletContext, ValidationError
from .policy import load_policy


class LocalAnomalyModel(Protocol):
    def fit(self, rows: list[TransactionFeatures]) -> None: ...
    def score(self, row: TransactionFeatures) -> Decimal: ...


class LocalKNNAnomalyModel:
    """Robustly scaled k-nearest distances, normalized by held-in LOO distances.

    score = distance / (distance + 8 * normal_reference_distance).
    This is a behavioural anomaly score, never a fraud probability.
    """
    def __init__(self, k=3):
        if type(k) is not int or k < 1:
            raise ValidationError('Invalid neighbour count')
        self.k = k
        self.reference = ()

    def fit(self, rows):
        if len(rows) < 4 or any(not isinstance(r, TransactionFeatures) for r in rows):
            raise ValidationError('At least four valid local reference rows required')
        vectors = [r.vector() for r in rows]
        columns = list(zip(*vectors))
        self.center = tuple(median(c) for c in columns)
        self.scale = tuple(max(sorted(c)[3 * len(c) // 4] - sorted(c)[len(c) // 4], abs(median(c)) * .1, .01) for c in columns)
        self.reference = tuple(self._normalize(v) for v in vectors)
        distances = [self._distance(v, self.reference[:i] + self.reference[i + 1:]) for i, v in enumerate(self.reference)]
        self.normal_distance = max(median(distances), .1)

    def _normalize(self, vector):
        return tuple((v - c) / s for v, c, s in zip(vector, self.center, self.scale))

    def _distance(self, vector, references):
        distances = sorted(sqrt(sum((a - b) ** 2 for a, b in zip(vector, ref)) / len(vector)) for ref in references)
        nearest = distances[:self.k]
        return sum(nearest) / len(nearest)

    def score(self, row):
        if not self.reference or not isinstance(row, TransactionFeatures):
            raise ValidationError('Anomaly model requires fitting and validated features')
        distance = self._distance(self._normalize(row.vector()), self.reference)
        return Decimal(str(distance / (distance + 8 * self.normal_distance)))


def demo_reference_features():
    """128 synthetic normal examples, seed 2048; no golden inputs or labels read.

    Reference identities are synthetic and distinct from evaluation identities.
    Amounts, balances and daily spend vary independently to avoid one-point fit.
    """
    rng = Random(2048)
    policy = replace(load_policy(), trusted_recipients=('ReferenceA', 'ReferenceB'))
    rows = []
    for _ in range(128):
        typical = Decimal(rng.randrange(3, 10)) / 100
        count = rng.randrange(2, 7)
        history = tuple(Transaction('ReferenceA', typical, 'CC', 'demo normal', None,
                                    '2026-09-01T08:00:00Z', 'PROCEED_TO_DAML', False) for _ in range(count))
        context = WalletContext(Decimal(rng.randrange(80, 201)) / 100,
                                Decimal(rng.randrange(0, 100)) / 100, history)
        intent = PaymentIntent('ReferenceA', typical * Decimal(rng.randrange(60, 161)) / 100, 'CC', 'demo normal')
        rows.append(build_features(intent, context, policy))
    return rows


def default_model():
    model = LocalKNNAnomalyModel()
    model.fit(demo_reference_features())
    return model


def model_info(model):
    from importlib.util import find_spec
    return {'model_type': type(model).__name__, 'feature_count': len(TransactionFeatures.names()),
            'reference_transaction_count': len(model.reference), 'training_source': '128 synthetic normal references; seed 2048; no fraud labels',
            'sklearn_available': find_spec('sklearn') is not None, 'inference': 'local only'}
