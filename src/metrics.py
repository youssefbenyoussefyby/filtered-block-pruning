import time

import numpy as np
import pandas as pd

from src.search import search

BUCKET_EDGES = [0.0, 0.005, 0.02, 0.05, 0.15, 1.0]
BUCKET_LABELS = ["<0.5%", "0.5-2%", "2-5%", "5-15%", ">15%"]


def recall_at_k(found_ids, true_ids):
    if len(true_ids) == 0:
        return 1.0
    return len(np.intersect1d(found_ids, true_ids)) / len(true_ids)


def timed(fn, repeats):
    result = fn()
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return result, 1000 * float(np.median(times))


def measure(blocks, meta, queries, truth, methods, k=10, repeats=0):
    rows = []
    for qid, (query, true) in enumerate(zip(queries, truth)):
        for name, args in methods.items():
            run = lambda: search(blocks, query, meta, k=k, **args)
            res, ms = timed(run, repeats) if repeats else (run(), float("nan"))
            rows.append({
                "query": qid,
                "method": name,
                "selectivity": query.selectivity,
                "blocks_touched": res.blocks_touched,
                "frac_blocks": res.blocks_touched / len(blocks),
                "rows_read": res.rows_read,
                "distances_computed": res.distances_computed,
                "recall": recall_at_k(res.row_ids, true.row_ids),
                "latency_ms": ms,
            })
    df = pd.DataFrame(rows)
    df["bucket"] = pd.cut(df["selectivity"], BUCKET_EDGES, labels=BUCKET_LABELS, include_lowest=True)
    return df


def summarize(df, by=()):
    keys = list(by) + ["bucket"]
    return df.groupby(keys, observed=True).agg(
        queries=("query", "size"),
        frac_blocks=("frac_blocks", "mean"),
        invocations=("blocks_touched", "mean"), 
        rows_read=("rows_read", "mean"),
        distances_computed=("distances_computed", "mean"),
        recall=("recall", "mean"),
        p50_ms=("latency_ms", "median"),
        p95_ms=("latency_ms", lambda s: s.quantile(0.95)),
    ).reset_index()
