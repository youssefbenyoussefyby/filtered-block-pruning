import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_var] = "1"  

import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

from src.data import make_dataset, make_queries
from src.layout import LAYOUTS, build_blocks
from src.metadata import build_metadata, bytes_per_block
from src.metrics import measure, summarize
from src.search import PRUNERS, search

RESULTS = Path("results")
DATA = dict(n=200_000, dim=64, num_clusters=64, num_tenants=100, zipf_s=1.1,
            home_clusters_per_tenant=3, centre_std=1.0, noise_std=0.5, seed=0)
QUERIES = dict(num_queries=200, in_list_sizes=(1, 3, 10, 25), seed=1)
N, K, BLOCK_SIZE, REPEATS = DATA["n"], 10, 5_000, 3
M_VALUES = (1, 2, 3, 4, 6, 8, 12, 16, 24, 40)
E4_BLOCK_SIZES = (1_000, 5_000, 20_000)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def git_commit():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip()
        return out.stdout.strip() + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_run_config(started, elapsed_s, commit, experiments):
    config = {
        "started": started,
        "elapsed_s": round(elapsed_s),
        "git_commit": commit,
        "experiments": experiments,
        "data": DATA,
        "queries": QUERIES,
        "k": K,
        "block_size": BLOCK_SIZE,
        "timing_repeats": REPEATS,
        "e3_m_values": M_VALUES,
        "e4_block_sizes": E4_BLOCK_SIZES,
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "pandas": pd.__version__, "scikit-learn": sklearn.__version__},
        "platform": platform.platform(),
    }
    (RESULTS / "run_config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def prepare(dist, rho, block_size=BLOCK_SIZE, layouts=tuple(LAYOUTS)):
    ds = make_dataset(tenant_dist=dist, rho=rho, **DATA)
    queries = make_queries(ds, **QUERIES)
    built = {}
    for layout in layouts:
        blocks, build_s = build_blocks(ds, layout, block_size)
        built[layout] = (blocks, build_metadata(blocks, ds.num_tenants), build_s)
    blocks, meta, _ = built[layouts[0]]
    truth = [search(blocks, q, meta, "none", K) for q in queries]
    return ds, queries, built, truth


def e1_e2():
    frames, builds = [], []
    for dist in ("uniform", "zipf"):
        for rho, layouts in ((0.8, tuple(LAYOUTS)), (1.0, ("vector_clustered",))):
            _, queries, built, truth = prepare(dist, rho, layouts=layouts)
            for layout, (blocks, meta, build_s) in built.items():
                builds.append({"dist": dist, "rho": rho, "layout": layout,
                               "num_blocks": len(blocks), "build_s": build_s})
                timed = measure(blocks, meta, queries, truth,
                                {p: {"pruner": p} for p in ("none", "tenant_set")}, K, repeats=REPEATS)
                untimed = measure(blocks, meta, queries, truth, {"zonemap": {"pruner": "zonemap"}}, K)
                frames.append(pd.concat([timed, untimed]).rename(columns={"method": "pruner"})
                              .assign(dist=dist, rho=rho, layout=layout))
                log(f"E1/E2 {dist} rho={rho} {layout}: build {build_s:.2f}s")
    per_query = pd.concat(frames, ignore_index=True)
    per_query["ideal_frac"] = np.ceil(per_query.selectivity * N / BLOCK_SIZE) / (N // BLOCK_SIZE)
    ids = ["dist", "rho", "layout", "query"]
    full = per_query[per_query.pruner == "none"][ids + ["latency_ms"]]
    per_query = per_query.merge(full.rename(columns={"latency_ms": "full_scan_ms"}), on=ids)
    per_query["speedup"] = per_query.full_scan_ms / per_query.latency_ms
    per_query["blocks_ratio"] = 1 / per_query.frac_blocks  # the full scan touches every block
    per_query.to_csv(RESULTS / "e1_e2_per_query.csv", index=False)
    pd.DataFrame(builds).to_csv(RESULTS / "layout_build.csv", index=False)

    by = ["dist", "rho", "layout", "pruner"]
    summary = summarize(per_query, by=by)
    medians = per_query.groupby(by + ["bucket"], observed=True)[["speedup", "blocks_ratio"]].median()
    summary = summary.merge(medians.add_suffix("_p50").reset_index(), on=by + ["bucket"])
    summary.to_csv(RESULTS / "e1_e2_summary.csv", index=False)


def e3():
    frames = []
    for rho in (0.0, 0.8):
        _, queries, built, truth = prepare("zipf", rho)
        for layout, (blocks, meta, _) in built.items():
            for order in ("tenant_set_by_centroid", "tenant_set_by_bound"):
                methods = {m: {"pruner": order, "max_blocks": m} for m in M_VALUES}
                df = measure(blocks, meta, queries, truth, methods, K)
                frames.append(df.rename(columns={"method": "m"}).assign(rho=rho, layout=layout, order=order))
            stop = {"early_stop": {"pruner": "tenant_set_by_centroid", "early_stop": True}}
            df = measure(blocks, meta, queries, truth, stop, K)
            frames.append(df.drop(columns="method").assign(rho=rho, layout=layout, order="early_stop", m=np.nan))
            log(f"E3 rho={rho} {layout}")
    pd.concat(frames, ignore_index=True).to_csv(RESULTS / "e3_per_query.csv", index=False)


def e4():
    frames, sizes = [], []
    for block_size in E4_BLOCK_SIZES:
        ds, queries, built, truth = prepare("zipf", 0.8, block_size=block_size, layouts=("tenant_sorted",))
        blocks, meta, _ = built["tenant_sorted"]
        df = measure(blocks, meta, queries, truth, {"tenant_set": {"pruner": "tenant_set"}}, K)
        frames.append(df.assign(block_size=block_size, num_blocks=len(blocks)))
        per_block = bytes_per_block(ds.num_tenants, ds.vectors.shape[1])
        sizes.append({"block_size": block_size, "num_blocks": len(blocks),
                      **{f"{kind}_bytes_total": b * len(blocks) for kind, b in per_block.items()}})
        log(f"E4 B={block_size}")
    per_query = pd.concat(frames, ignore_index=True)
    per_query["read_amplification"] = per_query.rows_read / (per_query.selectivity * N)
    per_query.to_csv(RESULTS / "e4_per_query.csv", index=False)
    pd.DataFrame(sizes).to_csv(RESULTS / "e4_metadata_size.csv", index=False)


EXPERIMENTS = {"e1_e2": e1_e2, "e3": e3, "e4": e4}

if __name__ == "__main__":
    names = sys.argv[1:] or list(EXPERIMENTS)
    if not set(names) <= set(EXPERIMENTS):
        sys.exit(f"usage: python experiments.py [{'] ['.join(EXPERIMENTS)}]")
    RESULTS.mkdir(exist_ok=True)
    commit = git_commit()  
    started, start = time.strftime("%Y-%m-%d %H:%M:%S"), time.perf_counter()
    for name in names:
        t = time.perf_counter()
        EXPERIMENTS[name]()
        log(f"{name} done in {time.perf_counter() - t:.0f}s")
    write_run_config(started, time.perf_counter() - start, commit, names)
    log(f"all experiments done in {time.perf_counter() - start:.0f}s; config in results/run_config.json")
