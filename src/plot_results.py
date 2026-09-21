import sys
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from rich import print
from matplotlib.colors import LogNorm
from matplotlib.ticker import ScalarFormatter

# Global plotting config
sns.set_theme(
    style="whitegrid",
    font_scale=1.05,
)

plt.rcParams.update({
    "axes.titleweight": "bold",
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
})


# Small helpers
def has_data(df, col):
    """True if `col` exists and has at least one non-null value."""
    return col in df.columns and df[col].notna().any()


def empty_panel(ax, message):
    """Render a placeholder message when no plot data is available."""
    ax.text(
        0.5, 0.5, message, ha="center", va="center",
        transform=ax.transAxes, fontsize=10, color="0.4", wrap=True,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def save_figure(fig, out_dir, filename):
    """Save a figure as PDF and PNG."""
    fig.tight_layout()
    fig.savefig(f"{out_dir}/{filename}.pdf", bbox_inches="tight")
    fig.savefig(f"{out_dir}/{filename}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


# Data loading
def load(csv_path):
    df = pd.read_csv(csv_path)

    column_aliases = {
        "is_reached": "reached",
        "interactions_to_first_execution": "interactions_to_first_execution",
        "requests_to_first_hit": "interactions_to_first_execution",
    }

    df = df.rename(columns={
        old: new for old, new in column_aliases.items()
        if old in df.columns and new not in df.columns
    })

    if "reached" in df.columns:
        df["reached"] = df["reached"].map(
            lambda x: True if str(x).lower() == "true"
            else (False if str(x).lower() == "false" else np.nan)
        )

    if "interactions_to_first_execution" in df.columns:
        df["interactions_to_first_execution"] = pd.to_numeric(
            df["interactions_to_first_execution"], errors="coerce",
        )

    if "mutant_id" not in df.columns:
        raise ValueError("Input CSV does not contain the required 'mutant_id' column.")

    df = df[df["mutant_id"].notna()].copy()
    return df


def plot_mutation_target_reachability(df, out_dir):
    """Figure 1: Overall mutation target reachability per testing tool."""
    required = {"tool", "api", "reached"}
    if not required.issubset(df.columns):
        print(f"[red]Skipping mutation_target_reachability: missing columns {sorted(required - set(df.columns))}.[/red]")
        return

    overall = df.groupby("tool")["reached"].mean().mul(100)
    per_api = df.groupby(["tool", "api"])["reached"].mean().mul(100).reset_index(name="reachability")
    order = overall.sort_values(ascending=False).index
    stats = per_api.groupby("tool")["reachability"].agg(["min", "max"]).reindex(order)
    total = df.groupby("tool").size()
    x = np.arange(len(order))

    fig, ax = plt.subplots(figsize=(9, 5.5))
    palette = sns.color_palette("crest", len(order))

    ax.bar(x, overall.reindex(order), width=0.55, color=palette, edgecolor="black", linewidth=0.7)

    ax.vlines(x, stats["min"], stats["max"], color="0.25", linewidth=2, zorder=3)
    ax.scatter(x, stats["min"], color="0.25", s=25, zorder=4)
    ax.scatter(x, stats["max"], color="0.25", s=25, zorder=4)

    for i, tool in enumerate(order):
        value = overall.loc[tool]
        ax.text(i, value + 2, f"{value:.1f}%", ha="center", va="bottom", fontsize=9)

    ax.set_ylabel("Mutant Coverage (activation) (%)")
    ax.set_xlabel("")
    ax.set_ylim(0, 105)
    ax.set_title("Mutant Coverage (activation) by tool")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{tool}\n(n={total[tool]})" for tool in order], fontsize=8)
    ax.grid(axis="y", alpha=0.25)

    save_figure(fig, out_dir, "mutation_coverage")


def plot_ife_curve(df, out_dir):
    """Figure 2: Cumulative fraction of mutation campaigns by interaction budget."""
    if not has_data(df, "interactions_to_first_execution"):
        print("[yellow]Skipping ife_curve: no interactions_to_first_execution data available.[/yellow]")
        return

    required = {"tool", "reached"}
    if not required.issubset(df.columns):
        print("[red]Skipping ife_curve: missing required columns.[/red]")
        return

    df_r = df[df["reached"] == True]
    if df_r.empty:
        print("[yellow]Skipping ife_curve: no reached campaigns.[/yellow]")
        return

    medians = df_r.groupby("tool")["interactions_to_first_execution"].median().sort_values()
    order = medians.index
    palette = sns.color_palette("tab10", len(order))

    fig, ax = plt.subplots(figsize=(9.5, 5.2))

    for tool, color in zip(order, palette):
        group = df[df["tool"] == tool]
        total_campaigns = len(group)
        if total_campaigns == 0: continue

        vals = np.sort(group.loc[group["reached"] == True, "interactions_to_first_execution"].dropna().values)
        if len(vals) == 0: continue

        ys = np.arange(1, len(vals) + 1) / total_campaigns
        ax.step(vals, ys, where="post", linewidth=2, color=color, label=f"{tool} (med={medians.loc[tool]:.0f})")

        q1, med, q3 = np.percentile(vals, [25, 50, 75])
        for xq, size, marker in ((q1, 26, "o"), (med, 60, "D"), (q3, 26, "o")):
            yq = np.searchsorted(vals, xq, side="right") / total_campaigns
            ax.scatter([xq], [yq], s=size, marker=marker, color=color, edgecolor="white", linewidth=1.2, zorder=5)

    ax.set_xscale("log")
    min_val = df_r["interactions_to_first_execution"].dropna().min()
    max_val = df_r["interactions_to_first_execution"].dropna().max()
    ax.set_xlim(max(0.8, min_val * 0.8), max_val * 1.2)
    ax.set_ylim(0, 1.05)
    ax.xaxis.set_major_formatter(ScalarFormatter())

    ax.set_xlabel("IFE (interactions, log scale)")
    ax.set_ylabel("Cumulative fraction of campaigns")
    ax.set_title("Cumulative activation by interaction budget")
    ax.legend(title="median IFE in parentheses", loc="lower right", frameon=True)
    ax.grid(alpha=0.25, which="both")

    save_figure(fig, out_dir, "ife_curve")


def plot_reachability_dotplot(df, out_dir):
    """Figure 3: Reachability per tool (one dot per API, plus tool mean)."""
    required = {"tool", "api", "reached"}
    if not required.issubset(df.columns):
        print(f"[red]Skipping reachability_dotplot: missing columns {sorted(required - set(df.columns))}.[/red]")
        return

    rr = df.groupby(["tool", "api"])["reached"].mean().mul(100).reset_index(name="rr")
    order = df.groupby("tool")["reached"].mean().sort_values(ascending=False).index

    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    sns.stripplot(data=rr, x="rr", y="tool", order=order, ax=ax, size=7, color="#2a3f8f", alpha=0.8, jitter=0.15, zorder=2)

    means = df.groupby("tool")["reached"].mean().mul(100).reindex(order)
    ax.scatter(means.values, range(len(order)), marker="D", s=60, facecolors="none", edgecolors="crimson", linewidths=1.8, zorder=3, label="Tool Mean")

    ax.set_xlim(40, 103)
    ax.set_xlabel("Mutant Coverage (activation) (%)")
    ax.set_ylabel("")
    ax.set_title("Activation rate per tool (one dot per API)")
    ax.legend(loc="lower left", frameon=True)
    ax.grid(axis="x", alpha=0.3)

    save_figure(fig, out_dir, "reachability_dots")


def plot_ife_heatmap(df, out_dir, group_col, fname, title):
    """Figure 4 & 5: Median IFE heatmaps (per API and per Fault Type)."""
    required = {"tool", group_col, "reached", "interactions_to_first_execution"}
    if not required.issubset(df.columns):
        print(f"[red]Skipping {fname}: missing columns {sorted(required - set(df.columns))}.[/red]")
        return

    df_r = df[df["reached"] == True]
    
    # Exclude Composition Faults for per-fault-type analysis
    if group_col == "mutant_taxonomy" and "mutant_taxonomy" in df_r.columns:
        df_r = df_r[df_r["mutant_taxonomy"] != "Composition Fault"]

    if df_r.empty or not has_data(df_r, "interactions_to_first_execution"):
        print(f"[yellow]Skipping {fname}: no IFE data for reached campaigns.[/yellow]")
        return

    med = df_r.groupby(["tool", group_col])["interactions_to_first_execution"].median().unstack(group_col)
    tool_order = df_r.groupby("tool")["interactions_to_first_execution"].median().sort_values().index
    med = med.reindex(tool_order)
    col_order = med.median().sort_values().index
    med = med[col_order]

    fig_width = max(7.0, 1.1 * med.shape[1] + 3)
    fig, ax = plt.subplots(figsize=(fig_width, 4.5))

    vmin = max(1, med.min().min())
    vmax = med.max().max()
    
    mask = med.isna()
    annot = med.round(0).astype("Int64").astype(str).where(med.notna(), "")

    sns.heatmap(
        med, mask=mask, annot=annot, fmt="", cmap="YlOrRd", linewidths=0.6, linecolor="white",
        ax=ax, norm=LogNorm(vmin=vmin, vmax=vmax), cbar_kws={"label": "Median IFE (log scale)"},
    )

    # Draw gray n/a cells explicitly so they match the caption
    for i in range(mask.shape[0]):
        for j in range(mask.shape[1]):
            if mask.iloc[i, j]:
                ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, facecolor='gray', edgecolor='white', lw=0.6))
                ax.text(j + 0.5, i + 0.5, "n/a", ha="center", va="center", color="white", fontsize=9, fontweight="bold")

    ax.set_title(title)
    ax.set_ylabel("")
    ax.set_xlabel("")
    
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", rotation_mode="anchor")

    save_figure(fig, out_dir, fname)


