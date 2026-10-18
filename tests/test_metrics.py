import numpy as np
import pandas as pd
import pytest

import src.search as search_mod
from src.data import make_dataset, make_queries
from src.layout import build_blocks
from src.metadata import build_metadata
from src.metrics import BUCKET_LABELS, measure, recall_at_k, summarize, timed

N = 20_000
SIZE = 1_000
NUM_TENANTS = 100

METHODS = {
    "full_scan": {"pruner": "none"},
    "tenant_set": {"pruner": "tenant_set"},
    "first_block": {"pruner": "tenant_set_by_centroid", "max_blocks": 1},
}


@pytest.fixture(scope="module")
def setup():
    ds = make_dataset(n=N)
    blocks, _ = build_blocks(ds, "random", SIZE)
    meta = build_metadata(blocks, NUM_TENANTS)
    queries = make_queries(ds, num_queries=20)
    truth = [search_mod.search(blocks, q, meta, "none", 10) for q in queries]
    return blocks, meta, queries, truth


@pytest.fixture(scope="module")
def df(setup):
    blocks, meta, queries, truth = setup
    return measure(blocks, meta, queries, truth, METHODS)


# recall_at_k


def test_recall_is_one_for_the_same_ids():
    assert recall_at_k(np.array([1, 2, 3]), np.array([3, 2, 1])) == 1.0


def test_recall_counts_shared_ids():
    assert recall_at_k(np.array([1, 2, 8, 9]), np.array([1, 2, 3, 4])) == 0.5


def test_recall_is_zero_for_no_shared_ids():
    assert recall_at_k(np.array([5, 6]), np.array([1, 2])) == 0.0


def test_recall_divides_by_the_true_top_k_not_by_what_was_found():
    """A search that finds 1 of the 2 true rows has recall 0.5, even though everything it found is right."""
    assert recall_at_k(np.array([1]), np.array([1, 2])) == 0.5


def test_recall_is_one_when_nothing_matches_the_filter():
    assert recall_at_k(np.array([], dtype=int), np.array([], dtype=int)) == 1.0


# timed


def test_timed_returns_the_result_and_runs_warm_up_plus_repeats():
    calls = []
    result, ms = timed(lambda: calls.append(1) or "done", repeats=3)
    assert result == "done"
    assert len(calls) == 4
    assert ms >= 0


def test_timed_reports_the_median_in_milliseconds(monkeypatch):
    """A fake clock makes the three timed runs take 1 s, 1 s and 10 s: the median is 1,000 ms
    (the mean would be 4,000 ms, pulled up by the one slow run)."""
    import src.metrics
    clock = iter([0.0, 1.0, 1.0, 2.0, 2.0, 12.0])
    monkeypatch.setattr(src.metrics.time, "perf_counter", lambda: next(clock))
    _, ms = timed(lambda: None, repeats=3)
    assert ms == pytest.approx(1_000.0)


# measure


def test_measure_has_one_row_per_query_and_method(df, setup):
    _, _, queries, _ = setup
    assert len(df) == len(queries) * len(METHODS)
    assert set(df["method"]) == set(METHODS)
    expected = {"query", "method", "selectivity", "blocks_touched", "frac_blocks", "rows_read",
                "distances_computed", "recall", "latency_ms", "bucket"}
    assert expected <= set(df.columns)


def test_measure_matches_a_direct_search(df, setup):
    blocks, meta, queries, _ = setup
    for qid, q in enumerate(queries):
        for name, args in METHODS.items():
            res = search_mod.search(blocks, q, meta, k=10, **args)
            row = df[(df["query"] == qid) & (df["method"] == name)].iloc[0]
            assert row["blocks_touched"] == res.blocks_touched
            assert row["rows_read"] == res.rows_read
            assert row["distances_computed"] == res.distances_computed
            assert row["frac_blocks"] == res.blocks_touched / len(blocks)


def test_lossless_methods_have_full_recall(df):
    assert np.all(df.loc[df["method"].isin(["full_scan", "tenant_set"]), "recall"] == 1.0)


def test_scanning_one_block_loses_recall_on_random_layout(df):
    """On the random layout one block holds 1/20 of each tenant, so it cannot hold the whole top-10."""
    one = df[df["method"] == "first_block"]
    assert np.all(one["blocks_touched"] == 1)
    assert one["recall"].mean() < 0.5


def test_full_scan_touches_every_block(df, setup):
    blocks, _, _, _ = setup
    full = df[df["method"] == "full_scan"]
    assert np.all(full["blocks_touched"] == len(blocks))
    assert np.all(full["frac_blocks"] == 1.0)


def test_latency_is_missing_without_repeats_and_present_with_them(df, setup):
    assert df["latency_ms"].isna().all()
    blocks, meta, queries, truth = setup
    timed_df = measure(blocks, meta, queries[:2], truth[:2], {"full_scan": {"pruner": "none"}}, repeats=2)
    assert (timed_df["latency_ms"] > 0).all()


def test_uniform_selectivities_fall_in_the_right_buckets(df):
    """Uniform tenants: 1, 3, 10 and 25 tenants match 1, 3, 10 and 25% of rows."""
    expected = {0.01: "0.5-2%", 0.03: "2-5%", 0.10: "5-15%", 0.25: ">15%"}
    for sel, label in expected.items():
        rows = df[np.isclose(df["selectivity"], sel)]
        assert len(rows) > 0
        assert (rows["bucket"] == label).all()


def test_bucket_edges():
    """Each edge belongs to the lower bucket: 0.5% is '<0.5%', 2% is '0.5-2%'."""
    from src.metrics import BUCKET_EDGES
    sel = pd.Series([0.001, 0.005, 0.006, 0.02, 0.03, 0.05, 0.1, 0.15, 0.5, 1.0])
    got = pd.cut(sel, BUCKET_EDGES, labels=BUCKET_LABELS, include_lowest=True).astype(str).tolist()
    assert got == ["<0.5%", "<0.5%", "0.5-2%", "0.5-2%", "2-5%", "2-5%", "5-15%", "5-15%", ">15%", ">15%"]


# summarize


def test_summarize_groups_by_method_and_bucket(df):
    summary = summarize(df, by=["method"])
    assert summary["queries"].sum() == len(df)
    for _, row in summary.iterrows():
        part = df[(df["method"] == row["method"]) & (df["bucket"] == row["bucket"])]
        assert row["queries"] == len(part)
        assert row["frac_blocks"] == pytest.approx(part["frac_blocks"].mean())
        assert row["recall"] == pytest.approx(part["recall"].mean())
        assert row["invocations"] == pytest.approx(part["blocks_touched"].mean())


def test_summarize_without_grouping_keys_uses_only_buckets(df):
    summary = summarize(df[df["method"] == "full_scan"])
    assert set(summary["bucket"].astype(str)) == set(df["bucket"].astype(str))
