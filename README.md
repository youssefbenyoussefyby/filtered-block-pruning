# filtered-block-pruning

A small prototype that measures **block pruning for tenant-filtered vector search**. Given a
query vector and a filter `tenant_id IN (...)`, it returns the 10 nearest rows (L2) among the rows
that match, while touching as few fixed-size blocks as possible.

Each block touched stands for one fetch and one function invocation in a serverless vector
database, so **blocks touched** is the main cost metric. Recall@10 is measured against an exact
full scan. Everything is synthetic, in memory and single-threaded.

The full working log is in [NOTES.md](NOTES.md). It has the hypotheses with predictions written
before each run, the design decisions, and every result and surprise.

## Results in one minute

Setup: 200,000 rows of 64 dimensions, 100 tenants, blocks of 5,000 rows (40 blocks), and 200
queries per configuration.

- **The layout decides whether attribute pruning works.**
  - The same exact metadata prunes nothing on a `random` layout: 100% of blocks are scanned for
    every filter.
  - On `tenant_sorted` it scans 2.9% / 8.2% / 27.6% / 58.5% of blocks for 1 / 3 / 10 / 25 tenants.
    That is 2.3–2.9 times the selectivity, because a block holds about 3 tenants and the tenants
    in an IN-list rarely share one.
  - On `tenant_sorted` the 8-byte zone map is exactly as good as the exact tenant set.
  - Recall is 1.00 everywhere.
- **Filter locality and similarity locality conflict.**
  - `vector_clustered` prunes almost nothing by tenant when tenants are only loosely tied to
    clusters (`rho` = 0.8). It scans 17% of blocks for one tenant even when every row is in its
    tenant's home clusters (`rho` = 1.0).
  - But ranking its blocks by centroid finds 90% of the true top-10 after 3–4 blocks (7.5–10%).
  - `tenant_sorted` needs 13–17% of blocks for the same recall and is exact at 23%.
  - `random` gives no trade-off at all: recall ≈ fraction of blocks scanned.
- **In memory, latency hides most of the saving.** 40 times fewer blocks gives only 4.3–10.6
  times lower latency. Skipping a block saves about 0.06 ms. Most of the time is distance work
  on matching rows, which every lossless method does.
- **The recall curve has a long tail.** On `vector_clustered`, recall reaches 0.9 after 3 blocks
  but only 0.98 after 24.
- **The lossless early stop rarely helps.** It uses the centroid and radius lower bound to skip
  blocks. It skips 13% of the remaining blocks on `vector_clustered` at `rho` = 0.8 and nothing
  elsewhere, with recall 1.00. Ordering blocks by that bound is far worse than ordering them by
  centroid distance: it needs 24 blocks for recall 0.9.
- **Block size trades invocations against wasted reads.**
  - From 1k to 20k rows per block, broad queries go from 71.5 to 7.0 blocks touched.
  - Selective queries go from reading 3.1 to 46.3 times the rows they need (68 times in the worst
    case).
  - Metadata shrinks from 108 KB to 5.4 KB.

| | |
|---|---|
| ![E1: blocks scanned](plots/e1_blocks_scanned.png) | ![E2: latency speedup](plots/e2_speedup.png) |
| **E1.** Fraction of blocks scanned against filter selectivity, per layout and metadata. | **E2.** Latency speedup (solid) against blocks ratio (dotted), against the full scan of the same query. |
| ![E3: recall against blocks](plots/e3_recall_vs_blocks.png) | ![E4: block size](plots/e4_block_size.png) |
| **E3.** Recall@10 against blocks scanned, by centroid order (solid) or lower-bound order (dashed); stars mark the early stop. | **E4.** Blocks touched and read amplification against block size, `tenant_sorted`. |

All numbers per selectivity bucket are in [results/summary_table.md](results/summary_table.md).

## What is compared

**Data** (`src/data.py`):
- a Gaussian mixture of 64 clusters;
- each tenant has 3 home clusters, and `rho` is the probability that a row comes from one of them;
- tenants are either uniform (2,000 rows each) or Zipf(1.1) (294 to 46,751 rows);
- filters are IN-lists of 1, 3, 10 or 25 tenants;
- each query is the centre of the cluster of a random matching row, plus noise.

**Layouts** (`src/layout.py`). Each layout is an order of the rows, cut into blocks of B rows.

| Name | Order |
|---|---|
| `random` | random (a seeded shuffle of the arrival order) |
| `tenant_sorted` | stable sort by tenant id |
| `vector_clustered` | MiniBatchKMeans with N/B clusters, rows sorted by cluster |