def plot_reachability_boxplot_per_api(df, out_dir):
    """Figure 3 (Alt): Distribution of per-API reachability for each tool."""
    required = {"tool", "api", "reached"}
    if not required.issubset(df.columns):
        print(f"[red]Skipping reachability_boxplot_per_api: missing columns {sorted(required - set(df.columns))}.[/red]")
        return

    per_api = df.groupby(["tool", "api"])["reached"].mean().mul(100).reset_index(name="rr")
    order = df.groupby("tool")["reached"].mean().sort_values(ascending=False).index

    fig, ax = plt.subplots(figsize=(9.5, 5))
    sns.boxplot(data=per_api, x="tool", y="rr", order=order, ax=ax, palette="crest", width=0.55, linewidth=1.1, showfliers=False, hue="tool", legend=False)
    sns.stripplot(data=per_api, x="tool", y="rr", order=order, ax=ax, color="0.25", size=5, alpha=0.7, jitter=0.15)

    ax.set_ylim(40, 105)
    ax.set_ylabel("Mutant Coverage (activation) (%)")
    ax.set_xlabel("")
    ax.set_title("Activation rate per tool (one dot per API)")
    ax.grid(axis="y", alpha=0.25)

    save_figure(fig, out_dir, "reachability_boxplot")


def plot_ife_boxplot_per_tool(df, out_dir):
    """Figure 4: Distribution of Interactions-to-First-Execution per tool."""
    required = {"tool", "reached", "interactions_to_first_execution"}
    if not required.issubset(df.columns):
        print(f"[red]Skipping ife_boxplot_per_tool: missing columns {sorted(required - set(df.columns))}.[/red]")
        return

    df_r = df[df["reached"] == True]
    if df_r.empty or not has_data(df_r, "interactions_to_first_execution"):
        print("[yellow]Skipping ife_boxplot_per_tool: no IFE data for reached campaigns.[/yellow]")
        return

    order = df_r.groupby("tool")["interactions_to_first_execution"].median().sort_values().index

    fig, ax = plt.subplots(figsize=(9.5, 5))
    sns.boxplot(data=df_r, x="tool", y="interactions_to_first_execution", order=order, ax=ax, palette="crest", width=0.55, linewidth=1.1, showfliers=False, hue="tool", legend=False)
    sns.stripplot(data=df_r, x="tool", y="interactions_to_first_execution", order=order, ax=ax, color="0.25", size=2.5, alpha=0.45, jitter=0.18)

    ax.set_yscale("log")
    ax.set_ylabel("IFE (interactions, log scale)")
    ax.set_xlabel("")
    ax.set_title("IFE by tool")
    ax.grid(axis="y", alpha=0.25, which="both")

    save_figure(fig, out_dir, "ife_boxplot_per_tool")


