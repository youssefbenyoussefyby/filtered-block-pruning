from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D

from src.metrics import BUCKET_LABELS

RESULTS, PLOTS = Path("results"), Path("plots")
NUM_BLOCKS = 40 
DEFAULT_RHO = 0.8
plt.rcParams.update({"axes.grid": True, "grid.alpha": 0.3, "font.size": 9})


def layout_styles(layouts):
    colours = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    markers = "os^Dvp"
    return {layout: dict(color=colours[i % len(colours)], marker=markers[i % len(markers)])
            for i, layout in enumerate(layouts)}


def series_label(layout, rho):
    return layout if rho == DEFAULT_RHO else f"{layout} (rho={rho:g})"


def series_style(styles, layout, rho):
    if rho == DEFAULT_RHO:
        return styles[layout]
    return dict(styles[layout], linestyle="--", markerfacecolor="white")


def bucket_axis(ax):
    ax.set_xticks(range(len(BUCKET_LABELS)), BUCKET_LABELS)
    ax.set_xlabel("filter selectivity (fraction of rows matching)")


def bucket_x(df):
    return df.bucket.cat.codes


def load(name):
    df = pd.read_csv(RESULTS / name)
    if "bucket" in df:
        df["bucket"] = pd.Categorical(df.bucket, BUCKET_LABELS, ordered=True)
        df = df.sort_values("bucket", kind="stable")
    return df


def save(fig, name):
    fig.savefig(PLOTS / name, dpi=150)
    plt.close(fig)
    print(f"wrote plots/{name}")


def fig_e1(summary, per_query, styles, series):
    fig, axes = plt.subplots(2, 2, figsize=(9, 6.6), sharex=True, sharey=True, layout="constrained")
    for row, pruner in enumerate(("zonemap", "tenant_set")):
        for col, dist in enumerate(("uniform", "zipf")):
            ax = axes[row, col]
            ideal = per_query[(per_query.dist == dist) & (per_query.pruner == "none")]
            ideal = ideal.groupby("bucket", observed=True).ideal_frac.mean()
            ax.plot(ideal.index.codes, ideal.values, color="grey", linestyle=":", label="ideal (matching rows packed)")
            for layout, rho in series:
                s = summary[(summary.dist == dist) & (summary.pruner == pruner)
                            & (summary.layout == layout) & (summary.rho == rho)]
                ax.plot(bucket_x(s), s.frac_blocks, label=series_label(layout, rho),
                        **series_style(styles, layout, rho))
            ax.set_title(f"{pruner} metadata · {dist} tenants")
            ax.set_ylim(0, 1.05)
            if col == 0:
                ax.set_ylabel(f"blocks scanned (fraction of {NUM_BLOCKS})")
            if row == 1:
                bucket_axis(ax)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=5)
    fig.suptitle("E1 · Attribute pruning: fraction of blocks scanned, by layout (rho = 0.8 unless noted)")
    save(fig, "e1_blocks_scanned.png")


def fig_e2(summary, styles, series):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.9), sharey=True, layout="constrained")
    for ax, dist in zip(axes, ("uniform", "zipf")):
        for layout, rho in series:
            s = summary[(summary.dist == dist) & (summary.pruner == "tenant_set") & (summary.layout == layout) & (summary.rho == rho)]
            style = series_style(styles, layout, rho)
            ax.plot(bucket_x(s), s.speedup_p50, label=series_label(layout, rho), **style)
            ax.plot(bucket_x(s), s.blocks_ratio_p50, color=style["color"], linestyle=":")
        ax.axhline(1, color="grey", linewidth=1)
        ax.set_yscale("log")
        ax.set_yticks([0.5, 1, 2, 5, 10, 20, 40], ["0.5x", "1x", "2x", "5x", "10x", "20x", "40x"])
        ax.minorticks_off()
        ax.set_title(f"tenant_set metadata · {dist} tenants")
        bucket_axis(ax)
    axes[0].set_ylabel("ratio to full scan (same layout)")
    handles, labels = axes[0].get_legend_handles_labels()
    handles += [Line2D([], [], color="black"), Line2D([], [], color="black", linestyle=":")]
    labels += ["latency speedup (median per query)", "blocks ratio full / touched (median per query)"]
    fig.legend(handles, labels, loc="outside lower center", ncol=3)
    fig.suptitle("E2 · Attribute pruning: in-memory latency speedup vs. blocks-skipped ratio")
    save(fig, "e2_speedup.png")