**Metadata per block** (`src/metadata.py`):
- zone map: min and max tenant id, 8 B;
- tenant set: an exact bitmap, 13 B for 100 tenants;
- centroid and radius: 520 B, float64. It gives the lower bound `max(0, ‖q − c‖ − r)` on the
  distance from the query to any row in the block.

**Pruners** (`src/search.py`, `PRUNERS`). `search(blocks, query, meta, pruner, k, max_blocks,
early_stop)` scans the blocks a pruner returns, in its order. `max_blocks` limits the scan to the
first m blocks, and `early_stop` skips a block whose lower bound exceeds the current 10th-best
distance.

| Name | Blocks scanned, in order |
|---|---|
| `none` | all blocks: the full-scan baseline and ground truth |
| `zonemap` | blocks whose tenant range covers a requested tenant |
| `tenant_set` | blocks whose bitmap holds a requested tenant |
| `tenant_set_by_centroid` | as `tenant_set`, nearest centroid first |
| `tenant_set_by_bound` | as `tenant_set`, smallest lower bound first |

**Experiments** (`experiments.py`):

| ID | Question | Varies |
|---|---|---|
| E1 | How many blocks does attribute pruning skip? | layout × {`zonemap`, `tenant_set`} × {uniform, Zipf} × `rho` ∈ {0.8, 1.0} |
| E2 | Does latency fall as much as blocks touched? | as E1, timed against the full scan of the same query |
| E3 | Recall against blocks scanned with similarity ranking | layout × m ∈ {1, 2, 3, 4, 6, 8, 12, 16, 24, 40} × `rho` ∈ {0, 0.8} × order; plus the early stop (Zipf tenants) |
| E4 | Effect of block size | B ∈ {1k, 5k, 20k} on `tenant_sorted`, Zipf tenants |

## Running it

Needs [uv](https://docs.astral.sh/uv/). It installs Python 3.13 (`.python-version`) and the
locked dependencies (`uv.lock`).

```
uv sync                          # install the locked environment
uv run pytest                    # 252 tests, about 2 minutes
uv run python experiments.py     # all experiments, about 7.5 minutes (or only: e1_e2 e3 e4)
uv run python plots.py           # figures in plots/, results/summary_table.md
```

Without uv, the same commands work with Python 3.13 and `pip install -r requirements.txt`, run
from the repository root.

`experiments.py` writes per-query and summary tables to `results/`, plus `run_config.json`
(parameters, commit, versions, platform). `plots.py` reads them and writes `plots/*.png` and
`results/summary_table.md`.

## Reproducibility

- **Fixed seeds:** data 0, queries 1, layouts 0. Each part has its own generator.
- **One thread** for numpy and scikit-learn.
- **Locked dependencies** in `uv.lock`, with exact pins in `pyproject.toml`.
- **Deterministic ties:** ties in the top-k are broken by row id.
- **Checked:** two full runs on commit `7dcef8e`, and a third from a fresh clone installed with
  `uv sync --frozen`, gave identical results files once timing columns are removed. The hashes
  are in [NOTES.md](NOTES.md), section 10.
- **Timing noise:** median latencies moved by 1.9% between the two runs, 9% at most, so speedup
  differences under about 6% are noise.
- **The committed `results/` and `plots/`** come from the run on commit `7dcef8e`.

## Repository layout

```
src/
  data.py             synthetic dataset and queries
  layout.py           the three layouts, cut into blocks
  metadata.py         zone map, tenant set, centroid and radius, lower bound
  search.py           pruners and the filtered top-k search
  metrics.py          recall, timing, per-query table, per-bucket summary
  reproducibility.py  thread limit, run config, results hash
experiments.py        runs E1-E4 and writes results/
plots.py              draws plots/ and results/summary_table.md
tests/                correctness and consistency tests for all of the above
results/              results of the committed run
plots/                figures of the committed run
NOTES.md              hypotheses, decisions, logs, results, surprises
```

## Limitations

- **The data is easy.** Clusters never overlap, and every query lands in a cluster its tenants
  occupy. Centroid ranking looks better here than it would on real embeddings.
- **In memory, in one process.** No object storage, network or cold starts are modelled; latency
  is only a proxy for cost.
- **No index inside a block.** Search inside a block is exact brute force, with no ANN index, and
  there is no post-filtering baseline.
- **Blocks are fixed-size.** With 64 true clusters in 40 blocks, `vector_clustered` blocks mix
  about 2 clusters each, which keeps them wide and the lower bound loose.
- **The grid was reduced to save time.** E3 ran only `rho` = 0 and 0.8, so how the trade-off
  depends on `rho` is only partly tested. E4 ran three block sizes.
- **One machine** (Windows 11) and one run configuration.

Next steps are listed in [NOTES.md](NOTES.md), section 11.