def plot_ife_boxplot_per_fault_type(df, out_dir):
    """Figure 5: Distribution of Interactions-to-First-Execution per fault type."""
    required = {"tool", "mutant_taxonomy", "reached", "interactions_to_first_execution"}
    if not required.issubset(df.columns):
        print(f"[red]Skipping ife_boxplot_per_fault_type: missing columns {sorted(required - set(df.columns))}.[/red]")
        return

    df_r = df[df["reached"] == True]
    
    # Exclude Composition Faults due to applicability confound
    if "mutant_taxonomy" in df_r.columns:
        df_r = df_r[df_r["mutant_taxonomy"] != "Composition Fault"]

    if df_r.empty or not has_data(df_r, "interactions_to_first_execution"):
        print("[yellow]Skipping ife_boxplot_per_fault_type: no IFE data for reached campaigns.[/yellow]")
        return

    order = df_r.groupby("mutant_taxonomy")["interactions_to_first_execution"].median().sort_values().index

    fig, ax = plt.subplots(figsize=(10, 5))
    sns.boxplot(data=df_r, x="mutant_taxonomy", y="interactions_to_first_execution", order=order, ax=ax, palette="flare", width=0.55, linewidth=1.1, showfliers=False, hue="mutant_taxonomy", legend=False)
    sns.stripplot(data=df_r, x="mutant_taxonomy", y="interactions_to_first_execution", order=order, ax=ax, color="0.25", size=2.5, alpha=0.4, jitter=0.18)

    ax.set_yscale("log")
    ax.set_ylabel("IFE (interactions, log scale)")
    ax.set_xlabel("")
    ax.set_title("IFE by fault type")
    
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", rotation_mode="anchor")
    ax.grid(axis="y", alpha=0.25, which="both")

    save_figure(fig, out_dir, "ife_boxplot_per_fault_type")


