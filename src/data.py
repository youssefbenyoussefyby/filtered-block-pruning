from dataclasses import dataclass

import numpy as np


@dataclass
class Dataset:
    vectors: np.ndarray  
    tenant_ids: np.ndarray   
    cluster_ids: np.ndarray  
    centres: np.ndarray      
    num_tenants: int
    noise_std: float


@dataclass
class Query:
    vector: np.ndarray   
    tenants: np.ndarray  
    selectivity: float   


def tenant_sizes(n, num_tenants, dist="uniform", zipf_s=1.1):
    if dist == "uniform":
        weights = np.ones(num_tenants)
    elif dist == "zipf":
        weights = 1.0 / np.arange(1, num_tenants + 1) ** zipf_s
    else:
        raise ValueError(f"unknown tenant distribution {dist!r}")
    sizes = np.floor(weights / weights.sum() * n).astype(np.int64)
    sizes[: n - sizes.sum()] += 1
    return sizes


def make_dataset(n=200_000, dim=64, num_clusters=64, num_tenants=100, tenant_dist="uniform",zipf_s=1.1, rho=0.8, home_clusters_per_tenant=3,centre_std=1.0, noise_std=0.5, seed=0):
    rng = np.random.default_rng(seed)
    centres = rng.normal(0.0, centre_std, (num_clusters, dim)).astype(np.float32)
    sizes = tenant_sizes(n, num_tenants, tenant_dist, zipf_s)
    tenant_ids = np.repeat(np.arange(num_tenants, dtype=np.int32), sizes)
    homes = np.stack([rng.choice(num_clusters, home_clusters_per_tenant, replace=False) for _ in range(num_tenants)])
    home_pick = homes[tenant_ids, rng.integers(0, home_clusters_per_tenant, n)]
    any_pick = rng.integers(0, num_clusters, n)
    cluster_ids = np.where(rng.random(n) < rho, home_pick, any_pick).astype(np.int32)

    vectors = centres[cluster_ids] + noise_std * rng.standard_normal((n, dim), dtype=np.float32)

    arrival = rng.permutation(n)
    return Dataset(vectors[arrival], tenant_ids[arrival], cluster_ids[arrival],centres, num_tenants, noise_std)


def make_queries(ds, num_queries=200, in_list_sizes=(1, 3, 10, 25), seed=1):
    rng = np.random.default_rng(seed)
    sizes = np.bincount(ds.tenant_ids, minlength=ds.num_tenants)
    dim = ds.vectors.shape[1]
    queries = []
    for _ in range(num_queries):
        tenants = np.sort(rng.choice(ds.num_tenants, rng.choice(in_list_sizes), replace=False))
        matching = np.flatnonzero(np.isin(ds.tenant_ids, tenants))
        cluster = ds.cluster_ids[rng.choice(matching)]
        vector = ds.centres[cluster] + ds.noise_std * rng.standard_normal(dim, dtype=np.float32)
        queries.append(Query(vector, tenants, sizes[tenants].sum() / len(ds.tenant_ids)))
    return queries
