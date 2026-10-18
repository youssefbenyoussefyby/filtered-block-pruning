from dataclasses import dataclass
from math import dist
from typing import List

import numpy as np

from src.layout import Block
from src.data import Query
from src.metadata import BlockMetadata,lower_bound

@dataclass
class Result:
    row_ids: np.ndarray
    distances: np.ndarray
    blocks_touched: int
    rows_read:int
    distances_computed:int

def all_blocks(query:Query,meta:BlockMetadata):
    return np.arange(meta.num_blocks)

def zonemap(query:Query,meta:BlockMetadata):
    t =query.tenants 
    in_range = (meta.tenant_min[:,None]<=t) & (t<=meta.tenant_max[:,None])
    return np.flatnonzero(in_range.any(axis=1))

def tenant_set(query:Query,meta:BlockMetadata):
    return np.flatnonzero(meta.tenant_set[:,query.tenants].any(axis=1))

def tenant_set_centroid(query:Query,meta:BlockMetadata):
    ids = tenant_set(query,meta)
    dist = np.linalg.norm(meta.centroids[ids]-query.vector,axis=1)
    return ids[np.argsort(dist,kind="stable")]

def tenant_set_by_bound(query:Query,meta:BlockMetadata):
    ids = tenant_set(query,meta)
    return ids[np.argsort(lower_bound(meta, query.vector)[ids],kind="stable")]

PRUNERS = {
    "none": all_blocks,
    "zonemap": zonemap,
    "tenant_set": tenant_set,
    "tenant_set_by_centroid": tenant_set_centroid,
    "tenant_set_by_bound": tenant_set_by_bound,
}

def search_block(block:Block,query:Query,k:int):
    mask = np.isin(block.tenant_ids, query.tenants)
    rows = block.row_ids[mask]
    dist = dist = ((block.vectors[mask] - query.vector)**2).sum(axis=1)
    top = np.lexsort((rows, dist))[:k]
    return dist[top],block.row_ids[mask][top],len(rows)

def search(blocks:List[Block],query:Query,meta:BlockMetadata,pruner:str,k:int,max_blocks:int = None , early_stop:bool = False):
    block_ids = PRUNERS[pruner](query,meta)[:max_blocks]
    bounds  = lower_bound(meta,query.vector) ** 2 if early_stop else None
    best_dist = np.empty(0,dtype=np.float32)
    best_ids = np.empty(0,dtype=np.int64)
    touched = rows_read = computed = 0
    for b in block_ids:
        if early_stop and len(best_dist) >= k and bounds[b] >= best_dist[-1] *(1+1e-6):
            continue
        dist , ids , n = search_block(blocks[b],query,k)
        touched += 1
        rows_read += len(blocks[b].row_ids)
        computed += n
        best_dist = np.concatenate([best_dist,dist])
        best_ids = np.concatenate([best_ids,ids])
        keep = np.lexsort((best_ids, best_dist))[:k] 
        best_dist = best_dist[keep]
        best_ids = best_ids[keep]   
    return Result(best_ids,best_dist,touched,rows_read,computed)

