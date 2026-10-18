import numpy as np
import pytest

import src.metadata as metadata
from src.data import make_dataset, make_queries
from src.layout import LAYOUTS, build_blocks
from src.metadata import build_metadata, bytes_per_block

N = 20_000
SIZE = 1_000
NUM_TENANTS = 100
DIM = 64


@pytest.fixture(scope="module")
def ds():
    return make_dataset(n=N)


@pytest.fixture(scope="module", params=sorted(LAYOUTS))
def blocks_and_meta(request, ds):
    blocks, _ = build_blocks(ds, request.param, SIZE)
    return request.param, blocks, build_metadata(blocks, NUM_TENANTS)


def lower_bound(meta, q):
    return metadata.lower_bound(meta, q)




def test_metadata_shapes(blocks_and_meta):
    _, blocks, meta = blocks_and_meta
    nb = len(blocks)
    assert meta.num_blocks == nb
    assert meta.tenant_min.shape == meta.tenant_max.shape == meta.radii.shape == (nb,)
    assert meta.tenant_set.shape == (nb, NUM_TENANTS)
    assert meta.tenant_set.dtype == bool
    assert meta.centroids.shape == (nb, DIM)




def test_zonemap_is_min_and_max_tenant_of_each_block(blocks_and_meta):
    _, blocks, meta = blocks_and_meta
    for i, b in enumerate(blocks):
        assert meta.tenant_min[i] == b.tenant_ids.min()
        assert meta.tenant_max[i] == b.tenant_ids.max()


def test_zonemap_never_excludes_a_tenant_the_block_holds(blocks_and_meta):
    _, blocks, meta = blocks_and_meta
    for i, b in enumerate(blocks):
        assert np.all((meta.tenant_min[i] <= b.tenant_ids) & (b.tenant_ids <= meta.tenant_max[i]))


def test_zonemap_ranges_follow_each_other_on_tenant_sorted(ds):
    blocks, _ = build_blocks(ds, "tenant_sorted", SIZE)
    meta = build_metadata(blocks, NUM_TENANTS)
    assert np.all(meta.tenant_min[1:] >= meta.tenant_max[:-1])




def test_tenant_set_is_exactly_the_tenants_in_each_block(blocks_and_meta):
    _, blocks, meta = blocks_and_meta
    for i, b in enumerate(blocks):
        assert np.array_equal(np.flatnonzero(meta.tenant_set[i]), np.unique(b.tenant_ids))




def test_centroid_is_mean_of_block(blocks_and_meta):
    _, blocks, meta = blocks_and_meta
    for i, b in enumerate(blocks):
        assert np.allclose(meta.centroids[i], b.vectors.mean(axis=0, dtype=np.float64), atol=1e-5)


def test_radius_is_distance_to_farthest_row(blocks_and_meta):
    _, blocks, meta = blocks_and_meta
    for i, b in enumerate(blocks):
        dist = np.linalg.norm(b.vectors.astype(np.float64) - meta.centroids[i], axis=1)
        assert np.all(dist <= meta.radii[i] + 1e-6)
        assert dist.max() == pytest.approx(meta.radii[i], rel=1e-6)




def test_lower_bound_never_exceeds_true_nearest_distance(ds, blocks_and_meta):
    _, blocks, meta = blocks_and_meta
    rng = np.random.default_rng(0)
    queries = [q.vector for q in make_queries(ds, num_queries=30)]
    queries += list(rng.normal(0, 3, (10, DIM)).astype(np.float32))  # queries far from any cluster
    for q in queries:
        lb = lower_bound(meta, q)
        for i, b in enumerate(blocks):
            nearest = np.linalg.norm(b.vectors.astype(np.float64) - q, axis=1).min()
            assert lb[i] <= nearest + 1e-6


def test_lower_bound_shape_and_sign(ds, blocks_and_meta):
    _, _, meta = blocks_and_meta
    lb = lower_bound(meta, make_queries(ds, num_queries=1)[0].vector)
    assert lb.shape == (meta.num_blocks,)
    assert np.all(lb >= 0)


def test_lower_bound_is_zero_at_the_centroid(blocks_and_meta):
    _, _, meta = blocks_and_meta
    assert lower_bound(meta, meta.centroids[0])[0] == 0


def test_lower_bound_is_exact_far_away(blocks_and_meta):
    _, _, meta = blocks_and_meta
    q = meta.centroids[0] + 1_000.0
    expected = np.linalg.norm(meta.centroids[0] - q) - meta.radii[0]
    assert lower_bound(meta, q)[0] == pytest.approx(expected)




def test_bytes_per_block_matches_the_notes():
    assert bytes_per_block(NUM_TENANTS, DIM) == {"zonemap": 8, "tenant_set": 13, "centroid_radius": 520}


def test_reported_centroid_size_matches_what_is_stored(blocks_and_meta):
    _, _, meta = blocks_and_meta
    stored = meta.centroids[0].nbytes + meta.radii[:1].nbytes
    assert stored == bytes_per_block(NUM_TENANTS, DIM)["centroid_radius"]


def test_build_metadata_does_not_change_blocks(ds):
    blocks, _ = build_blocks(ds, "random", SIZE)
    before = [(b.vectors.copy(), b.tenant_ids.copy()) for b in blocks]
    build_metadata(blocks, NUM_TENANTS)
    for b, (v, t) in zip(blocks, before):
        assert np.array_equal(b.vectors, v) and np.array_equal(b.tenant_ids, t)
