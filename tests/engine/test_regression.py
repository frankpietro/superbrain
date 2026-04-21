"""Engine golden regression test.

Re-runs the value-bet pipeline on the same deterministic synthetic lake used
by ``scripts/generate_engine_golden.py`` and asserts the output matches the
frozen corpus at ``tests/engine/fixtures/golden/engine_pipeline.json``.

Any intentional change to the engine (clustering, similarity, probability,
pricing, value-bet filtering) that legitimately alters the corpus must be
accompanied by a rerun of the script and a refreshed golden file, committed
together. Unintentional drift shows up as a diff here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from scripts.generate_engine_golden import (
    GOLDEN_FILE,
    build_corpus,
    canonicalise_cluster_partition,
    hash_object,
    hash_similarity_matrix,
)


@pytest.fixture()
def golden_payload() -> dict[str, Any]:
    if not GOLDEN_FILE.exists():
        pytest.fail(
            f"golden corpus missing at {GOLDEN_FILE}; "
            "run `uv run python scripts/generate_engine_golden.py`"
        )
    payload: dict[str, Any] = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    return payload


def test_cluster_partition_is_stable(tmp_path: Path, golden_payload: dict[str, Any]) -> None:
    corpus = build_corpus(tmp_path)
    assert corpus.cluster_partition_checksum == golden_payload["cluster_partition_checksum"], (
        "cluster partition drift — regenerate with "
        "`uv run python scripts/generate_engine_golden.py` if the change is intentional"
    )


def test_similarity_matrix_is_stable(tmp_path: Path, golden_payload: dict[str, Any]) -> None:
    corpus = build_corpus(tmp_path)
    assert corpus.similarity_matrix_checksum == golden_payload["similarity_matrix_checksum"], (
        "similarity matrix drift — regenerate with "
        "`uv run python scripts/generate_engine_golden.py` if the change is intentional"
    )


def test_priced_outcomes_are_stable(tmp_path: Path, golden_payload: dict[str, Any]) -> None:
    corpus = build_corpus(tmp_path)
    fresh = corpus.priced_outcomes
    frozen: list[dict[str, Any]] = list(golden_payload["priced_outcomes"])

    assert len(fresh) == len(frozen), (
        f"priced-outcome count drifted: {len(fresh)} fresh vs {len(frozen)} frozen"
    )

    for new, old in zip(fresh, frozen, strict=True):
        assert new["market"] == old["market"]
        assert new["selection"] == old["selection"]
        assert new["params"] == old["params"]
        assert new["target_columns"] == old["target_columns"]
        assert new["sample_size"] == old["sample_size"]
        assert new["model_probability"] == pytest.approx(old["model_probability"], abs=1e-12)
        assert new["model_payout"] == pytest.approx(old["model_payout"], abs=1e-9)


def test_value_bets_are_stable(tmp_path: Path, golden_payload: dict[str, Any]) -> None:
    corpus = build_corpus(tmp_path)
    fresh = corpus.value_bets
    frozen: list[dict[str, Any]] = list(golden_payload["value_bets"])

    assert len(fresh) == len(frozen), (
        f"value-bet count drifted: {len(fresh)} fresh vs {len(frozen)} frozen"
    )

    for new, old in zip(fresh, frozen, strict=True):
        assert new["market"] == old["market"]
        assert new["selection"] == old["selection"]
        assert new["bookmaker"] == old["bookmaker"]
        assert new["params"] == old["params"]
        assert new["decimal_odds"] == pytest.approx(old["decimal_odds"], abs=1e-12)
        assert new["book_probability"] == pytest.approx(old["book_probability"], abs=1e-12)
        assert new["model_probability"] == pytest.approx(old["model_probability"], abs=1e-12)
        assert new["edge"] == pytest.approx(old["edge"], abs=1e-12)


def test_canonical_partition_is_cluster_id_invariant() -> None:
    """Sanity check on the canonical partition helper.

    Two cluster-id relabellings of the same partition must produce the same
    canonical list. This guards against regressions in the helper itself.
    """
    original = {"A": 0, "B": 0, "C": 1, "D": 1, "E": 2}
    relabelled = {"A": 7, "B": 7, "C": 3, "D": 3, "E": 9}

    p1 = canonicalise_cluster_partition(original)
    p2 = canonicalise_cluster_partition(relabelled)

    assert p1 == p2
    assert hash_object(p1) == hash_object(p2)


def test_similarity_hash_is_key_order_invariant() -> None:
    """Sanity check on the similarity hasher.

    Feeding the helper the same matrix under two different key orderings
    (the helper re-sorts internally) must produce the same digest.
    """
    keys = [("A", "2023-24"), ("B", "2023-24"), ("C", "2023-24")]
    values = np.array([[1.0, 0.5, 0.2], [0.5, 1.0, 0.3], [0.2, 0.3, 1.0]], dtype=np.float64)

    reversed_keys = list(reversed(keys))
    perm = [keys.index(k) for k in reversed_keys]
    reversed_values = values[np.ix_(perm, perm)]

    assert hash_similarity_matrix(values, keys) == hash_similarity_matrix(
        reversed_values, reversed_keys
    )
