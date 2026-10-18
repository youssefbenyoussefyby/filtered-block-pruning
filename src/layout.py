import time 
from dataclasses import dataclass
from src.data import Dataset
import numpy as np
from sklearn.cluster import MiniBatchKMeans


@dataclass
class Block:
    row_ids: np.ndarray
    vectors: np.ndarray
    tenant_ids: np.ndarray

def random_order(ds:Block,size:int,seed:int=0):
    return np.random.default_rng(seed).permutation(len(ds.tenant_ids))

def tenant_sorted_order(ds:Block,size:int,seed:int=0):
    return np.argsort(ds.tenant_ids,kind="stable")

def vector_clustered_order(ds:Block,size:int,seed:int=0):
    num_clusters = max(1,len(ds.vectors)//size)
    kmeans = MiniBatchKMeans(n_clusters=num_clusters, batch_size=4096 , n_init=3, random_state=seed)
    labels = kmeans.fit_predict(ds.vectors)
    return np.argsort(labels,kind="stable")

LAYOUTS = {
    "random": random_order,
    "tenant_sorted": tenant_sorted_order,
    "vector_clustered": vector_clustered_order,
}

def build_blocks(ds:Dataset,layout:str,size:int,seed:int=0):
    start = time.perf_counter()
    order = LAYOUTS[layout](ds, size,seed)
    blocks = []
    for lo in range(0, len(order), size):
        rows = order[lo:lo + size]
        blocks.append(Block(rows, np.ascontiguousarray(ds.vectors[rows]), ds.tenant_ids[rows]))
    return blocks, time.perf_counter() - start
