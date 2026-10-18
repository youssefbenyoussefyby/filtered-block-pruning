## Zipf tenants, rho = 0.8 unless noted (E1/E2 + E3 at m = 2)

| layout | metric | <0.5% | 0.5-2% | 2-5% | 5-15% | >15% |
|---|---|---|---|---|---|---|
| random | blocks scanned, zonemap | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| | blocks scanned, tenant_set | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| | p50 blocks ratio full / touched, tenant_set | 1.0× | 1.0× | 1.0× | 1.0× | 1.0× |
| | p50 latency speedup, tenant_set | 1.0× | 1.0× | 1.0× | 1.0× | 1.0× |
| | recall@10, 2 nearest surviving blocks | 0.07 | 0.06 | 0.04 | 0.05 | 0.05 |
| tenant_sorted | blocks scanned, zonemap | 0.03 | 0.06 | 0.14 | 0.28 | 0.52 |
| | blocks scanned, tenant_set | 0.03 | 0.06 | 0.14 | 0.28 | 0.52 |
| | p50 blocks ratio full / touched, tenant_set | 40.0× | 13.3× | 6.7× | 3.6× | 2.0× |
| | p50 latency speedup, tenant_set | 10.6× | 3.6× | 1.7× | 1.2× | 1.1× |
| | recall@10, 2 nearest surviving blocks | 1.00 | 0.95 | 0.72 | 0.53 | 0.38 |
| vector_clustered | blocks scanned, zonemap | 0.98 | 1.00 | 1.00 | 1.00 | 1.00 |
| | blocks scanned, tenant_set | 0.79 | 0.98 | 1.00 | 1.00 | 1.00 |
| | p50 blocks ratio full / touched, tenant_set | 1.2× | 1.0× | 1.0× | 1.0× | 1.0× |
| | p50 latency speedup, tenant_set | 1.2× | 1.0× | 1.0× | 1.0× | 1.0× |
| | recall@10, 2 nearest surviving blocks | 0.83 | 0.81 | 0.93 | 0.92 | 0.86 |
| vector_clustered (rho=1) | blocks scanned, zonemap | 0.90 | 0.99 | 0.97 | 1.00 | 0.98 |
| | blocks scanned, tenant_set | 0.15 | 0.28 | 0.47 | 0.71 | 0.86 |
| | p50 blocks ratio full / touched, tenant_set | 6.7× | 3.3× | 1.9× | 1.4× | 1.1× |
| | p50 latency speedup, tenant_set | 3.4× | 1.9× | 1.3× | 1.1× | 1.0× |

Attribute pruning (zonemap, tenant_set) recall@10: min 1.00 over all cells.

## Full E1/E2 table

| tenants | layout | selectivity | queries | scanned (zonemap) | scanned (tenant_set) | recall@10 | p50 latency speedup (tenant_set) | p50 blocks ratio full / touched (tenant_set) |
|---|---|---|---|---|---|---|---|---|
| uniform | random | 0.5-2% | 48 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| uniform | random | 2-5% | 47 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| uniform | random | 5-15% | 52 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| uniform | random | >15% | 53 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| uniform | tenant_sorted | 0.5-2% | 48 | 0.03 | 0.03 | 1.00 | 4.3× | 40.0× |
| uniform | tenant_sorted | 2-5% | 47 | 0.08 | 0.08 | 1.00 | 2.2× | 13.3× |
| uniform | tenant_sorted | 5-15% | 52 | 0.28 | 0.28 | 1.00 | 1.4× | 3.6× |
| uniform | tenant_sorted | >15% | 53 | 0.58 | 0.58 | 1.00 | 1.1× | 1.7× |
| uniform | vector_clustered | 0.5-2% | 48 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| uniform | vector_clustered | 2-5% | 47 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| uniform | vector_clustered | 5-15% | 52 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| uniform | vector_clustered | >15% | 53 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| uniform | vector_clustered (rho=1) | 0.5-2% | 48 | 0.88 | 0.17 | 1.00 | 2.2× | 6.2× |
| uniform | vector_clustered (rho=1) | 2-5% | 47 | 1.00 | 0.40 | 1.00 | 1.7× | 2.5× |
| uniform | vector_clustered (rho=1) | 5-15% | 52 | 1.00 | 0.82 | 1.00 | 1.1× | 1.2× |
| uniform | vector_clustered (rho=1) | >15% | 53 | 1.00 | 0.99 | 1.00 | 1.0× | 1.0× |
| zipf | random | <0.5% | 30 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| zipf | random | 0.5-2% | 46 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| zipf | random | 2-5% | 29 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| zipf | random | 5-15% | 49 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| zipf | random | >15% | 46 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| zipf | tenant_sorted | <0.5% | 30 | 0.03 | 0.03 | 1.00 | 10.6× | 40.0× |
| zipf | tenant_sorted | 0.5-2% | 46 | 0.06 | 0.06 | 1.00 | 3.6× | 13.3× |
| zipf | tenant_sorted | 2-5% | 29 | 0.14 | 0.14 | 1.00 | 1.7× | 6.7× |
| zipf | tenant_sorted | 5-15% | 49 | 0.28 | 0.28 | 1.00 | 1.2× | 3.6× |
| zipf | tenant_sorted | >15% | 46 | 0.52 | 0.52 | 1.00 | 1.1× | 2.0× |
| zipf | vector_clustered | <0.5% | 30 | 0.98 | 0.79 | 1.00 | 1.2× | 1.2× |
| zipf | vector_clustered | 0.5-2% | 46 | 1.00 | 0.98 | 1.00 | 1.0× | 1.0× |
| zipf | vector_clustered | 2-5% | 29 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| zipf | vector_clustered | 5-15% | 49 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| zipf | vector_clustered | >15% | 46 | 1.00 | 1.00 | 1.00 | 1.0× | 1.0× |
| zipf | vector_clustered (rho=1) | <0.5% | 30 | 0.90 | 0.15 | 1.00 | 3.4× | 6.7× |
| zipf | vector_clustered (rho=1) | 0.5-2% | 46 | 0.99 | 0.28 | 1.00 | 1.9× | 3.3× |
| zipf | vector_clustered (rho=1) | 2-5% | 29 | 0.97 | 0.47 | 1.00 | 1.3× | 1.9× |
| zipf | vector_clustered (rho=1) | 5-15% | 49 | 1.00 | 0.71 | 1.00 | 1.1× | 1.4× |
| zipf | vector_clustered (rho=1) | >15% | 46 | 0.98 | 0.86 | 1.00 | 1.0× | 1.1× |
