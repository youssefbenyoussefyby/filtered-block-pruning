
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import experiments
from src.reproducibility import csv_hash

REPO = Path(__file__).resolve().parent.parent
SMALL_N = 20_000


@pytest.fixture
def small(tmp_path, monkeypatch):
    monkeypatch.setattr(experiments, "DATA", dict(experiments.DATA, n=SMALL_N))
    monkeypatch.setattr(experiments, "N", SMALL_N)
    monkeypatch.setattr(experiments, "QUERIES", dict(experiments.QUERIES, num_queries=20))
    monkeypatch.setattr(experiments, "REPEATS", 1)
    monkeypatch.setattr(experiments, "E4_BLOCK_SIZES", (1_000, 5_000))
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(experiments, "RESULTS", results)
    return results


@pytest.fixture
def ran(small):
    for run in experiments.EXPERIMENTS.values():
        run()
    return small


def test_writes_every_file_plots_needs_with_its_columns(ran):
    needed = {
        "e1_e2_summary.csv": {"dist", "pruner", "layout", "rho", "bucket", "queries", "frac_blocks", "recall",
                              "speedup_p50", "blocks_ratio_p50"},
        "e1_e2_per_query.csv": {"dist", "pruner", "layout", "rho", "bucket", "ideal_frac"},
        "e3_per_query.csv": {"rho", "layout", "order", "m", "bucket", "frac_blocks", "recall"},
        "e4_per_query.csv": {"block_size", "bucket", "blocks_touched", "read_amplification"},
    }
    for name, columns in needed.items():
        df = pd.read_csv(ran / name)
        assert columns <= set(df.columns), f"{name} is missing {columns - set(df.columns)}"
        assert len(df) > 0


def test_e1_e2_covers_every_combination(ran):
    per_query = pd.read_csv(ran / "e1_e2_per_query.csv")
    combos = set(per_query[["dist", "rho", "layout"]].itertuples(index=False, name=None))
    expected = {(d, 0.8, l) for d in ("uniform", "zipf") for l in ("random", "tenant_sorted", "vector_clustered")}
    expected |= {(d, 1.0, "vector_clustered") for d in ("uniform", "zipf")}
    assert combos == expected
    assert set(per_query.pruner) == {"none", "zonemap", "tenant_set"}
    assert len(per_query) == len(expected) * 3 * 20


def test_attribute_pruning_is_lossless_and_full_scan_reads_everything(ran):
    per_query = pd.read_csv(ran / "e1_e2_per_query.csv")
    assert (per_query.recall == 1.0).all()
    full = per_query[per_query.pruner == "none"]
    assert (full.frac_blocks == 1.0).all()
    assert (full.blocks_ratio == 1.0).all()


def test_speedup_is_against_the_full_scan_of_the_same_query(ran):
    per_query = pd.read_csv(ran / "e1_e2_per_query.csv")
    ts = per_query[per_query.pruner == "tenant_set"]
    full = per_query[per_query.pruner == "none"].set_index(["dist", "rho", "layout", "query"]).latency_ms
    expected = full.loc[list(ts[["dist", "rho", "layout", "query"]].itertuples(index=False, name=None))].values
    assert np.allclose(ts.speedup, expected / ts.latency_ms.values)
    assert (per_query[per_query.pruner == "zonemap"].latency_ms.isna()).all()


def test_e3_recall_reaches_one_when_all_surviving_blocks_are_scanned(ran):
    e3 = pd.read_csv(ran / "e3_per_query.csv")
    assert set(e3.order) == {"tenant_set_by_centroid", "tenant_set_by_bound", "early_stop"}
    assert e3[e3.order == "early_stop"].m.isna().all()
    assert (e3[e3.m == 40].recall == 1.0).all()
    assert (e3[e3.order == "early_stop"].recall == 1.0).all()


def test_e4_read_amplification_is_at_least_one(ran):
    e4 = pd.read_csv(ran / "e4_per_query.csv")
    assert set(e4.block_size) == {1_000, 5_000}
    assert (e4.read_amplification >= 1.0 - 1e-9).all()


def test_plots_run_on_the_experiment_output(ran):
    done = subprocess.run([sys.executable, str(REPO / "plots.py")], cwd=ran.parent, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(REPO)})
    assert done.returncode == 0, done.stderr
    assert len(list((ran.parent / "plots").glob("*.png"))) == 4


def test_two_runs_give_the_same_results_hash(small, tmp_path, monkeypatch):
    hashes = []
    for i in range(2):
        out = tmp_path / f"run{i}"
        out.mkdir()
        monkeypatch.setattr(experiments, "RESULTS", out)
        experiments.e1_e2()
        experiments.e3()
        hashes.append({f: csv_hash(out / f) for f in ("e1_e2_per_query.csv", "e1_e2_summary.csv", "e3_per_query.csv")})
    assert hashes[0] == hashes[1]

