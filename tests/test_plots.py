import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import plots
from src.metrics import BUCKET_LABELS

SERIES = [("random", 0.8), ("tenant_sorted", 0.8), ("vector_clustered", 0.8), ("vector_clustered", 1.0)]
LAYOUT_CODE = {"random": 0, "tenant_sorted": 1, "vector_clustered": 2}


def buckets_for(dist):
    return BUCKET_LABELS[1:] if dist == "uniform" else BUCKET_LABELS


def frac_value(dist, pruner, layout, rho, bucket):
    return round(0.1 * LAYOUT_CODE[layout] + 0.02 * BUCKET_LABELS.index(bucket) + 0.01 * (pruner == "zonemap") + 0.005 * (dist == "zipf") + 0.001 * (rho == 1.0), 4)


def make_summary():
    rows = []
    for dist in ("uniform", "zipf"):
        for pruner in ("none", "zonemap", "tenant_set"):
            for layout, rho in SERIES:
                for bucket in buckets_for(dist):
                    frac = 1.0 if pruner == "none" else frac_value(dist, pruner, layout, rho, bucket)
                    rows.append(dict(dist=dist, pruner=pruner, layout=layout, rho=rho, bucket=bucket, queries=40,
                                     frac_blocks=frac, recall=1.0, speedup_p50=0.5 / frac, blocks_ratio_p50=1 / frac))
    return pd.DataFrame(rows)


def make_per_query():
    rows = []
    for dist in ("uniform", "zipf"):
        for layout, rho in SERIES:
            for q, bucket in enumerate(buckets_for(dist)):
                rows.append(dict(query=q, dist=dist, pruner="none", layout=layout, rho=rho, bucket=bucket,
                                 ideal_frac=0.01 * (q + 1)))
    return pd.DataFrame(rows)


def make_e3():
    rows = []
    for rho in (0.0, 0.8):
        for layout in LAYOUT_CODE:
            for q in range(3):
                for order in ("tenant_set_by_centroid", "tenant_set_by_bound"):
                    for m in range(1, 41):
                        rows.append(dict(query=q, rho=rho, layout=layout, order=order, m=m, bucket="2-5%",
                                         frac_blocks=m / 40, recall=min(1.0, m / (5 if order.endswith("centroid") else 40))))
                rows.append(dict(query=q, rho=rho, layout=layout, order="early_stop", m=np.nan, bucket="2-5%",
                                 frac_blocks=1.0, recall=1.0))
    return pd.DataFrame(rows)


def make_e4():
    rows = []
    for size in (1_000, 2_000, 5_000, 10_000, 20_000):
        for bucket in BUCKET_LABELS:
            rows.append(dict(query=0, block_size=size, bucket=bucket, blocks_touched=200_000 / size / 10,
                             read_amplification=size / 1_000))
    return pd.DataFrame(rows)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    results, out = tmp_path / "results", tmp_path / "plots"
    results.mkdir()
    out.mkdir()
    make_summary().to_csv(results / "e1_e2_summary.csv", index=False)
    make_per_query().to_csv(results / "e1_e2_per_query.csv", index=False)
    make_e3().to_csv(results / "e3_per_query.csv", index=False)
    make_e4().to_csv(results / "e4_per_query.csv", index=False)
    monkeypatch.setattr(plots, "RESULTS", results)
    monkeypatch.setattr(plots, "PLOTS", out)
    return tmp_path


@pytest.fixture
def captured(monkeypatch):
    figures = {}
    monkeypatch.setattr(plots, "save", lambda fig, name: figures.__setitem__(name, fig))
    return figures


def inputs():
    summary, per_query = plots.load("e1_e2_summary.csv"), plots.load("e1_e2_per_query.csv")
    series = list(per_query[["layout", "rho"]].drop_duplicates().itertuples(index=False, name=None))
    styles = plots.layout_styles(dict.fromkeys(layout for layout, _ in series))
    return summary, per_query, series, styles


def line(ax, label):
    matches = [l for l in ax.get_lines() if l.get_label() == label]
    assert len(matches) == 1, f"expected one line labelled {label!r}"
    return matches[0]




def test_load_orders_buckets_from_lowest_to_highest_selectivity(workdir):
    df = plots.load("e1_e2_summary.csv")
    assert list(df.bucket.cat.categories) == BUCKET_LABELS
    assert df.bucket.cat.ordered
    assert df.bucket.cat.codes.is_monotonic_increasing


def test_series_are_layout_and_rho_pairs(workdir):
    _, _, series, styles = inputs()
    assert set(series) == set(SERIES)
    assert set(styles) == set(LAYOUT_CODE)




