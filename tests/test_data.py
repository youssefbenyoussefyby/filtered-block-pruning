import numpy as np
import pytest

from src.data import make_dataset, make_queries, tenant_sizes

N = 50_000
DIM = 64
NUM_CLUSTERS = 64
NUM_TENANTS = 100
HOMES = 3


@pytest.fixture(scope="module")
def datasets():
    return {rho: make_dataset(n=N, rho=rho) for rho in (0.0, 0.8, 1.0)}


@pytest.fixture(scope="module")
def zipf_ds():
    return make_dataset(n=N, tenant_dist="zipf")


def home_sets(ds_rho1):
    used = np.zeros((ds_rho1.num_tenants, NUM_CLUSTERS), dtype=bool)
    used[ds_rho1.tenant_ids, ds_rho1.cluster_ids] = True
    return used


@pytest.mark.parametrize("dist", ["uniform", "zipf"])
@pytest.mark.parametrize("n", [200_000, 1_003, 100])
def test_tenant_sizes_sum_to_n(dist, n):
    sizes = tenant_sizes(n, NUM_TENANTS, dist)
    assert sizes.shape == (NUM_TENANTS,)
    assert sizes.sum() == n


def test_tenant_sizes_uniform_spreads_remainder():
    sizes = tenant_sizes(1_003, 10, "uniform")
    assert sizes.tolist() == [101] * 3 + [100] * 7


def test_tenant_sizes_zipf_is_skewed_and_decreasing():
    sizes = tenant_sizes(200_000, NUM_TENANTS, "zipf")
    assert np.all(np.diff(sizes) <= 0)
    assert sizes.min() > 0
    assert 0.20 < sizes[0] / sizes.sum() < 0.26
    assert 0.001 < sizes[-1] / sizes.sum() < 0.002


def test_tenant_sizes_rejects_unknown_distribution():
    with pytest.raises(ValueError):
        tenant_sizes(1_000, 10, "pareto")


def test_dataset_shapes_and_dtypes(datasets):
    ds = datasets[0.8]
    assert ds.vectors.shape == (N, DIM)
    assert ds.vectors.dtype == np.float32
    assert ds.tenant_ids.shape == ds.cluster_ids.shape == (N,)
    assert ds.tenant_ids.dtype == ds.cluster_ids.dtype == np.int32
    assert ds.centres.shape == (NUM_CLUSTERS, DIM)
    assert ds.centres.dtype == np.float32
    assert ds.num_tenants == NUM_TENANTS
    assert ds.cluster_ids.min() >= 0 and ds.cluster_ids.max() < NUM_CLUSTERS


@pytest.mark.parametrize("dist", ["uniform", "zipf"])
def test_dataset_tenant_counts_match_tenant_sizes(dist):
    ds = make_dataset(n=N, tenant_dist=dist)
    counts = np.bincount(ds.tenant_ids, minlength=NUM_TENANTS)
    assert np.array_equal(counts, tenant_sizes(N, NUM_TENANTS, dist))


def test_dataset_same_seed_is_identical(datasets):
    again = make_dataset(n=N, rho=0.8)
    ds = datasets[0.8]
    assert np.array_equal(ds.vectors, again.vectors)
    assert np.array_equal(ds.tenant_ids, again.tenant_ids)
    assert np.array_equal(ds.cluster_ids, again.cluster_ids)
    assert np.array_equal(ds.centres, again.centres)


def test_dataset_different_seed_differs(datasets):
    other = make_dataset(n=N, rho=0.8, seed=1)
    assert not np.array_equal(datasets[0.8].vectors, other.vectors)


def test_dataset_rows_are_paired_across_rho(datasets):
    """Draws do not depend on rho: same arrival order, same centres, and a row that
    lands in the same cluster at two values of rho has the same vector."""
    a, b = datasets[0.8], datasets[1.0]
    assert np.array_equal(a.tenant_ids, b.tenant_ids)
    assert np.array_equal(a.centres, b.centres)
    same = a.cluster_ids == b.cluster_ids
    assert same.mean() > 0.8
    assert np.array_equal(a.vectors[same], b.vectors[same])


