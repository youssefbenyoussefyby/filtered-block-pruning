import numpy as np
import pytest

import src.search as search_mod
from src.data import Query, make_dataset, make_queries
from src.layout import LAYOUTS, Block, build_blocks
from src.metadata import build_metadata, lower_bound
from src.search import PRUNERS

N = 20_000
SIZE = 1_000
NUM_TENANTS = 100
K = 10


def search(blocks, query, meta, pruner, k=K, max_blocks=None, early_stop=False):
    return search_mod.search(blocks, query, meta, pruner, k, max_blocks=max_blocks, early_stop=early_stop)


def brute_force(ds, query, k=K, rows=None):
    ids = np.arange(len(ds.tenant_ids)) if rows is None else np.asarray(rows)
    ids = ids[np.isin(ds.tenant_ids[ids], query.tenants)]
    dist = ((ds.vectors[ids] - query.vector) ** 2).sum(axis=1)
    order = np.lexsort((ids, dist))[:k]
    return ids[order], dist[order]


@pytest.fixture(scope="module")
def ds():
    return make_dataset(n=N, rho=0.8)


@pytest.fixture(scope="module")
def queries(ds):
    return make_queries(ds, num_queries=30)


@pytest.fixture(scope="module", params=sorted(LAYOUTS))
def setup(request, ds):
    blocks, _ = build_blocks(ds, request.param, SIZE)
    return request.param, blocks, build_metadata(blocks, NUM_TENANTS)


def blocks_with_matches(blocks, query):
    return {i for i, b in enumerate(blocks) if np.isin(b.tenant_ids, query.tenants).any()}




def test_all_pruners_exist():
    assert set(PRUNERS) == {"none", "zonemap", "tenant_set", "tenant_set_by_centroid", "tenant_set_by_bound"}


def test_full_scan_equals_brute_force(ds, queries, setup):
    _, blocks, meta = setup
    for q in queries:
        res = search(blocks, q, meta, "none")
        ids, dist = brute_force(ds, q)
        assert np.array_equal(res.rows_ids, ids)
        assert np.allclose(res.distances, dist)


def test_full_scan_touches_every_block(queries, setup):
    _, blocks, meta = setup
    res = search(blocks, queries[0], meta, "none")
    assert res.block_touch_count == len(blocks)
    assert res.row_read == N


def test_results_are_sorted_and_have_k_rows(queries, setup):
    _, blocks, meta = setup
    for q in queries:
        res = search(blocks, q, meta, "none")
        assert len(res.rows_ids) == len(res.distances) == K
        assert np.all(np.diff(res.distances) >= 0)


def test_fewer_matches_than_k_returns_all_matches(ds, setup):
    _, blocks, meta = setup
    tenant = 7
    rows = np.flatnonzero(ds.tenant_ids == tenant)
    q = Query(ds.vectors[0], np.array([tenant]), len(rows) / N)
    res = search(blocks, q, meta, "tenant_set", k=len(rows) + 50)
    assert np.array_equal(np.sort(res.rows_ids), rows)




@pytest.mark.parametrize("pruner", sorted(PRUNERS))
def test_every_pruner_returns_the_exact_top_k(queries, setup, pruner):
    _, blocks, meta = setup
    for q in queries:
        exact = search(blocks, q, meta, "none")
        res = search(blocks, q, meta, pruner)
        assert np.array_equal(res.rows_ids, exact.rows_ids)


@pytest.mark.parametrize("pruner", sorted(PRUNERS))
def test_early_stop_returns_the_exact_top_k(queries, setup, pruner):
    _, blocks, meta = setup
    for q in queries:
        exact = search(blocks, q, meta, "none")
        res = search(blocks, q, meta, pruner, early_stop=True)
        assert np.array_equal(res.rows_ids, exact.rows_ids)
        assert res.block_touch_count <= search(blocks, q, meta, pruner).block_touch_count


