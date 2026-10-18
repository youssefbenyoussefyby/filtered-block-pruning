
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
PACKAGES = ("numpy", "pandas", "scikit-learn", "scipy", "matplotlib")
TIMING_COLUMNS = ("latency_ms", "p50_ms", "p95_ms", "build_s", "full_scan_ms", "speedup", "speedup_p50")


def limit_threads(n=1):
    for var in THREAD_VARS:
        os.environ[var] = str(n)
    from threadpoolctl import threadpool_limits
    return threadpool_limits(limits=n)


def git_commit():
    root = Path(__file__).resolve().parent.parent
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}
    return {"commit": commit, "dirty": bool(status.strip())}


def run_config(**params):
    from threadpoolctl import threadpool_info
    return {
        "params": params,
        "git": git_commit(),
        "python": sys.version.split()[0],
        "packages": {p: version(p) for p in PACKAGES},
        "platform": platform.platform(),
        "processor": platform.processor(),
        "threads": sorted({info["num_threads"] for info in threadpool_info()}),
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_run_config(path, **params):
    config = run_config(**params)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(config, indent=2, default=str))
    return config


def table_hash(df, drop=TIMING_COLUMNS):
    kept = df.drop(columns=[c for c in drop if c in df.columns])
    return hashlib.sha256(kept.to_csv(index=False).encode()).hexdigest()


def csv_hash(path, drop=TIMING_COLUMNS):
    import pandas as pd
    return table_hash(pd.read_csv(path), drop)