def fig_e3(e3, styles):
    curves = e3.groupby(["rho", "layout", "order", "m"], dropna=False)[["frac_blocks", "recall"]].mean().reset_index()
    fig, axes = plt.subplots(1, 2, figsize=(9, 4.0), sharey=True, layout="constrained")
    for ax, rho in zip(axes, (0.0, 0.8)):
        for layout, style in styles.items():
            c = curves[(curves.rho == rho) & (curves.layout == layout)]
            cen = c[c.order == "tenant_set_by_centroid"].sort_values("m")
            bnd = c[c.order == "tenant_set_by_bound"].sort_values("m")
            stop = c[c.order == "early_stop"]
            ax.plot(cen.frac_blocks, cen.recall, label=layout, **style)
            ax.plot(bnd.frac_blocks, bnd.recall, color=style["color"], linestyle="--", linewidth=1)
            ax.plot(stop.frac_blocks, stop.recall, linestyle="none", marker="*", markersize=13,
                    color=style["color"], markeredgecolor="white")
        ax.set_title(f"rho = {rho:g}" + (" (tenant independent of vector)" if rho == 0 else " (tenants have home clusters)"))
        ax.set_xlabel(f"blocks scanned (fraction of {NUM_BLOCKS})")
        ax.set_xlim(0, 1.02)
        ax.set_ylim(0, 1.05)
    axes[0].set_ylabel("recall@10")
    handles, labels = axes[0].get_legend_handles_labels()
    handles += [Line2D([], [], color="black"), Line2D([], [], color="black", linestyle="--", linewidth=1),
                Line2D([], [], color="black", linestyle="none", marker="*", markersize=11)]
    labels += ["nearest-centroid order", "lower-bound order", "lossless early stop"]
    fig.legend(handles, labels, loc="outside lower center", ncol=3)
    fig.suptitle("E3 · Similarity pruning: recall@10 vs. blocks scanned, m = 1…40 (Zipf tenants, tenant_set pruning first)")
    save(fig, "e3_recall_vs_blocks.png")


def fig_e4(e4):
    agg = e4.groupby(["bucket", "block_size"], observed=True)[["blocks_touched", "read_amplification"]].mean().reset_index()
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.9), layout="constrained")
    colours = plt.cm.Blues([0.4, 0.55, 0.7, 0.85, 1.0])
    for colour, bucket in zip(colours, BUCKET_LABELS):
        s = agg[agg.bucket == bucket].sort_values("block_size")
        axes[0].plot(s.block_size, s.blocks_touched, color=colour, marker="o", label=f"selectivity {bucket}")
        axes[1].plot(s.block_size, s.read_amplification, color=colour, marker="o")
    for ax in axes:
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xticks([1_000, 5_000, 20_000], ["1k", "5k", "20k"])
        ax.set_yticks([1, 2, 5, 10, 20, 50, 100], ["1", "2", "5", "10", "20", "50", "100"])
        ax.minorticks_off()
        ax.set_xlabel("block size B (rows per block)")
    axes[0].set_ylabel("blocks touched = invocations (mean)")
    axes[1].set_ylabel("rows read / rows matching the filter")
    axes[0].set_title("blocks touched per query")
    axes[1].set_title("read amplification")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=5)
    fig.suptitle("E4 · Block size on tenant_sorted layout (Zipf tenants, rho = 0.8, tenant_set pruning)")
    save(fig, "e4_block_size.png")


