import json
import os
import subprocess
from importlib.metadata import version

import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_info

from src.data import make_dataset, make_queries
from src.layout import build_blocks
from src.metadata import build_metadata
from src.metrics import measure
from src.reproducibility import (
    PACKAGES, THREAD_VARS, csv_hash, git_commit, limit_threads, run_config, table_hash, write_run_config,
)
from src.search import search


@pytest.fixture
def one_thread():
    saved = {v: os.environ.get(v) for v in THREAD_VARS}
    limiter = limit_threads(1)
    yield
    limiter.restore_original_limits()
    for var, value in saved.items():
        if value is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = value


def small_table():
    return pd.DataFrame({
        "query": [0, 0, 1],
        "method": ["a", "b", "a"],
        "recall": [1.0, 0.7, 0.123456789012345],
        "latency_ms": [1.5, 2.5, 3.5],
    })


# Threads


def test_limit_threads_sets_every_thread_pool_to_one(one_thread):
    assert all(info["num_threads"] == 1 for info in threadpool_info())
    assert all(os.environ[var] == "1" for var in THREAD_VARS)


# Run config


def test_run_config_records_params_versions_and_commit(one_thread):
    config = run_config(experiment="E1", n=200_000, block_size=5_000, seed=0)
    assert config["params"] == {"experiment": "E1", "n": 200_000, "block_size": 5_000, "seed": 0}
    assert config["packages"] == {p: version(p) for p in PACKAGES}
    assert config["threads"] == [1]
    assert config["python"].startswith("3.13")


def test_git_commit_matches_git():
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    info = git_commit()
    assert info["commit"] == head
    assert isinstance(info["dirty"], bool)


def test_write_run_config_writes_readable_json(tmp_path):
    path = tmp_path / "results" / "run_config.json"
    written = write_run_config(path, experiment="E3", rho=0.8)
    assert json.loads(path.read_text()) == json.loads(json.dumps(written, default=str))


# Results hash


def test_hash_is_the_same_for_the_same_table():
    assert table_hash(small_table()) == table_hash(small_table())


def test_hash_ignores_timing_columns():
    other = small_table()
    other["latency_ms"] = [9.0, 9.0, 9.0]
    assert table_hash(other) == table_hash(small_table())


@pytest.mark.parametrize("column, value", [("recall", 0.123456789012346), ("method", "c"), ("query", 2)])
def test_hash_changes_when_any_result_changes(column, value):
    other = small_table()
    other.loc[2, column] = value
    assert table_hash(other) != table_hash(small_table())


def test_hash_survives_a_csv_round_trip(tmp_path):
    """Saving and reloading must not change the hash, or two runs could not be compared from files."""
    df = small_table()
    df["bucket"] = pd.Categorical(["<0.5%", "2-5%", "<0.5%"])
    path = tmp_path / "results.csv"
    df.to_csv(path, index=False)
    assert csv_hash(path) == table_hash(df)


# End to end: the D10 claim, at small scale


def run_small_experiment(layout):
    ds = make_dataset(n=10_000)
    blocks, _ = build_blocks(ds, layout, 1_000)
    meta = build_metadata(blocks, ds.num_tenants)
    queries = make_queries(ds, num_queries=10)
    truth = [search(blocks, q, meta, "none", 10) for q in queries]
    methods = {"full": {"pruner": "none"}, "m2": {"pruner": "tenant_set_by_centroid", "max_blocks": 2}}
    return measure(blocks, meta, queries, truth, methods, repeats=1)


@pytest.mark.parametrize("layout", ["random", "tenant_sorted", "vector_clustered"])
def test_two_runs_give_the_same_results_hash(one_thread, layout):
    first, second = run_small_experiment(layout), run_small_experiment(layout)
    assert table_hash(first) == table_hash(second)