def test_e1_plots_the_right_cell_in_each_panel(workdir, captured):
    summary, per_query, series, styles = inputs()
    plots.fig_e1(summary, per_query, styles, series)
    axes = captured["e1_blocks_scanned.png"].axes
    panels = {(0, 0): ("zonemap", "uniform"), (0, 1): ("zonemap", "zipf"),
              (1, 0): ("tenant_set", "uniform"), (1, 1): ("tenant_set", "zipf")}
    for (row, col), (pruner, dist) in panels.items():
        ax = axes[2 * row + col]
        assert pruner in ax.get_title() and dist in ax.get_title()
        for layout, rho in series:
            got = line(ax, plots.series_label(layout, rho))
            expected = [frac_value(dist, pruner, layout, rho, b) for b in buckets_for(dist)]
            assert np.allclose(got.get_ydata(), expected)
            assert list(got.get_xdata()) == [BUCKET_LABELS.index(b) for b in buckets_for(dist)]


def test_e1_ideal_line_is_the_mean_per_bucket(workdir, captured):
    summary, per_query, series, styles = inputs()
    plots.fig_e1(summary, per_query, styles, series)
    ideal = line(captured["e1_blocks_scanned.png"].axes[0], "ideal (matching rows packed)")
    assert np.allclose(ideal.get_ydata(), [0.01 * (q + 1) for q in range(4)])


def test_e2_plots_speedup_and_blocks_ratio_for_tenant_set(workdir, captured):
    summary, per_query, series, styles = inputs()
    plots.fig_e2(summary, styles, series)
    ax = captured["e2_speedup.png"].axes[0]
    speed = line(ax, "tenant_sorted")
    expected = [frac_value("uniform", "tenant_set", "tenant_sorted", 0.8, b) for b in buckets_for("uniform")]
    assert np.allclose(speed.get_ydata(), [0.5 / f for f in expected])
    ratios = [l for l in ax.get_lines() if l.get_linestyle() == ":" and np.allclose(l.get_ydata(), [1 / f for f in expected])]
    assert len(ratios) == 1


def test_e3_curves_are_ordered_by_m_and_averaged_over_queries(workdir, captured):
    _, _, _, styles = inputs()
    e3 = plots.load("e3_per_query.csv")
    e3.loc[(e3["query"] == 2) & (e3.order == "tenant_set_by_centroid"), "recall"] = 0.0
    plots.fig_e3(e3, styles)
    ax = captured["e3_recall_vs_blocks.png"].axes[0]
    centroid = line(ax, "tenant_sorted")
    assert np.all(np.diff(centroid.get_xdata()) > 0)
    assert np.allclose(centroid.get_ydata(), [min(1.0, m / 5) * 2 / 3 for m in range(1, 41)])


def test_e3_shows_the_early_stop_point(workdir, captured):
    _, _, _, styles = inputs()
    plots.fig_e3(plots.load("e3_per_query.csv"), styles)
    stars = [l for l in captured["e3_recall_vs_blocks.png"].axes[0].get_lines() if l.get_marker() == "*"]
    assert len(stars) >= len(LAYOUT_CODE)
    assert all(np.allclose(s.get_xdata(), [1.0]) and np.allclose(s.get_ydata(), [1.0]) for s in stars[:len(LAYOUT_CODE)])


def test_e4_plots_one_line_per_bucket_against_block_size(workdir, captured):
    plots.fig_e4(plots.load("e4_per_query.csv"))
    left, right = captured["e4_block_size.png"].axes
    assert len(left.get_lines()) == len(right.get_lines()) == len(BUCKET_LABELS)
    first = left.get_lines()[0]
    assert list(first.get_xdata()) == [1_000, 2_000, 5_000, 10_000, 20_000]
    assert np.allclose(right.get_lines()[0].get_ydata(), [1, 2, 5, 10, 20])




def test_summary_table_has_every_series_and_bucket(workdir):
    summary, per_query, series, _ = inputs()
    plots.write_tables(summary, plots.load("e3_per_query.csv"), series)
    text = (workdir / "results" / "summary_table.md").read_text(encoding="utf-8")
    full = text.split("## Full E1/E2 table")[1]
    rows = [r for r in full.splitlines() if r.startswith("| uniform") or r.startswith("| zipf")]
    assert len(rows) == len(SERIES) * (len(buckets_for("uniform")) + len(buckets_for("zipf")))
    v = frac_value("zipf", "tenant_set", "tenant_sorted", 0.8, ">15%")
    assert f"| zipf | tenant_sorted | >15% | 40 | " in full
    assert f"{v:.2f}" in full




def test_running_the_module_writes_four_figures_and_the_table(workdir):
    repo = Path(__file__).resolve().parent.parent
    done = subprocess.run([sys.executable, str(repo / "plots.py")], cwd=workdir, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(repo)})
    assert done.returncode == 0, done.stderr
    for name in ("e1_blocks_scanned.png", "e2_speedup.png", "e3_recall_vs_blocks.png", "e4_block_size.png"):
        data = (workdir / "plots" / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 10_000
    assert (workdir / "results" / "summary_table.md").exists()
