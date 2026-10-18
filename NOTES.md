# Development notes

Working log for **filtered-block-pruning**, a small prototype for block pruning in tenant-filtered
vector search. It records the hypotheses, the configuration, the design decisions with their
trade-offs, and what each step and experiment produced. The README summarises it.

**Method.** Each hypothesis has a prediction written down *before* the experiment that tests it is
run. Observations and verdicts are added afterwards, and deviations from the plan are logged with the
reason, not silently edited.

---

## Contents

1. [Time log](#1-time-log)
2. [Problem](#2-problem)
3. [Hypotheses](#3-hypotheses)
4. [Configuration](#4-configuration)
5. [Design decisions](#5-design-decisions)
6. [Experiment plan](#6-experiment-plan)
7. [Implementation log](#7-implementation-log)
8. [Results log](#8-results-log)
9. [Surprises](#9-surprises)
10. [Run provenance](#10-run-provenance)
11. [Next steps](#11-next-steps)

---

## 1. Time log

Time budget for the core task: 6 h, starting Sun 18 Oct 2026, 12:00 (UTC+1).

Filled in from the section 7 timestamps, which mark when each step was logged as done, so the
boundaries are approximate.

| Date | Start | End | Duration | Phase | Outcome |
|---|---|---|---|---|---|
| 18 Oct | 12:00 | 12:31 | 0 h 31 min | Framing, design, notes | Problem, H1–H3, configuration, D1–D11, experiment plan; locked environment (uv) |
| 18 Oct | 12:31 | 13:58 | 1 h 27 min | Data generation and layouts | `data.py`, `layout.py` and their tests |
| 18 Oct | 13:58 | 15:21 | 1 h 23 min | Metadata, search, correctness tests | `metadata.py`, `search.py`, `metrics.py`; the D9 correctness tests pass |
| 18 Oct | 15:21 | 15:45 | 0 h 24 min | Experiments E1–E4: predictions and reproducibility | Predictions for H3 and E1–E4; `reproducibility.py` |
| 18 Oct | 15:45 | 16:00 | 0 h 15 min | Plots | `plots.py` and its tests |
| 18 Oct | 16:00 | 16:46 | 0 h 46 min | Experiments E1–E4: script, runs, results | `experiments.py`; two full runs with identical hashes; results and verdicts logged |
| 18 Oct | 16:46 | 17:16 | 0 h 30 min | Review fixes, README, final checks | Notes corrected after review; README written; fresh-clone check passed; everything committed |
| | | | **5 h 16 min** | **Core task total** | Within the 6 h budget |
| | | | | Verification beyond the budget | None needed: every check, including the fresh-clone run, fitted inside the budget |

---

## 2. Problem

Given a query vector `q` and a filter `tenant_id IN F`, return the k = 10 nearest rows (L2 distance)
among the rows that satisfy the filter.

Rows are stored in fixed-size blocks of `B` rows, as in block-based partitioning for stateless
serverless vector databases. **Every block a query touches costs one fetch and one unit of work in a
function invocation**, so the number of blocks touched is the main cost metric.

A block can be skipped for two reasons:

- **Attribute pruning (lossless):** the block's metadata proves it holds no row of a tenant in `F`.
- **Similarity pruning (lossy unless bounded):** the block is judged unlikely to hold any of the
  top-k, from its centroid. A distance lower bound with an early stop makes it lossless.

**Baseline (`full_scan`):** scan every block, keep the rows whose tenant is in `F`, compute exact L2
distances, keep the top 10, merge. It is exact, so its output is also the ground truth for
recall@10.

---

## 3. Hypotheses

### H1: The layout matters more than the metadata

- **Claim:** attribute pruning is lossless, but how much it saves depends on how co-located each
  tenant's rows are. In insertion order a tenant appears in nearly every block, so even an exact
  tenant set prunes almost nothing. On a tenant-sorted layout, blocks scanned should follow
  selectivity.
- **Prediction:** `random`: ~100% of blocks scanned for every filter. `tenant_sorted`: fraction
  scanned ≈ selectivity plus partly filled boundary blocks. On `tenant_sorted` the zone map matches
  the exact tenant set.
- **Refined prediction (added 15:45, before any experiment, from the code and the layout
  measurements in section 7):**
  - `random`: 100% of blocks for every filter and both tenant distributions. Every block holds all
    100 tenants (Zipf: 99% or more).
  - `tenant_sorted`, uniform tenants: a block holds 3 tenants, so a filter on t tenants touches a
    block with probability about 1 − (1 − t/100)³. That gives 3% of blocks for 1 tenant, 9% for 3,
    27% for 10 and 58% for 25. This is 2.3–3 times the selectivity, not "selectivity plus a little",
    because the tenants in an IN-list are random and rarely share a block.
  - `tenant_sorted`, Zipf: close to selectivity for IN-lists that contain a large tenant (the
    largest spans 10 of 40 blocks), and 1 block per small tenant.
  - On `tenant_sorted`, the zone map gives exactly the same blocks as the tenant set, for every
    IN-list: tenants are contiguous, so every tenant inside a block's [min, max] range is in the
    block.
- **Tested by:** E1
- **Observed (run of 16:25, commit `7dcef8e`):**
  - `random` scanned 100% of blocks in every cell, with both kinds of metadata.
  - `tenant_sorted`, uniform tenants, scanned 2.86% / 8.24% / 27.6% / 58.5% of blocks for 1 / 3 /
    10 / 25 tenants (selectivity 1 / 3 / 10 / 25%), against the predicted 3 / 9 / 27 / 58%. That is
    2.9 / 2.7 / 2.8 / 2.3 times the selectivity, as predicted. For 1 tenant, 2.86% is 1.14 blocks
    on average: a 2,000-row tenant fits in one block of 5,000, but sometimes straddles two.
  - `tenant_sorted`, Zipf: 3% / 6% / 14% / 28% / 52% from the lowest to the highest selectivity
    bucket.
  - On `tenant_sorted` the zone map and the tenant set gave the same fraction in every cell.
  - Recall@10 was 1.00 in every cell.
- **Verdict:** supported. The layout decides everything: the same exact metadata prunes nothing on
  `random` and up to 97% of blocks on `tenant_sorted`. The cheap zone map is as good as the exact
  tenant set once tenants are contiguous.

### H2: Attribute locality and similarity locality conflict

- **Claim:** a tenant-sorted layout is best for the filter; a vector-clustered layout is best for
  similarity but scatters each tenant across blocks. Tenant skew makes this worse, since large
  tenants span many blocks under any layout.
- **Prediction:** `vector_clustered` prunes little by tenant at `rho` = 0.8 and more at `rho` = 1.0.
  The zone map is close to useless on `vector_clustered`, because tenant ids are not contiguous
  there.
- **Refined prediction (added 15:45, before any experiment, from the layout measurements):**
  - `vector_clustered` with the tenant set, `rho` = 0.8: about 100% of blocks with uniform tenants
    (a tenant appears in 39–40 of 40 blocks), and 85–100% with Zipf (22–40 blocks per tenant).
  - `vector_clustered` with the tenant set, `rho` = 1.0: a tenant appears in about 6 blocks (15%).
    Expect about 15% of blocks for 1 tenant, 40% for 3, 80% for 10 and about 100% for 25.
  - The zone map on `vector_clustered`: about 100% at both `rho`, since a block's tenant range
    covers 92–100 of the 100 tenant ids.
  - So at `rho` = 1.0 `vector_clustered` prunes, but still 3–5 times more blocks than
    `tenant_sorted` for small IN-lists.
- **Tested by:** E1 (`rho` = 0.8 and 1.0), E3
- **Observed:**
  - `vector_clustered` with the tenant set, `rho` = 0.8: 100% of blocks with uniform tenants. With
    Zipf it was 79% for the most selective bucket (predicted 85–100%) and 98–100% for the others.
  - `rho` = 1.0, uniform: 17% / 40% / 82% / 99% for 1 / 3 / 10 / 25 tenants, against the
    predicted 15 / 40 / 80 / ~100%. Zipf: 15% to 86%.
  - The zone map on `vector_clustered`: 88–100% at `rho` = 1.0, 98–100% at 0.8.
  - For similarity the order is reversed. In E3, centroid order reaches recall 0.9 after scanning
    7.5–10% of blocks on `vector_clustered`, against 13–17% on `tenant_sorted` (blocks actually
    scanned, not the budget m; see H3).
- **Verdict:** supported. The layout that is best for the filter (`tenant_sorted`) is not the best
  for similarity (`vector_clustered`), and the other way round. At `rho` = 1.0, `vector_clustered`
  still scans 5–6 times more blocks than `tenant_sorted` for a single tenant (17% against 3%).

### H3: Combining both kinds of pruning gives a tunable trade-off

- **Claim:** ranking the blocks that survive attribute pruning by similarity, and scanning only the
  first `m`, gives a recall versus blocks-scanned curve. Its shape depends on the layout and on the
  tenant/vector correlation `rho`.
- **Prediction (written 15:45, before any experiment, from the code and the measurements in
  sections 7 and 9):**
  - `random`: every block holds about 1/40 of every tenant and every cluster, so block order does
    not matter. Recall@10 ≈ fraction of blocks scanned: a straight diagonal, the same at every
    `rho`.
  - `tenant_sorted`: only the 1–2 blocks per tenant survive the filter, and each holds all of that
    tenant's clusters, so centroid order helps little. Recall reaches 1 only once all surviving
    blocks are scanned. On a plot against the fraction of *all* blocks, the curve still ends early,
    at the E1 fraction (3–58%).
  - `vector_clustered`, centroid order: the query's top-10 lie in its own cluster (clusters never
    mix), and that cluster is spread over 1–2 blocks (57% of a block comes from its main cluster).
    Expect recall around 0.5–0.7 after 1 block and 0.9 or more after 3 blocks (7.5%), at every
    `rho`. `rho` changes how many blocks survive the tenant filter, not the shape of the curve.
  - Lower-bound order: 81–100% of bounds are 0, so the order falls back to block-id order. Expect
    it to be close to the `random` diagonal and much worse than centroid order (as D5 feared).
  - Early stop: it skipped no block at all in the search tests, so expect no saving at all, and
    recall stays exactly 1.
- **Tested by:** E3
- **Observed** (Zipf tenants; mean recall@10 for a budget of m blocks):

  m is a *budget*: scan at most the first m blocks that survive the tenant filter. When fewer than
  m blocks survive, fewer are scanned. On `random` and `vector_clustered` almost all 40 blocks
  survive, so budget and blocks scanned are the same. On `tenant_sorted` only 9.1 blocks survive
  on average (23%), so a budget of 2 / 3 / 4 / 8 / 12 / 16 / 24 scans on average 1.8 / 2.5 / 3.2 /
  5.3 / 6.9 / 7.9 / 8.9 blocks.

  | Layout, order | `rho` | m = 1 | 2 | 3 | 4 | 8 | 16 | 24 | Budget m for recall ≥ 0.9 | Blocks actually scanned (of 40) |
  |---|---|---|---|---|---|---|---|---|---|---|
  | `random`, centroid | 0 | 0.03 | 0.05 | 0.08 | 0.10 | 0.22 | 0.41 | 0.64 | 40 | 40.0 (100%) |
  | `tenant_sorted`, centroid | 0 | 0.34 | 0.49 | 0.58 | 0.65 | 0.82 | 0.95 | 0.99 | 12 | 6.9 (17%) |
  | `tenant_sorted`, centroid | 0.8 | 0.51 | 0.69 | 0.77 | 0.81 | 0.91 | 0.98 | 1.00 | 8 | 5.3 (13%) |
  | `vector_clustered`, centroid | 0 | 0.63 | 0.79 | 0.85 | 0.90 | 0.93 | 0.96 | 0.98 | 4 | 4.0 (10%) |
  | `vector_clustered`, centroid | 0.8 | 0.71 | 0.87 | 0.90 | 0.92 | 0.94 | 0.98 | 0.98 | 3 | 3.0 (7.5%) |
  | `vector_clustered`, lower bound | 0.8 | 0.05 | 0.09 | 0.11 | 0.15 | 0.31 | 0.72 | 0.94 | 24 | 24.0 (60%) |

  - `random` follows the diagonal with either order, as predicted.
  - `tenant_sorted` reaches recall 0.9 after scanning 5.3–6.9 blocks on average (13–17%), and
    recall 1 once all its 9.1 surviving blocks (23%) are scanned. Centroid order
    helps at `rho` = 0.8 (0.51 after one block, against 0.40 for lower-bound order) but not at
    `rho` = 0.
  - `vector_clustered` with centroid order is close to the prediction: 0.63–0.71 after 1 block
    (predicted 0.5–0.7), and 0.85–0.90 after 3 (predicted 0.9 or more).
  - Not predicted: a long tail. On `vector_clustered`, recall stays at 0.93–0.98 from 8 to 24
    blocks scanned, and only reaches 1 when every surviving block is scanned.
  - Lower-bound order is far worse than centroid order, as predicted. It is a little better than
    the diagonal on `vector_clustered` (0.72 at 40% of blocks), not equal to it.
  - **Early stop: the prediction was wrong.** On `vector_clustered` at `rho` = 0.8 it skipped 13%
    of the blocks that survive the tenant filter (5.2 blocks per query, in 92% of queries), with
    recall 1.00. It skipped nothing on `random` and `tenant_sorted`, and almost nothing on
    `vector_clustered` at `rho` = 0 (1 block in 4% of queries). See section 9.
- **Verdict:** supported for the layout, only partly tested for `rho`. Similarity ranking gives a
  tunable trade-off, and its shape depends on the layout: steep on `vector_clustered` (recall 0.9
  at 7.5% of blocks scanned), moderate on `tenant_sorted` (13–17%), and none on `random`. The
  trade-off has a long tail: the last few percent of recall cost most of the blocks. The claim
  that the shape depends on `rho` was tested only with `rho` = 0 and 0.8. Between those two, the
  curves differ little (recall after 1 block: 0.63 and 0.71 on `vector_clustered`); 0.5 and 1.0
  were not run (section 6).

---

## 4. Configuration

Defaults for all experiments unless an experiment states otherwise.

| Parameter | Value | Rationale |
|---|---|---|
| Rows N | 200,000 | Gives 40 blocks at B = 5,000 and measurable latency, while a full run still takes minutes on a laptop. |
| Dimension d | 64, float32 | Realistic embedding size without brute force dominating run time. |
| Vectors | Gaussian mixture, 64 clusters | Real similarity structure, so k-means and centroid ranking are meaningful. |
| Tenants | 100 | Enough for non-trivial bitmaps and IN-lists of up to 25 tenants. |
| Tenant distribution | Uniform (2,000 rows each) and Zipf(1.1) | Uniform controls selectivity exactly; Zipf gives realistic skew, with a few very large tenants and many small ones. |
| `rho` | 0.8 by default; 0, 0.5, 0.8, 1.0 in E3 | Each tenant has 3 home clusters, and a row is drawn from them with probability `rho`, otherwise from any cluster. This is the main variable behind H2 and H3. |
| Block size B | 5,000 rows (40 blocks); 1k–20k in E4 | 40 blocks give a readable curve; the sweep shows invocation count against wasted reads. |
| Queries | 200 | With Zipf tenants they fill all five selectivity buckets (30–49 queries each). With uniform tenants they fill only four: every query matches exactly 1, 3, 10 or 25% of rows, so the <0.5% bucket is empty. |
| Filter | IN-list of 1, 3, 10 or 25 tenants, chosen uniformly | Spreads selectivity: uniform gives 1/3/10/25%, Zipf about 0.15–53%. |
| Query vector | Centre of the cluster of a random matching row, plus noise | Queries land where their tenants have data, so `rho` actually affects them. |
| k | 10 | Standard value, kept fixed to remove one axis. |
| Distance | L2 | Simple, and it matches the lower-bound derivation. |
| Selectivity buckets | <0.5%, 0.5–2%, 2–5%, 5–15%, >15% | Grouping for tables and plots. |
| Seed | Data 0, queries 1, layouts 0 | One fixed seed per generator; see D10. |
| Environment | CPython 3.13.3; numpy 2.2.4, pandas 2.2.3, matplotlib 3.10.7, scikit-learn 1.8.0, scipy 1.16.3, pytest 9.0.3; locked with uv 0.13.1 (`uv.lock`) | The scikit-learn version changes the k-means output and therefore the `vector_clustered` results. |
| BLAS threads | 1 (the machine's default is 20) | Deterministic floating-point order and more stable latency. Set by `limit_threads()` at the start of each experiment. |
| Timing | 1 warm-up + 3 runs, median; each method timed back to back with `full_scan` on the same query | Removes machine-state drift between methods. Only per-query speedups are compared. |

Changes to these defaults during the work (date, change, reason):

- 18 Oct, 14:25: `centroid_radius` metadata is stored as float64, so it takes 520 B per block, not
  the 260 B planned in D4. Float64 is simpler and cannot make the lower bound too big by rounding.
  Storing float32 would need the radius rounded up to stay safe.

---

## 5. Design decisions

Each entry gives the decision, the alternatives considered, the rationale, the trade-off, and what
would trigger a revision.

### D1: Synthetic data with a correlation knob

- **Decision:** Gaussian mixture, plus a tenant-to-home-cluster mapping controlled by `rho`.
- **Alternatives:** real embeddings (SIFT, GloVe) with synthetic tenants; tenants assigned at random.
- **Rationale:** full control over the tenant/vector correlation, which is what H2 and H3 are about.
- **Trade-off:** the clusters are well separated, which favours k-means and centroid ranking; real
  embeddings are messier. Measured: a row is about 4.0 from its own centre and at least 7.6 from
  any other, so clusters never mix. Each query is a cluster centre plus the same noise as a row, so
  it looks like one more row of that cluster, the easiest case for centroid ranking. Kept as is
  (`noise_std` = 0.5); raising it to about 1.0 would make clusters overlap.
- **Revise if:** time allows a real dataset; otherwise it is a next step.

### D2: Exact brute-force search inside a block

- **Decision:** filter the block's rows, compute exact L2 distances, keep the top 10, merge across
  blocks.
- **Alternatives:** an ANN index per block (HNSW or IVF via FAISS).
- **Rationale:** any recall loss then comes only from pruning, never from an approximate index, so
  it can be attributed cleanly.
- **Trade-off:** lossless pruning computes the same distances as the full scan, so in-memory latency
  hides most of the saving. Blocks touched is the primary cost metric for that reason.
- **Revise if:** studying the interaction between filters and an index (next step).

### D3: Three layouts, each a permutation of row ids

- **Decision:** `random` (insertion order, as produced by streaming ingestion), `tenant_sorted`
  (stable sort by `tenant_id`), `vector_clustered` (MiniBatchKMeans with k = N/B, rows sorted by
  cluster, then cut into fixed-size blocks).
- **Alternatives:** tenant-then-cluster ordering; true clustering-based partitioning with
  variable-size partitions.
- **Rationale:** the two extremes plus no organisation at all. Tenant-then-cluster is left out so
  that H2 stays clean.
- **Trade-off:** `vector_clustered` is fixed-size blocks in cluster order, not clustering-based
  partitioning: blocks straddle cluster boundaries, and the load imbalance of variable-size
  partitions does not appear.
- **Revise if:** after the core experiments; tenant-then-cluster is a short change to the layout
  module.

### D4: Per-block metadata

- **Decision:**
  - `zonemap`: min/max tenant id, 8 B per block.
  - `tenant_set`: exact bitmap of tenants present, 13 B per block for 100 tenants.
  - `centroid_radius`: centroid plus maximum distance from it, 520 B (65 float64 numbers; see
    the change log in section 4), giving the lower bound
    `max(0, ‖q − c‖ − r)` on the distance to any row in the block.
- **Alternatives:** Bloom filters; per-(block, tenant) centroids; several sub-centroids per block.
- **Rationale:** the zone map is the standard, nearly free option; the bitmap is the upper limit of
  what attribute pruning can achieve; centroid plus radius is the simplest similarity metadata with
  a provable bound.
- **Trade-off:** the zone map only works when tenant ids are contiguous. The bitmap grows with the
  number of tenants (125 KB per block at 1M tenants), where a Bloom filter becomes the usual choice.
  The radius bound may be loose in 64 dimensions.
- **Revise if:** E3 shows the bound prunes nothing.

### D5: Block order for similarity pruning

- **Decision:** rank surviving blocks by distance to their centroid, as in IVF probing, and use the
  lower bound only for the lossless early stop. Ordering by lower bound is kept as a variant and
  compared in E3.
- **Alternatives:** order by lower bound only.
- **Rationale:** if block radii are comparable to the distance between clusters, most lower bounds
  are 0, and ordering by them collapses to block-id order.
- **Trade-off:** centroid ranking has no guarantee. The early stop gives one, but may prune little.
- **Safety margin:** the early stop skips a block only when its squared lower bound is bigger than
  the current 10th distance by more than a relative 1e-6. Without this margin, rounding can make
  the bound look a tiny bit too big and skip a block that holds a true result (√2 squared gives
  2.0000000000000004, not 2).
- **Revise if:** E3 shows the lower-bound ordering is competitive.

### D6: Baseline is an exact pre-filter full scan

- **Decision:** scan all blocks, filter first, then compute exact distances.
- **Alternatives:** post-filtering (unfiltered top-k′, then filter), as many ANN-based systems do.
- **Rationale:** exact, so it doubles as the ground truth; it uses the same in-block code as every
  pruned method, so the only difference between methods is which blocks get scanned.
- **Trade-off:** there is no comparison against post-filtering; this is listed as a limitation.

### D7: Metrics

- **Decision:** blocks touched (= function invocations), rows read, distances computed, recall@10
  against the exact filtered result, and latency (paired, median).
- **Rationale:** blocks touched is the cost proxy for a serverless setting; single-process in-memory
  latency is only a proxy.
- **Trade-off:** no object storage, network or cold starts are modelled.

### D8: Pruners as plain functions

- **Decision:** a pruner is a function `(query, meta) -> ordered array of block ids`, registered by
  name in `PRUNERS`: `none` (the `full_scan` baseline of D6), `zonemap`, `tenant_set`,
  `tenant_set_by_centroid` and `tenant_set_by_bound`. The baseline is registered as `none` (its
  function is `all_blocks`); results files, plots and the README use the registered names. Every method is one call to
  `search(blocks, query, meta, pruner, k, max_blocks, early_stop)`. It returns squared L2
  distances, which rank rows the same way as L2.
- **Rationale:** a new pruning strategy is one function and one registration line, with no change to
  the search or the experiments.

### D9: Correctness tests

- **Decision:**
  - `full_scan` equals plain numpy brute force over the whole dataset, which checks the ground truth
    itself.
  - `zonemap`, `tenant_set`, the early stop, and similarity pruning with `m` = all surviving blocks
    each return exactly the `full_scan` top-10, on every layout.
  - The zone map never drops a block that holds a matching row.
- **Check on the tests:** an off-by-one in the zone map comparison and an L1 distance in place of L2
  must both make tests fail.

### D10: Reproducibility

- **Decision:**
  - One fixed seed per generator: data uses seed 0, queries use seed 1, and layouts use seed 0
    (`build_blocks(seed=0)`, for both the `random` shuffle and k-means). Each part makes its own
    generator and never touches numpy's shared one (`np.random.seed`), so changing one part does
    not shift the random numbers of the others. A test checks this. (The first
    plan was one master seed split into child seeds; fixed seeds give the same guarantee more
    simply.)
  - Inside the data generator, no random draw depends on `rho`. The same row gets the same vector
    at every `rho` whenever it stays in the same cluster, so results at different `rho` are
    compared on the same rows. A test checks this.
  - `random_state` and `n_init` set explicitly for k-means.
  - Dependencies and the Python version pinned in a lock file (uv).
  - BLAS and OpenMP limited to one thread.
  - Ties in the top-k broken by (distance, row id).
  - The configuration of every run written to `results/run_config.json`.
- **Alternatives:** Docker, which would also pin system libraries and the BLAS build.
- **Rationale:** the lock file covers the Python stack at a fraction of the cost. On a Windows host,
  containers run inside a virtual machine, which distorts latency, so timed runs stay native.
- **Trade-off:** floating-point results can still differ in the last bits across CPUs (AVX2 vs
  AVX-512). The claim is exact reproduction of all non-timing results on the same machine and
  environment. Latency is never exactly reproducible; its spread over several runs is reported
  instead.
- **Check:** two runs, and a fresh clone installed from the lock file, give identical hashes of the
  results files once timing columns are removed.
- **How it is done (`src/reproducibility.py`):**
  - `limit_threads(1)` sets numpy and scikit-learn to one thread, both through environment
    variables and through threadpoolctl.
  - `write_run_config(path, **params)` saves a run's parameters, git commit (and whether there were
    uncommitted changes), Python and package versions, platform, thread count and start time as
    JSON.
  - `table_hash(df)` and `csv_hash(path)` give a SHA-256 of a results table without its timing
    columns: `latency_ms`, `p50_ms`, `p95_ms` and `build_s`, plus `full_scan_ms`, `speedup` and
    `speedup_p50`, which are computed from timings.
  - `experiments.py` sets the thread environment variables to 1 before importing numpy. It writes
    its own `results/run_config.json`, with the parameters, the short commit (with `-dirty` if
    tracked files had uncommitted changes), versions and platform. The hash of each results file
    goes in section 10.

Further decisions made during the work:

### D11: Project setup with uv, exact pins, no build system

- **Decision:** `pyproject.toml` with the runtime dependencies pinned exactly, pytest in a `dev`
  dependency group, `requires-python = ">=3.13,<3.14"`, `.python-version` = 3.13, and `uv.lock`
  committed. No build system: the project is not installed as a package. Code is imported as
  `src.data` etc., and pytest finds it through `pythonpath = ["."]`.
- **Alternatives:** version ranges in `pyproject.toml` with only the lock file pinning; a src-layout
  package with a build backend.
- **Rationale:** exact pins keep `pyproject.toml` and the lock in agreement on the versions that
  matter for reproducibility (D10), so nothing changes if someone installs without the lock. A
  package adds nothing for a prototype run from scripts.
- **Trade-off:** `requirements.txt` duplicates the pins and can drift from the lock; it is kept only
  as a pip fallback and should be regenerated with `uv export` if versions change.
- **Revise if:** the code needs to be imported from outside the repo, or the pins need to move.

---

## 6. Experiment plan

| ID | Question | Varies | Fixed | Output |
|---|---|---|---|---|
| E1 | H1, H2: how much does each layout and metadata combination prune? | layout × {zonemap, tenant_set} × tenant distribution × `rho` ∈ {0.8, 1.0} | B = 5,000 | Fraction of blocks scanned per selectivity bucket |
| E2 | Does latency fall as much as blocks touched? | as E1 | as E1 | Per-query latency speedup against blocks ratio |
| E3 | H3: recall against blocks scanned with similarity ranking | layout × `m` ∈ 1..40 × `rho` ∈ {0, 0.5, 0.8, 1.0}; centroid vs lower-bound order; early stop | B = 5,000 | Recall@10 against fraction of blocks scanned |
| E4 | Effect of block size | B ∈ {1k, 2k, 5k, 10k, 20k} | `tenant_sorted`, Zipf | Blocks touched, rows read per matching row, metadata size |
| E5 | Pruning decay under streaming ingestion | Share of unsorted blocks | | Fraction scanned against drift (not in the time budget) |

Planned figures:

1. `plots/e1_blocks_scanned.png`: fraction of blocks scanned against selectivity, one line per
   layout and metadata.
2. `plots/e2_speedup.png`: latency speedup against blocks ratio, with the line y = x for reference.
3. `plots/e3_recall_vs_blocks.png`: recall@10 against fraction of blocks scanned, one curve per
   layout and `rho`.
4. `plots/e4_block_size.png`: blocks touched and read amplification against B.
5. `results/summary_table.md`: summary per layout and selectivity bucket, generated by `plots.py`.

How `plots.py` draws them (16:00), where this differs from the list above:

- **Figure 2** shows two lines per layout against selectivity: the latency speedup (solid) and the
  blocks ratio (dotted). This replaces a scatter of one against the other with the line y = x.
  "Below y = x" becomes "solid line below its dotted line".
- **Figure 3** has two panels, `rho` = 0 and `rho` = 0.8, each with one curve per layout. Centroid
  order is solid, lower-bound order dashed, and the early stop is a star. `rho` = 0.5 and 1.0 are
  run but not drawn.
- Run from the repository root: `uv run python experiments.py` (all experiments, or only some of
  `e1_e2`, `e3`, `e4`), then `uv run python plots.py`. Tests: `uv run pytest`. `uv run` uses the
  locked environment (D11). Without uv, the same commands work with the project's `.venv` active
  (or `.venv\Scripts\python` in place of `python`), after `uv sync` or an install from the lock
  file.

How `experiments.py` runs them (16:12), where this differs from the table above:

- **E1/E2:** `rho` = 1.0 is run for `vector_clustered` only. For `random` and `tenant_sorted`, which
  blocks hold which tenant does not depend on `rho`. The zone map is not timed.
- **E3:** Zipf tenants, `rho` ∈ {0, 0.8} (not 0.5 and 1.0), and m ∈ {1, 2, 3, 4, 6, 8, 12, 16, 24,
  40} instead of every value from 1 to 40, to save time.
- **E4:** B ∈ {1k, 5k, 20k} instead of five sizes, `rho` = 0.8. It also writes
  `e4_metadata_size.csv` (total bytes of each kind of metadata).
- **Also written:** `layout_build.csv` (time to build each layout) and `run_config.json`.

Files the experiment script must write to `results/` for `plots.py` (fixed by
`tests/test_plots.py`):

| File | One row per | Columns |
|---|---|---|
| `e1_e2_summary.csv` | tenant distribution × pruner (`none`, `zonemap`, `tenant_set`) × layout × `rho` × bucket | `dist`, `pruner`, `layout`, `rho`, `bucket`, `queries`, `frac_blocks`, `recall`, `speedup_p50`, `blocks_ratio_p50` |
| `e1_e2_per_query.csv` | query × the same keys | `dist`, `pruner`, `layout`, `rho`, `bucket`, `ideal_frac` (fraction of blocks if the matching rows were packed together) |
| `e3_per_query.csv` | query × `rho` × layout × order × `m` | `rho`, `layout`, `order` (`tenant_set_by_centroid`, `tenant_set_by_bound`, or `early_stop` with empty `m`), `m`, `bucket`, `frac_blocks`, `recall` |
| `e4_per_query.csv` | query × block size | `block_size`, `bucket`, `blocks_touched`, `read_amplification` (rows read / matching rows) |

`speedup_p50` and `blocks_ratio_p50` are medians of per-query ratios against the full scan of the
same query (section 4, Timing), so `summarize` in `metrics.py` does not produce them. The
experiment script computes them.

---

## 7. Implementation log

<!-- One entry per step:
### HH:MM: step
- Done:
- Deviations from the plan, and why:
- Problems:
- Tests:
-->

### 12:31: environment setup

- Done: `pyproject.toml`, `.python-version` and `uv.lock` created from `requirements.txt` (D11).
  `uv lock` resolved 25 packages; `uv sync` built `.venv` on CPython 3.13.3, and all six pinned
  packages import at the expected versions.
- Deviations from the plan, and why: none.
- Problems: uv was not installed on the machine; it was run from a temporary venv to create the lock.
  Reproducing the environment needs uv installed (`uv sync`).
- Tests: none yet (`src/` and `tests/` are empty).

### 13:23: data generator and its tests

- Done: `src/data.py` makes the dataset (tenant sizes, home clusters, vectors, random arrival order)
  and the queries. `tests/test_data.py` has 30 tests; all pass in about 3 s. They check that tenant
  sizes add up to N, that types and shapes are right, that the same seed gives the same data, that
  rows are paired across `rho`, that the share of rows in home clusters matches `rho`, and that
  query selectivity is right.
- Check on the tests: 10 deliberately broken copies of `data.py` (for example `rho` reversed, no
  shuffle, noise doubled, selectivity off by one) each made at least one test fail.
- Deviations from the plan, and why: two fixed seeds instead of one master seed (D10 updated).
  pytest path changed from `src` to `.` so tests can import `src.data` (D11 updated).
- Problems: none in the code. What the measurements showed about the data is in section 9.

### 13:58: layouts and their tests

- Done: `src/layout.py` builds the three layouts of D3 and cuts them into fixed-size blocks.
  `vector_clustered` uses MiniBatchKMeans with N/B clusters, `batch_size` 4096, `n_init` 3 and a
  fixed `random_state`. `tests/test_layout.py` has 33 tests; all 63 tests pass in about 10 s.
  They check that every row is in exactly one block, that block sizes and contents are right, that
  the same seed gives the same blocks, that the dataset and numpy's shared generator are left
  alone, that `tenant_sorted` keeps tenants together and in arrival order, and that
  `vector_clustered` groups similar vectors.
- Deviations from the plan, and why: `random` is a seeded shuffle of the arrival order, not the
  arrival order itself. Rows already arrive in random order, so this changes nothing in the
  results.
- Problems: the tests found that `random` reset numpy's shared generator (`np.random.seed`), which
  would silently change the random numbers of any other code (D10); fixed with a generator of its
  own. Two crash-level slips were also fixed. One test was wrong at first: it expected clustered blocks to be 20% tighter than random ones while
  using 64 true clusters for only 20 blocks. It now uses as many true clusters as blocks.
- First look (B = 5,000, uniform tenants): `random` has all 100 tenants in every block.
  `tenant_sorted` has about 3, and a tenant fills 1–2 blocks. `vector_clustered` has 100 at
  `rho` = 0.8 but 15 at `rho` = 1.0, and its zone map covers almost every tenant id (width 92–100).
  This is what H1 and H2 predict; E1 will measure it properly.

### 14:27: block metadata and its tests

- Done: `src/metadata.py` builds, for each block, the zone map (min and max tenant id), the exact
  tenant set, and the centroid with its radius. `lower_bound` gives `max(0, ‖q − c‖ − r)` per block,
  and `bytes_per_block` gives the size of each kind of metadata. `tests/test_metadata.py` has 36
  tests; all 99 tests pass in about 11 s. They check, on all three layouts, that the zone map and
  tenant set are exact, that the centroid and radius are right, and that the lower bound is never
  bigger than the true distance to the nearest row in the block (40 queries × 20 blocks, including
  queries far from the data). If that last test failed, the early stop could lose results.
- Deviations from the plan, and why: centroid and radius are stored as float64, 520 B per block
  instead of 260 B (see the change log in section 4).
- Problems: the tests found that the reported size of the centroid and radius (260 B) did not
  match what was stored (520 B), which would have made E4 report the wrong metadata size; fixed
  (section 4, change log). Two crash-level slips were also fixed.

### 15:04: search and its tests

- Done: `src/search.py` has the five pruners of D8 and `search`, which scans blocks in the pruner's
  order, keeps the best 10, and counts blocks touched, rows read and distances computed (D7). It
  supports `max_blocks` (scan only the first m blocks, for E3) and the early stop (D5).
  `tests/test_search.py` has 105 tests; all 204 tests pass in about 23 s. On all three layouts
  they check that:
  - the full scan gives the same top-10 as plain numpy over the whole dataset (D9);
  - every pruner, with and without the early stop, returns exactly the full-scan top-10 (D9);
  - no pruner drops a block that holds a matching row;
  - blocks come in the right order, `max_blocks` scans only the first m blocks, and the counters
    are right;
  - ties are broken by row id (D10).
- Check on the tests: 9 deliberately planted bugs each made at least one test fail, including
  the two D9 asks for (zone map off by one, L1 instead of L2 distance), an early stop that skips
  too much, starts before it has 10 results, or compares an unsquared bound, and `max_blocks`
  being ignored.
- Deviations from the plan, and why: the argument order of `search` is (blocks, query, meta), not
  (blocks, meta, query) as first written in D8 (D8 updated). The early stop got a safety margin
  (D5 updated).
- Problems: the tests found four real bugs, all fixed:
  - distances were computed from row ids instead of vectors, so no search worked;
  - `max_blocks` was ignored, so E3's "first m blocks" would have scanned everything;
  - ties were not broken by row id, in the block or when merging, so two methods could return
    different rows (D10);
  - the early stop could skip a block that holds a true result because of rounding (D5).

  Two crash-level slips were also fixed.
- Problem with the tests themselves: on the default data the early stop never skips a block (see
  section 9), so the first early-stop test passed without testing any skip. Two hand-made tests
  (rows on a line) and one test on tight, well-separated blocks now make the skip rule matter.

### 15:21: metrics and their tests

- Done: `src/metrics.py` turns search results into the D7 metrics. `measure` runs every method on
  every query and makes one table row per (query, method): blocks touched, fraction of blocks,
  rows read, distances computed, recall@10 against the full scan, latency and selectivity bucket.
  `summarize` averages them per bucket and any other key (for example method or layout). Latency
  follows section 4: one warm-up run, then the median of the timed runs, in milliseconds.
  `tests/test_metrics.py` has 17 tests; all 221 tests pass in about 23 s.
- Check on the tests: 8 deliberately planted bugs in `metrics.py`. At first 2 got through (recall
  divided by the rows found instead of the true top-10, and the mean instead of the median); a test
  was added for each, and now all 8 are caught. The median test uses a fake clock so it does not
  depend on real timings.
- Deviations from the plan, and why: none.
- Problems: `metrics.py` and `search.py` disagreed on argument order and on some names, so
  nothing ran; `search.py` and its tests now use the names in D7 and D8 (`pruner`, `row_ids`,
  `blocks_touched`, `rows_read`).

### 15:45: predictions and reproducibility

- Done: predictions written for H3 and for E1–E4 (sections 3 and 8), and sharper numbers added to
  H1 and H2 as a dated addition, with the original predictions kept. All are based on the code
  and on layout facts measured at full size (blocks per tenant, tenants per block), not on any
  experiment result.
- Done: `src/reproducibility.py` implements D10: one thread, a run config file, and a results hash
  without timing columns. `tests/test_reproducibility.py` has 13 tests; all 234 tests pass in about
  24 s. They check that every thread pool is set to 1, that the run config records the parameters,
  package versions and current commit, that the hash ignores timing but changes when any other
  value changes (even in the 15th digit), that it survives saving to CSV and reloading, and that
  two runs of a small experiment give the same hash on all three layouts.
- Check on the tests: 7 deliberately planted bugs each made at least one test fail. These were:
  timing not dropped from the hash, floats rounded before hashing, threads not limited,
  environment variables not set, commit not recorded, parameters not recorded, and a search made
  non-deterministic.
- Deviations from the plan, and why: none.
- Problems: none. Found while checking: the machine runs numpy and scikit-learn on 20 threads by
  default, and the thread limit stays in place even if the object `limit_threads` returns is
  discarded.

### 16:00: plots and their tests

- Done: `src/plots.py` reads the experiment results and draws the four planned figures, and
  writes `results/summary_table.md` (section 6). There are no real results yet, because the
  experiment script is not written. `tests/test_plots.py` therefore feeds it small made-up tables
  with known values: 10 tests, and all 244 tests pass in about 34 s. They check that buckets are
  ordered from low to high selectivity, and that each panel of each figure plots the right cell
  (pruner, tenant distribution, layout, `rho`). They also check that E3 curves are sorted by `m`
  and averaged over queries, that the summary table has every row, and that
  running it from the command line writes four PNG files and the table. They also fix the columns the
  experiment script must write (section 6).
- Check on the tests: 7 deliberately planted bugs. At first one got through (median instead of
  mean in E3), because the made-up data had two queries, where the median equals the mean. With
  three queries all 7 are caught. The others were: E1 panels swapped, `rho` ignored, E2 drawn from
  the zone map, E3 not sorted by `m`, buckets left in file order, and E4 panels swapped.
- Checked by eye on the made-up data: the four figures render without overlapping text.
- Deviations from the plan, and why: figures 2 and 3 are drawn differently from the plan (see
  section 6).
- Problems: none in the code.

### 16:12: experiment script and its tests

- Done: `experiments.py` runs E1/E2, E3 and E4 and writes the files `plots.py` reads (section 6);
  `plots.py` moved to the repository root next to it. `tests/test_experiments.py` runs every
  experiment on 20,000 rows and 20 queries, then runs `plots.py` on the output. It has 8 tests; all
  252 tests pass in about 110 s. They check that every file and column `plots.py` needs is written,
  that E1/E2 covers every combination, and that attribute pruning has recall 1. They also check
  that speedup is measured against the full scan of the same query, that E3 reaches recall 1 when
  all surviving blocks are scanned, and that read amplification is at least 1. Finally, two runs
  must give the same results hash (D10).
- Deviations from the plan, and why: fewer `rho` values, `m` values and block sizes than planned,
  to save time (section 6).
- Problems: the "dirty" check in `run_config.json` counted untracked files, so any untracked file
  would have marked every run as made from uncommitted code; it now looks at tracked files only.
  Two crash-level slips (argument order, pruner function passed instead of its name) were also
  fixed.
- Problem found by the reproducibility test: two runs gave different hashes for the E1/E2 files.
  The new `speedup` and `full_scan_ms` columns are computed from timings, so they differ on every
  run. They are now dropped from the hash like the other timing columns (D10 updated).
- Moving `plots.py` broke the plot tests' import; they now import it from the root.

### 16:35: first full run and results

- Done: `experiments.py` (16:25–16:32, 450 s, commit `7dcef8e`, clean) and `plots.py`, run with
  the project's `.venv` Python. This wrote the four figures in `plots/`, `results/summary_table.md` and the
  results files, hashed in section 10. Observations and verdicts are in sections 3, 8 and 9.
- Predictions: E1 and E4 held to within a few points. E2 was right about the direction (latency
  falls much less than blocks touched) but wrong about where the gap is largest relative to the
  blocks ratio. E3 was close for the recall curves, but wrong about the early stop, which skipped
  13% of blocks on `vector_clustered` at `rho` = 0.8. The prediction came from a small setup that
  did not carry over (section 9).
- Deviations from the plan, and why: none beyond the reduced `rho`, `m` and block-size values
  already logged (section 6).
- Reproducibility (D10): a second full run on the same commit gave identical hashes for all five
  results files. Median latencies moved by 1.9% on average and by 9% at most (section 10).

### 17:01: review fixes, README, and closing

- Done: the notes were corrected after a review.
  - E3 now separates the budget m from the blocks actually scanned.
  - H1 gives unrounded fractions.
  - Commands use `uv run`.
  - Typo-level bug reports are trimmed.
  - Untested explanations are marked as likely.
  - The time log is filled in.
- Done: `README.md` summarises the results with the four figures, what is compared, how to run
  it, reproducibility and limitations. It uses the pruner names from the code.
- Done: the notes file is renamed `NOTES.md` and committed with `results/` and `plots/` from the
  run on commit `7dcef8e`. All 252 tests pass, and every link in the README points to a file in
  the repository.
- Final check (D10): a fresh clone of commit `2afc6c8`, installed with `uv sync --frozen`, passed
  all 252 tests with the README's commands. A full run of `experiments.py` in that clone gave
  results identical to the committed ones for all five files (run 3, section 10). Every D10 check
  has now passed.

---

## 8. Results log

<!-- The prediction is copied from section 3 before the run; the rest is filled in after. -->

All predictions below were written at 15:45, before any experiment was run. They use the code and
the layout and search measurements logged in sections 7 and 9.

### E1: layout × metadata

- **Prediction:** from H1 and H2 (refined predictions). Fraction of blocks scanned, uniform tenants:

  | Layout and metadata | 1 tenant | 3 | 10 | 25 |
  |---|---|---|---|---|
  | `random`, either metadata | 100% | 100% | 100% | 100% |
  | `tenant_sorted`, tenant set = zone map | 3% | 9% | 27% | 58% |
  | `vector_clustered`, tenant set, `rho` = 0.8 | ~100% | ~100% | ~100% | ~100% |
  | `vector_clustered`, tenant set, `rho` = 1.0 | ~15% | ~40% | ~80% | ~100% |
  | `vector_clustered`, zone map | ~100% | ~100% | ~100% | ~100% |

  Recall is 1 everywhere, because both kinds of metadata are lossless (checked by tests).
- **Result** (`plots/e1_blocks_scanned.png`, `results/summary_table.md`):

  | Layout and metadata, uniform tenants | 1 tenant | 3 | 10 | 25 |
  |---|---|---|---|---|
  | `random`, either metadata | 100% | 100% | 100% | 100% |
  | `tenant_sorted`, tenant set = zone map | 2.9% | 8.2% | 27.6% | 58.5% |
  | `vector_clustered`, tenant set, `rho` = 0.8 | 100% | 100% | 100% | 100% |
  | `vector_clustered`, tenant set, `rho` = 1.0 | 17% | 40% | 82% | 99% |
  | `vector_clustered`, zone map, `rho` = 1.0 | 88% | 100% | 100% | 100% |

  Every prediction held to within a few points. One cell was a little lower than predicted:
  `vector_clustered` with Zipf at `rho` = 0.8 scanned 79% in the most selective bucket (predicted
  85–100%). Recall@10 was 1.00 in all 36 cells. Building a layout took 0.05 s (`random`), 0.08 s
  (`tenant_sorted`) and 1.0 s (`vector_clustered`, k-means).
- **Takeaway:** attribute pruning only works when the layout puts each tenant's rows together.
  Even then, a random IN-list touches 2.3–2.9 times more blocks than its selectivity (uniform
  tenants): a block holds
  about 3 tenants, and the requested tenants rarely share one. The zone map costs 8 bytes per block
  and is as good as an exact tenant set on a tenant-sorted layout, but useless on the others.

### E2: latency

- **Prediction:** latency falls less than blocks touched; points sit below the line y = x. A
  skipped block saves only the tenant check (`np.isin` on 5,000 rows) and loop overhead. The
  distance work is the same for every lossless method, because distances are computed only for
  matching rows, and all methods visit those. Expect the gap to be largest at high selectivity,
  where distance work dominates. At 1% selectivity on `tenant_sorted` (blocks ratio about 33×),
  expect a latency speedup well under half of that.
- **Result** (`plots/e2_speedup.png`; medians per query, `tenant_set` against the full scan of the
  same query):

  | `tenant_sorted` | Blocks ratio | Latency speedup | Speedup / ratio | Full scan / pruned (ms) |
  |---|---|---|---|---|
  | Zipf, <0.5% | 40× | 10.6× | 0.27 | 2.67 / 0.25 |
  | Uniform, 1 tenant (0.5–2%) | 40× | 4.3× | 0.11 | 3.18 / 0.75 |
  | Uniform, 3 tenants (2–5%) | 13.3× | 2.2× | 0.17 | 5.27 / 2.35 |
  | Uniform, 10 tenants (5–15%) | 3.6× | 1.4× | 0.39 | 10.91 / 7.98 |
  | Uniform, 25 tenants (>15%) | 1.7× | 1.1× | 0.65 | 22.52 / 21.24 |

  - The speedup is always well below the blocks ratio, as predicted. At 1% selectivity it is 4.3×
    for 40× fewer blocks, under the predicted "well under half".
  - `vector_clustered` at `rho` = 1.0: 2.2–3.4× speedup for 6–7× fewer blocks.
  - `random`: 1.0× in every bucket, so a tenant check that prunes nothing costs nothing measurable.
  - **Part of the prediction was wrong:** "the gap is largest at high selectivity". In absolute
    terms the gap is largest at low selectivity (40× against 4.3×). Relative to the blocks ratio,
    the speedup keeps more of the saving at high selectivity (0.65 of the ratio at >15%, 0.11 at
    1%).
- **Takeaway:** in memory, skipping a block that holds no matching row saves only about 0.06 ms,
  the cost of the tenant check on 5,000 rows. Most of the time goes into distance work on matching
  rows, which every lossless method does. Latency therefore understates the saving that matters
  in a serverless setting: 40× fewer invocations and block fetches. This is why blocks touched is
  the main cost metric (D7).
  - The two cells with the same 40× blocks ratio confirm this. Zipf <0.5% gets 10.6× but uniform 1%
    only 4.3×, because the Zipf queries have fewer matching rows (median 426 against 2,000). Their
    pruned scan does less distance work (0.25 ms against 0.75 ms), while the full scans cost about
    the same (2.67 ms against 3.18 ms).

### E3: similarity pruning

- **Prediction:** see H3. In short:
  - `random` follows the diagonal.
  - `vector_clustered` with centroid order reaches recall 0.9 or more after about 3 blocks.
  - Lower-bound order is close to the diagonal.
  - The early stop saves nothing.
- **Result** (`plots/e3_recall_vs_blocks.png`): see H3, Observed, for the table.
  - Centroid order on `vector_clustered` reaches recall 0.9 after 3 blocks at `rho` = 0.8 and 4
    blocks at `rho` = 0. Mean recall then creeps from 0.93 to 0.98 between 8 and 24 blocks.
  - `tenant_sorted` needs a budget of m = 8–12 for recall 0.9. Since only 9.1 blocks survive the
    filter on average, that scans 5.3–6.9 blocks (13–17%). It is exact once all 9.1 surviving
    blocks (23%) are scanned.
  - Lower-bound order needs 24 blocks for 0.9 on `vector_clustered`.
  - The early stop is lossless everywhere (recall 1.00). On `vector_clustered` at `rho` = 0.8 it
    scans 83.5% of blocks instead of 96.4%, and computes 13.5% fewer distances. Elsewhere it saves
    nothing.
- **Takeaway:**
  - On a vector-clustered layout, scanning the 3–4 blocks nearest the query by centroid finds 90%
    of the true top-10 for 10% of the cost. Getting the last 10% costs the other 90%.
  - On a tenant-sorted layout the tenant filter already does most of the work, and exact results
    cost 23% of blocks.
  - The lower bound is too loose to order blocks (blocks are wide; section 9). It still lets the
    early stop skip some blocks when the 10th-best distance is small, which happens when a
    tenant's rows sit in the query's cluster.

### E4: block size

- **Prediction** (`tenant_sorted`, Zipf):
  - Blocks touched falls as B grows, roughly as (matching rows / B) + 1 per tenant in the IN-list.
  - Rows read per matching row grows with B, because each tenant wastes up to one partly-used
    block. The worst case is selective queries: a 294-row tenant reads about 1,000 rows at
    B = 1k (3.4×) but 20,000 at B = 20k (68×).
  - Metadata per block is fixed (8 + 13 + 520 = 541 B), so total metadata is 541 B × N/B: about
    108 KB at B = 1k and 5.4 KB at B = 20k.
- **Result** (`plots/e4_block_size.png`; means per selectivity bucket, three block sizes only):

  | Bucket | Blocks touched, B = 1k / 5k / 20k | Rows read per matching row, 1k / 5k / 20k |
  |---|---|---|
  | <0.5% | 1.4 / 1.0 / 1.0 | 3.1 / 12.0 / 46.3 (worst query 5.7 / 28.4 / 68.0) |
  | 0.5–2% | 4.5 / 2.5 / 1.7 | 2.3 / 6.7 / 17.3 |
  | 2–5% | 12.8 / 5.6 / 2.8 | 1.7 / 3.8 / 8.0 |
  | 5–15% | 30.7 / 11.2 / 4.6 | 1.6 / 2.9 / 4.9 |
  | >15% | 71.5 / 20.8 / 7.0 | 1.3 / 2.0 / 2.7 |

  - Total metadata: 108.2 KB at B = 1k, 21.6 KB at 5k and 5.4 KB at 20k. The centroid and radius
    are 96% of it.
  - All as predicted. The worst query at B = 20k reads 68× more rows than it needs, exactly the
    predicted 68× for the 294-row tenant. At B = 1k the worst case is 5.7×, not 3.4×, because a
    small tenant can straddle two blocks. Recall was 1.00 everywhere.
- **Takeaway:**
  - Block size trades invocations against wasted reads. The trade is worst for selective queries:
    going from 1k to 20k saves almost no invocations at <0.5% selectivity (1.4 → 1.0) but
    multiplies wasted reads by 15.
  - For broad queries, larger blocks cut invocations 10× (71.5 → 7.0) for only 2× more reads.
  - So the best B depends on the query mix. A cost model (section 11) would pick it.

---

## 9. Surprises

Results that contradicted a prediction, or that need a caveat when read.

- **The data is easy.** Clusters never mix: rows are about 4.0 from their own centre and at least
  7.6 from any other. A query's 10 nearest rows almost always come from one cluster, so ranking
  blocks by centroid (E3) will look better here than on real embeddings. Keep this in mind when
  reading E3.
- **With Zipf, cluster sizes are very uneven,** from 684 to 16,959 rows. The largest tenant has
  46,751 rows and puts them into only 3 home clusters. This will affect `vector_clustered`, where
  k-means looks for 40 clusters in 64 clusters of very different sizes.
- **With uniform tenants, only four selectivity buckets have queries,** because every query matches
  exactly 1, 3, 10 or 25% of rows. Use Zipf for per-bucket comparisons that need all five.
- **`vector_clustered` blocks are only partly clustered.** There are 64 true clusters but only 40
  blocks, so each block mixes about 2 clusters: only 57% of a block's rows come from its main
  cluster, and rows are only 25% closer to their block's centre than in `random` (6.65 vs 8.86).
  Even with 40 true clusters for 40 blocks the share is only 73%, because cutting into equal-size
  blocks crosses cluster edges (the D3 trade-off). Blocks are therefore wide, and the lower bound
  `‖q − c‖ − r` will often be 0, so expect the early stop in E3 to skip few blocks.
- **The early stop skips nothing on the default data.** Measured with 20,000 rows, blocks of
  1,000 and 30 queries:

  | Layout | Blocks with lower bound 0 | Blocks skipped per query |
  |---|---|---|
  | `random` | 100% | 0 |
  | `tenant_sorted` | 100% | 0 |
  | `vector_clustered` | 81% | 0 |

  Blocks are so wide that the query sits inside almost every block's ball, so the bound says
  nothing. It is still correct; it just never helps here. Expect E3 to show no saving from the
  early stop unless blocks are tighter (fewer true clusters per block, or less noise).
- **Correction from E3 (full size): the early stop does skip blocks on `vector_clustered` at
  `rho` = 0.8.** It skipped 13% of the surviving blocks (5.2 per query, in 92% of queries) with
  recall 1.00. At `rho` = 0 it skipped almost nothing. The measurement above was on a small setup
  (20,000 rows, 20 blocks of 1,000), where blocks mix more clusters. Likely reason `rho` matters
  (not checked; measuring the 10th-best distance at both `rho` would test it): at 0.8 many
  matching rows sit in the query's own cluster, so the 10th-best distance is small, and more
  blocks have a lower bound above it. At `rho` = 0 the matching rows are spread over all clusters,
  the 10th-best distance is larger, and almost no bound exceeds it. Lesson: a result measured on a
  small setup did not carry over to full size.
- **E2: latency hides most of the pruning.** A block with no matching row costs about 0.06 ms to
  check, while a full scan of 40 blocks takes 2.7–42 ms, mostly spent on distances for matching
  rows. So 40× fewer blocks gives only 4–11× lower latency in memory (E2).
- **E3: the recall curve has a long tail.** On `vector_clustered`, recall goes from 0 to 0.9 in 3–4
  blocks, then from 0.93 to 0.98 over the next 16 blocks. Likely cause (not checked): a few of the
  top-10 rows are in blocks far down the centroid order, because their cluster is split across
  blocks that also hold other clusters, so those blocks' centroids sit far from the query.

---

## 10. Run provenance

For each run: the command, the commit and dirty flag from `results/run_config.json`, and the
`csv_hash` of each results file. Two runs of the same command on the same commit must give the same
hashes (D10).

| Run | Date and time | Command | Commit | Machine state | Results hashes (first 16 hex digits) | Notes |
|---|---|---|---|---|---|---|
| 1 | 18 Oct, 16:25–16:32 | `experiments.py`, then `plots.py`, with the project's `.venv` Python (same environment as `uv run python …`, section 6) | `7dcef8e`, clean | Windows 11, 1 thread; other load not recorded | e1_e2_per_query `2069b812bc63467c`, e1_e2_summary `d62291b3c49d847e`, e3_per_query `504ddde5b405146e`, e4_per_query `49f64d9e33102acf`, e4_metadata_size `5a4865092c876093` | 450 s. The results in sections 3 and 8. |
| 2 | 18 Oct, 16:35–16:42 | `.venv\Scripts\python experiments.py`, run from a scratch folder so it did not overwrite run 1 | `7dcef8e`, clean | Windows 11, 1 thread; the test suite ran at the same time for about 2 minutes | All five identical to run 1 | 444 s. D10 check at full size: passed. |
| 3 | 18 Oct, 17:02–17:12 | Fresh `git clone`, `uv sync --frozen`, `uv run --frozen pytest` (252 passed), `uv run --frozen python experiments.py` | `2afc6c8` (same code as `7dcef8e`), clean | Windows 11, 1 thread; the test suite ran at the same time | All five identical to run 1 | 610 s. D10 fresh-clone check: passed. |

Latency variation across runs with the same configuration:

- Runs 1 and 2, median latency per cell (72 cells): median change 1.9%, largest 9.2%. Median
  speedup per cell: median change 0.8%, largest 6.4% (Zipf, `tenant_sorted`, <0.5%: 10.6× and
  11.2×). Run 2 shared the machine with the test suite for part of its run. Speedups are therefore
  stable to within about ±6%. Differences smaller than that, for example 1.0× against 1.1×, should
  not be read as real.

---

## 11. Next steps

Ideas outside the time budget, collected as they come up:

- **Streaming ingestion and layout drift (E5):** sort each batch by tenant, LSM-style compaction.
- **Tenant-then-cluster layout:** keep lossless tenant pruning and add similarity locality inside
  large tenants.
- **Tighter similarity metadata:** per-(block, tenant) centroids or several sub-centroids per block,
  so the lower bound prunes.
- **ANN index per block** (FAISS HNSW or IVF), and how the filter interacts with the index.
- **Range and multi-attribute filters;** Bloom filters for high-cardinality attributes.
- **Cost model:** invocations × (fetch latency + bytes / bandwidth + compute), to choose B per
  workload.
- **Post-filter baseline,** skewed query popularity (hot blocks), real embeddings with real metadata.