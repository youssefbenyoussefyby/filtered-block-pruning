import numpy as np
import pytest

from src.data import make_dataset
from src.layout import LAYOUTS, build_blocks

N = 20_000
SIZE = 1_000


@pytest.fixture(scope="module")
def ds():
    return make_dataset(n=N, rho=0.8)


@pytest.fixture(scope="module")
def built(ds):
    return {layout: build_blocks(ds, layout, SIZE)[0] for layout in LAYOUTS}


def all_row_ids(blocks):
    return np.concatenate([b.row_ids for b in blocks])


def mean_spread(blocks):
    return np.mean([np.linalg.norm(b.vectors - b.vectors.mean(axis=0), axis=1).mean() for b in blocks])


def main_cluster_share(ds, blocks):
    return np.mean([np.bincount(ds.cluster_ids[b.row_ids]).max() / len(b.row_ids) for b in blocks])




def test_all_three_layouts_exist():
    assert set(LAYOUTS) == {"random", "tenant_sorted", "vector_clustered"}


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_every_row_is_in_exactly_one_block(ds, built, layout):
    assert np.array_equal(np.sort(all_row_ids(built[layout])), np.arange(N))


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_blocks_have_fixed_size(built, layout):
    blocks = built[layout]
    assert len(blocks) == N // SIZE
    assert all(len(b.row_ids) == SIZE for b in blocks)


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_block_data_matches_the_dataset(ds, built, layout):
    for b in built[layout]:
        assert np.array_equal(b.vectors, ds.vectors[b.row_ids])
        assert np.array_equal(b.tenant_ids, ds.tenant_ids[b.row_ids])
        assert len(b.vectors) == len(b.tenant_ids) == len(b.row_ids)


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_last_block_is_smaller_when_n_is_not_a_multiple(layout):
    small = make_dataset(n=2_500)
    blocks, _ = build_blocks(small, layout, SIZE)
    assert [len(b.row_ids) for b in blocks] == [1_000, 1_000, 500]
    assert np.array_equal(np.sort(all_row_ids(blocks)), np.arange(2_500))


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_same_seed_gives_same_blocks(ds, built, layout):
    again, _ = build_blocks(ds, layout, SIZE)
    for a, b in zip(built[layout], again):
        assert np.array_equal(a.row_ids, b.row_ids)


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_build_does_not_change_the_dataset(layout):
    small = make_dataset(n=5_000)
    before = (small.vectors.copy(), small.tenant_ids.copy(), small.cluster_ids.copy())
    build_blocks(small, layout, SIZE)
    assert np.array_equal(small.vectors, before[0])
    assert np.array_equal(small.tenant_ids, before[1])
    assert np.array_equal(small.cluster_ids, before[2])


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_build_does_not_touch_numpy_global_random_state(ds, layout):
    np.random.seed(12345)
    expected = np.random.random()
    np.random.seed(12345)
    build_blocks(ds, layout, SIZE)
    assert np.random.random() == expected


def test_build_returns_build_time(ds):
    _, seconds = build_blocks(ds, "tenant_sorted", SIZE)
    assert seconds >= 0


def test_unknown_layout_raises(ds):
    with pytest.raises(KeyError):
        build_blocks(ds, "by_magic", SIZE)




def test_random_blocks_hold_every_tenant(built):
    for b in built["random"]:
        assert len(np.unique(b.tenant_ids)) == 100




def test_tenant_sorted_rows_are_in_tenant_order(built):
    tenant_ids = np.concatenate([b.tenant_ids for b in built["tenant_sorted"]])
    assert np.all(np.diff(tenant_ids) >= 0)


def test_tenant_sorted_is_stable(ds, built):
    row_ids = all_row_ids(built["tenant_sorted"])
    tenant_ids = ds.tenant_ids[row_ids]
    for t in np.unique(tenant_ids):
        assert np.all(np.diff(row_ids[tenant_ids == t]) > 0)


@pytest.mark.parametrize("dist", ["uniform", "zipf"])
def test_tenant_sorted_tenant_spans_as_few_blocks_as_possible(dist):
    data = make_dataset(n=N, tenant_dist=dist)
    blocks, _ = build_blocks(data, "tenant_sorted", SIZE)
    sizes = np.bincount(data.tenant_ids, minlength=data.num_tenants)
    for t in range(data.num_tenants):
        spanned = sum(t in b.tenant_ids for b in blocks)
        ideal = -(-sizes[t] // SIZE)
        assert ideal <= spanned <= ideal + 1




def test_vector_clustered_groups_true_clusters():
    data = make_dataset(n=N, num_clusters=N // SIZE)
    blocks, _ = build_blocks(data, "vector_clustered", SIZE)
    assert main_cluster_share(data, blocks) > 0.8


def test_vector_clustered_blocks_are_tighter_than_random():
    data = make_dataset(n=N, num_clusters=N // SIZE)
    clustered, _ = build_blocks(data, "vector_clustered", SIZE)
    shuffled, _ = build_blocks(data, "random", SIZE)
    assert mean_spread(clustered) < 0.75 * mean_spread(shuffled)


def test_vector_clustered_has_fewer_tenants_per_block_when_rho_is_one():
    data = make_dataset(n=N, rho=1.0)
    clustered, _ = build_blocks(data, "vector_clustered", SIZE)
    shuffled, _ = build_blocks(data, "random", SIZE)
    per_block = lambda blocks: np.median([len(np.unique(b.tenant_ids)) for b in blocks])
    assert per_block(clustered) < 0.5 * per_block(shuffled)


def test_vector_clustered_works_when_block_is_larger_than_data():
    small = make_dataset(n=500)
    blocks, _ = build_blocks(small, "vector_clustered", SIZE)
    assert len(blocks) == 1 and len(blocks[0].row_ids) == 500
