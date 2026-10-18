from typing import List
from dataclasses import dataclass

import numpy as np

from src.layout import Block


@dataclass
class BlockMetadata:
    tenant_min: np.ndarray
    tenant_max: np.ndarray
    tenant_set:np.ndarray
    centroids: np.ndarray
    radii: np.ndarray
    @property
    def num_blocks(self):
        return len(self.radii)

def build_metadata(blocks:List[Block],num_tenants:int):
    tenant_set = np.zeros((len(blocks),num_tenants),dtype=bool)
    for d, block in enumerate(blocks):
        tenant_set[d,block.tenant_ids] = True
    centroids = np.array([b.vectors.mean(axis=0,dtype=np.float64) for b in blocks])
    radii = np.array([np.linalg.norm(b.vectors - centroids[d],axis=1).max() for d,b in enumerate(blocks)])
    return BlockMetadata( 
        tenant_min = np.array([b.tenant_ids.min() for b in blocks]),
        tenant_max = np.array([b.tenant_ids.max() for b in blocks]),
        tenant_set = tenant_set,
        centroids = centroids,
        radii = radii
    )

def lower_bound(metadata:BlockMetadata,query_vector:np.ndarray):
    return np.maximum(0.0, np.linalg.norm(metadata.centroids - query_vector, axis=1) - metadata.radii)


def bytes_per_block(num_tenants:int,dim:int):
    return {
        "zonemap" : 8,
        "tenant_set" : (num_tenants + 7) // 8,
        "centroid_radius" :  (dim+1)* 8,
    }