def test_dataset_rows_arrive_in_random_order(datasets):
    ds = datasets[0.8]
    first_block = ds.tenant_ids[:5_000]
    assert len(np.unique(first_block)) == NUM_TENANTS
    assert np.any(np.diff(ds.tenant_ids) < 0)


def test_vectors_are_centre_plus_gaussian_noise(datasets):
    ds = datasets[0.8]
    residual = ds.vectors - ds.centres[ds.cluster_ids]
    assert abs(residual.mean()) < 0.01
    assert residual.std() == pytest.approx(ds.noise_std, rel=0.01)


def test_rows_are_closest_to_their_own_centre(datasets):
    ds = datasets[0.8]
    sample = slice(0, 2_000)
    dist = np.linalg.norm(ds.vectors[sample, None] - ds.centres[None], axis=2)
    assert np.array_equal(dist.argmin(axis=1), ds.cluster_ids[sample])


def test_rho_one_keeps_each_tenant_in_its_home_clusters(datasets):
    used = home_sets(datasets[1.0])
    assert np.all(used.sum(axis=1) == HOMES)


def test_rho_zero_spreads_each_tenant_over_all_clusters(datasets):
    used = np.zeros((NUM_TENANTS, NUM_CLUSTERS), dtype=bool)
    ds = datasets[0.0]
    used[ds.tenant_ids, ds.cluster_ids] = True
    assert used.sum(axis=1).min() >= NUM_CLUSTERS - 2


@pytest.mark.parametrize("rho", [0.0, 0.8])
def test_share_of_rows_in_home_clusters_matches_rho(datasets, rho):
    homes = home_sets(datasets[1.0])
    ds = datasets[rho]
    in_home = homes[ds.tenant_ids, ds.cluster_ids].mean()
    expected = rho + (1 - rho) * HOMES / NUM_CLUSTERS
    assert in_home == pytest.approx(expected, abs=0.01)


@pytest.fixture(scope="module")
def uniform_queries(datasets):
    return make_queries(datasets[0.8])


def test_queries_count_and_types(uniform_queries):
    assert len(uniform_queries) == 200
    for q in uniform_queries:
        assert q.vector.shape == (DIM,)
        assert q.vector.dtype == np.float32
        assert q.tenants.dtype.kind == "i"


def test_query_tenants_are_sorted_unique_and_valid(uniform_queries):
    for q in uniform_queries:
        assert len(q.tenants) in (1, 3, 10, 25)
        assert np.array_equal(q.tenants, np.unique(q.tenants))
        assert q.tenants.min() >= 0 and q.tenants.max() < NUM_TENANTS


def test_queries_use_every_in_list_size(uniform_queries):
    sizes = {len(q.tenants) for q in uniform_queries}
    assert sizes == {1, 3, 10, 25}


@pytest.mark.parametrize("which", ["uniform", "zipf"])
def test_query_selectivity_is_fraction_of_matching_rows(datasets, zipf_ds, which):
    ds = datasets[0.8] if which == "uniform" else zipf_ds
    for q in make_queries(ds, num_queries=50):
        assert q.selectivity == pytest.approx(np.isin(ds.tenant_ids, q.tenants).mean())


def test_uniform_selectivity_is_in_list_size_over_tenants(uniform_queries):
    for q in uniform_queries:
        assert q.selectivity == pytest.approx(len(q.tenants) / NUM_TENANTS)


def test_query_lands_on_a_cluster_its_tenants_occupy(datasets, uniform_queries):
    ds = datasets[0.8]
    for q in uniform_queries:
        nearest = np.linalg.norm(ds.centres - q.vector, axis=1).argmin()
        clusters = np.unique(ds.cluster_ids[np.isin(ds.tenant_ids, q.tenants)])
        assert nearest in clusters


def test_queries_are_reproducible(datasets, uniform_queries):
    again = make_queries(datasets[0.8])
    for q, r in zip(uniform_queries, again):
        assert np.array_equal(q.vector, r.vector)
        assert np.array_equal(q.tenants, r.tenants)
        assert q.selectivity == r.selectivity