@pytest.mark.parametrize("pruner", ["tenant_set_by_centroid", "tenant_set_by_bound"])
def test_early_stop_is_exact_when_it_really_skips_blocks(pruner):
    data = make_dataset(n=N, num_clusters=N // SIZE, noise_std=0.1)
    blocks, _ = build_blocks(data, "vector_clustered", SIZE)
    meta = build_metadata(blocks, NUM_TENANTS)
    skipped = 0
    for q in make_queries(data, num_queries=30):
        exact = search(blocks, q, meta, "none")
        res = search(blocks, q, meta, pruner, early_stop=True)
        assert np.array_equal(res.rows_ids, exact.rows_ids)
        skipped += search(blocks, q, meta, pruner).block_touch_count - res.block_touch_count
    assert skipped > 0


def line_blocks(*groups):
    blocks, next_id = [], 0
    for values in groups:
        ids = np.arange(next_id, next_id + len(values))
        next_id += len(values)
        blocks.append(Block(ids, np.array(values, dtype=np.float32)[:, None], np.zeros(len(values), dtype=np.int32)))
    return blocks, build_metadata(blocks, 1)


@pytest.mark.parametrize("pruner", sorted(PRUNERS))
def test_early_stop_scans_a_block_whose_bound_is_below_the_kth_distance(pruner):
    blocks, meta = line_blocks([1.0, 3.0], [2.8, 2.9], [3.5, 3.6])
    q = Query(np.zeros(1, dtype=np.float32), np.array([0]), 1.0)
    res = search(blocks, q, meta, pruner, k=2, early_stop=True)
    assert res.rows_ids.tolist() == [0, 2]
    assert res.block_touch_count == 2


@pytest.mark.parametrize("pruner", sorted(PRUNERS))
def test_early_stop_waits_until_it_has_k_results(pruner):
    blocks, meta = line_blocks([1.0], [2.8, 2.9])
    q = Query(np.zeros(1, dtype=np.float32), np.array([0]), 1.0)
    res = search(blocks, q, meta, pruner, k=2, early_stop=True)
    assert res.rows_ids.tolist() == [0, 1]


@pytest.mark.parametrize("pruner", ["zonemap", "tenant_set", "tenant_set_by_centroid", "tenant_set_by_bound"])
def test_pruner_never_drops_a_block_with_a_matching_row(queries, setup, pruner):
    _, blocks, meta = setup
    for q in queries:
        assert blocks_with_matches(blocks, q) <= set(PRUNERS[pruner](q, meta).tolist())


def test_tenant_set_keeps_exactly_the_blocks_with_matches(queries, setup):
    _, blocks, meta = setup
    for q in queries:
        assert set(PRUNERS["tenant_set"](q, meta).tolist()) == blocks_with_matches(blocks, q)


def test_zonemap_is_exact_on_tenant_sorted(ds, queries):
    blocks, _ = build_blocks(ds, "tenant_sorted", SIZE)
    meta = build_metadata(blocks, NUM_TENANTS)
    single = [q for q in queries if len(q.tenants) == 1]
    assert single
    for q in single:
        assert set(PRUNERS["zonemap"](q, meta).tolist()) == blocks_with_matches(blocks, q)




def test_centroid_order_is_by_distance_to_centroid(queries, setup):
    _, _, meta = setup
    for q in queries:
        ids = PRUNERS["tenant_set_by_centroid"](q, meta)
        d = np.linalg.norm(meta.centroids[ids] - q.vector, axis=1)
        assert np.all(np.diff(d) >= 0)
        assert set(ids.tolist()) == set(PRUNERS["tenant_set"](q, meta).tolist())


def test_bound_order_is_by_lower_bound(queries, setup):
    _, _, meta = setup
    for q in queries:
        ids = PRUNERS["tenant_set_by_bound"](q, meta)
        assert np.all(np.diff(lower_bound(meta, q.vector)[ids]) >= 0)
        assert set(ids.tolist()) == set(PRUNERS["tenant_set"](q, meta).tolist())




@pytest.mark.parametrize("m", [1, 3, 8])
def test_max_blocks_scans_only_the_first_m_blocks(ds, queries, setup, m):
    _, blocks, meta = setup
    for q in queries:
        order = PRUNERS["tenant_set_by_centroid"](q, meta)
        res = search(blocks, q, meta, "tenant_set_by_centroid", max_blocks=m)
        assert res.block_touch_count == min(m, len(order))
        rows = np.concatenate([blocks[b].row_ids for b in order[:m]])
        ids, _ = brute_force(ds, q, rows=rows)
        assert np.array_equal(res.rows_ids, ids)


def test_max_blocks_larger_than_needed_is_exact(queries, setup):
    _, blocks, meta = setup
    for q in queries:
        exact = search(blocks, q, meta, "none")
        res = search(blocks, q, meta, "tenant_set_by_centroid", max_blocks=len(blocks))
        assert np.array_equal(res.rows_ids, exact.rows_ids)




@pytest.mark.parametrize("pruner", sorted(PRUNERS))
def test_counters_match_the_blocks_scanned(queries, setup, pruner):
    _, blocks, meta = setup
    for q in queries:
        res = search(blocks, q, meta, pruner)
        scanned = PRUNERS[pruner](q, meta)
        assert res.block_touch_count == len(scanned)
        assert res.row_read == sum(len(blocks[b].row_ids) for b in scanned)
        assert res.distances_computed == sum(int(np.isin(blocks[b].tenant_ids, q.tenants).sum()) for b in scanned)




def test_ties_are_broken_by_row_id():
    vec = np.zeros((6, 2), dtype=np.float32)
    tenants = np.zeros(6, dtype=np.int32)
    order = np.array([5, 4, 3, 2, 1, 0])  
    blocks = [Block(order[i:i + 2], vec[order[i:i + 2]], tenants[order[i:i + 2]]) for i in range(0, 6, 2)]
    meta = build_metadata(blocks, 1)
    q = Query(np.ones(2, dtype=np.float32), np.array([0]), 1.0)
    for pruner in PRUNERS:
        for early_stop in (False, True):
            res = search(blocks, q, meta, pruner, k=2, early_stop=early_stop)
            assert sorted(res.rows_ids.tolist()) == [0, 1], (pruner, early_stop)