def write_tables(summary, e3, series):
    def cells(values, fmt):
        return " | ".join(fmt.format(values[b]) if b in values.index else "-" for b in BUCKET_LABELS)

    zipf = summary[summary.dist == "zipf"]
    centroid_m2 = e3[(e3.order == "tenant_set_by_centroid") & (e3.m == 2)]
    at_m2 = centroid_m2.groupby(["rho", "layout", "bucket"], observed=True).recall.mean()
    out = ["## Zipf tenants, rho = 0.8 unless noted (E1/E2 + E3 at m = 2)", "",
           "| layout | metric | " + " | ".join(BUCKET_LABELS) + " |", "|---|---|" + "---|" * len(BUCKET_LABELS)]
    for layout, rho in series:
        s = zipf[(zipf.layout == layout) & (zipf.rho == rho)]
        zm = s[s.pruner == "zonemap"].set_index("bucket")
        ts = s[s.pruner == "tenant_set"].set_index("bucket")
        out.append(f"| {series_label(layout, rho)} | blocks scanned, zonemap | {cells(zm.frac_blocks, '{:.2f}')} |")
        out.append(f"| | blocks scanned, tenant_set | {cells(ts.frac_blocks, '{:.2f}')} |")
        out.append(f"| | p50 blocks ratio full / touched, tenant_set | {cells(ts.blocks_ratio_p50, '{:.1f}×')} |")
        out.append(f"| | p50 latency speedup, tenant_set | {cells(ts.speedup_p50, '{:.1f}×')} |")
        if (rho, layout) in at_m2.index.droplevel("bucket"):
            out.append(f"| | recall@10, 2 nearest surviving blocks | {cells(at_m2.loc[(rho, layout)], '{:.2f}')} |")
    attr = summary[summary.pruner != "none"]
    out += ["", f"Attribute pruning (zonemap, tenant_set) recall@10: min {attr.recall.min():.2f} over all cells.", ""]

    out += ["## Full E1/E2 table", "",
            "| tenants | layout | selectivity | queries | scanned (zonemap) | scanned (tenant_set) | "
            "recall@10 | p50 latency speedup (tenant_set) | p50 blocks ratio full / touched (tenant_set) |",
            "|---|---|---|---|---|---|---|---|---|"]
    for dist, (layout, rho) in [(d, s) for d in ("uniform", "zipf") for s in series]:
        s = summary[(summary.dist == dist) & (summary.layout == layout) & (summary.rho == rho)]
        zm = s[s.pruner == "zonemap"].set_index("bucket")
        ts = s[s.pruner == "tenant_set"].set_index("bucket")
        for b in [b for b in BUCKET_LABELS if b in ts.index]:
            out.append(f"| {dist} | {series_label(layout, rho)} | {b} | {ts.queries[b]} | {zm.frac_blocks[b]:.2f} | "
                       f"{ts.frac_blocks[b]:.2f} | {min(zm.recall[b], ts.recall[b]):.2f} | {ts.speedup_p50[b]:.1f}× | "
                       f"{ts.blocks_ratio_p50[b]:.1f}× |")
    (RESULTS / "summary_table.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("wrote results/summary_table.md")


if __name__ == "__main__":
    PLOTS.mkdir(exist_ok=True)
    summary, per_query = load("e1_e2_summary.csv"), load("e1_e2_per_query.csv")
    series = list(per_query[["layout", "rho"]].drop_duplicates().itertuples(index=False, name=None))
    styles = layout_styles(dict.fromkeys(layout for layout, _ in series))
    fig_e1(summary, per_query, styles, series)
    fig_e2(summary, styles, series)
    e3 = load("e3_per_query.csv")
    fig_e3(e3, styles)
    fig_e4(load("e4_per_query.csv"))
    write_tables(summary, e3, series)