# Console summary
def print_summary(df):
    summary = df.groupby("tool").agg(campaigns=("reached", "size"), reached=("reached", "sum"))
    summary["coverage_%"] = (summary["reached"] / summary["campaigns"] * 100).round(1)

    df_r = df[df["reached"] == True].copy()
    if has_data(df_r, "interactions_to_first_execution"):
        ife = df_r.groupby("tool")["interactions_to_first_execution"].agg(
            median="median", q1=lambda x: x.quantile(0.25), q3=lambda x: x.quantile(0.75)
        ).round(1)
        summary = summary.join(ife.rename(columns={"median": "median_ife", "q1": "q1_ife", "q3": "q3_ife"}))

    summary = summary.sort_values("coverage_%", ascending=False)
    print("\n================ SUMMARY ================\n")
    print(summary)

    if has_data(df_r, "interactions_to_first_execution"):
        print("\n--- Median IFE per fault type ---\n")
        # Exclude Composition Fault for console summary too
        df_r_filtered = df_r[df_r["mutant_taxonomy"] != "Composition Fault"] if "mutant_taxonomy" in df_r.columns else df_r
        print(df_r_filtered.groupby("mutant_taxonomy")["interactions_to_first_execution"].median().round(1))


# Main
if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "results/time_budget_aggregated_results.csv"
    out_dir = "results/plots"
    os.makedirs(out_dir, exist_ok=True)

    df = load(csv_path)
    print_summary(df)

    plot_mutation_target_reachability(df, out_dir)
    plot_ife_curve(df, out_dir)
    plot_reachability_dotplot(df, out_dir)
    
    plot_ife_heatmap(df, out_dir, "api", "ife_per_api", "Median IFE by tool and API")
    plot_ife_heatmap(df, out_dir, "mutant_taxonomy", "ife_per_fault_type", "Median IFE by tool and fault type")

    plot_reachability_boxplot_per_api(df, out_dir)
    plot_ife_boxplot_per_tool(df, out_dir)
    plot_ife_boxplot_per_fault_type(df, out_dir)

    print(f"\n[green]Plots saved in ./{out_dir}/ (PDF for LaTeX + PNG for slides)[/green]")