import sys
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_theme(style="whitegrid", font_scale=1.05)

# Consistent tool ordering/colors
TOOL_ORDER = ["schemathesis", "restler", "resttestgen", "cats", "deeprest", "evomaster", "restest", "morest", "arat-rl"]


def load(csv_path):
    df = pd.read_csv(csv_path)

    # Normalize boolean columns (handles True/False strings or real bools)
    if "reached" in df.columns:
        df["reached"] = df["reached"].map(
            lambda x: True if str(x).lower() == "true" else (False if str(x).lower() == "false" else np.nan)
        )

    # Numeric conversion (empty cells -> NaN)
    if "time_to_first_hit_sec" in df.columns:
        df["time_to_first_hit_sec"] = pd.to_numeric(df["time_to_first_hit_sec"], errors="coerce")

    # Keep only mutant campaigns (drop baseline rows)
    df = df[df["mutant_id"].notna()].copy()
    return df


# Figure 1: Reachability rate + mean time-to-hit per tool
def plot_tool_overview(df, out_dir):
    total = df.groupby("tool").size()
    reach_rate = (df.groupby("tool")["reached"].sum() / total * 100)

    df_r = df[df["reached"] == True]
    mean_t = df_r.groupby("tool")["time_to_first_hit_sec"].mean()
    sem_t = df_r.groupby("tool")["time_to_first_hit_sec"].sem()

    order = reach_rate.sort_values(ascending=False).index
    reach_rate = reach_rate.reindex(order)
    mean_t = mean_t.reindex(order)
    sem_t = sem_t.reindex(order)

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))

    reach_rate.plot.bar(ax=axes[0], color=sns.color_palette("crest", len(order)), edgecolor="black")
    axes[0].set_ylabel("Reachability rate (%)")
    axes[0].set_ylim(0, 100)
    axes[0].set_title("(a) % of mutated endpoints reached")
    axes[0].tick_params(axis="x", rotation=30)

    mean_t.plot.bar(ax=axes[1], yerr=sem_t, capsize=4, color=sns.color_palette("crest", len(order)), edgecolor="black")
    axes[1].set_ylabel("Mean time-to-first-hit (s)")
    axes[1].set_title("(b) Speed of reaching the mutated endpoint")
    axes[1].tick_params(axis="x", rotation=30)

    fig.tight_layout()
    fig.savefig(f"{out_dir}/tool_overview.pdf")
    fig.savefig(f"{out_dir}/tool_overview.png", dpi=300)
    plt.close(fig)

# Figure 2: Heatmap tool x taxonomy (mean time-to-hit)
def plot_taxonomy_heatmap(df, out_dir):
    df_r = df[df["reached"] == True]
    pivot = df_r.pivot_table(index="tool", columns="mutant_taxonomy",
                             values="time_to_first_hit_sec", aggfunc="mean")

    fig, ax = plt.subplots(figsize=(10, 5))
    sns.heatmap(pivot, annot=True, fmt=".0f", cmap="YlOrRd", linewidths=0.6, ax=ax,
                cbar_kws={"label": "Mean time-to-first-hit (s)"})
    ax.set_title("Exploration speed per tool and fault taxonomy (seconds)")
    ax.set_ylabel("")
    ax.set_xlabel("")
    ax.tick_params(axis="x", rotation=25)
    fig.tight_layout()
    fig.savefig(f"{out_dir}/taxonomy_heatmap.pdf")
    fig.savefig(f"{out_dir}/taxonomy_heatmap.png", dpi=300)
    plt.close(fig)


# Figure 3: Efficiency curves (cumulative fraction of campaigns reached over time)
def plot_efficiency_curves(df, out_dir, max_time=300):
    fig, ax = plt.subplots(figsize=(8, 5))

    for tool, group in df.groupby("tool"):
        total_campaigns = len(group)
        times = group.loc[group["reached"] == True, "time_to_first_hit_sec"].dropna()
        times = times[times <= max_time]
        if len(times) == 0:
            continue
        t_sorted = np.sort(times.values)
        frac = np.arange(1, len(t_sorted) + 1) / total_campaigns
        ax.step(t_sorted, frac, where="post", label=tool, lw=2)

    ax.set_xlabel("Time since run start (s)")
    ax.set_ylabel("Cumulative fraction of campaigns reached")
    ax.set_title("Exploration efficiency: how fast tools reach mutated endpoints")
    ax.set_xlim(0, max_time)
    ax.set_ylim(0, 1)
    ax.legend()
    fig.tight_layout()
    fig.savefig(f"{out_dir}/efficiency_curves.pdf")
    fig.savefig(f"{out_dir}/efficiency_curves.png", dpi=300)
    plt.close(fig)


# Figure 4: Boxplot of time-to-hit per taxonomy category
def plot_taxonomy_boxplot(df, out_dir):
    df_r = df[df["reached"] == True]
    fig, ax = plt.subplots(figsize=(9, 5))
    sns.boxplot(data=df_r, x="mutant_taxonomy", y="time_to_first_hit_sec", ax=ax, palette="muted")
    sns.stripplot(data=df_r, x="mutant_taxonomy", y="time_to_first_hit_sec", ax=ax,
                  color="0.25", size=3, alpha=0.5)
    ax.set_ylabel("Time-to-first-hit (s)")
    ax.set_xlabel("")
    ax.set_title("Distribution of exploration time per fault taxonomy")
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    fig.savefig(f"{out_dir}/taxonomy_boxplot.pdf")
    fig.savefig(f"{out_dir}/taxonomy_boxplot.png", dpi=300)
    plt.close(fig)


# Console summary
def print_summary(df):
    df_r = df[df["reached"] == True]
    summary = df.groupby("tool").agg(
        campaigns=("reached", "size"),
        reached=("reached", "sum"),
    )
    summary["reach_rate_%"] = (summary["reached"] / summary["campaigns"] * 100).round(1)
    summary["mean_tth_s"] = df_r.groupby("tool")["time_to_first_hit_sec"].mean().round(1)
    summary["median_tth_s"] = df_r.groupby("tool")["time_to_first_hit_sec"].median().round(1)
    print("\n================ SUMMARY ================\n")
    print(summary)
    print("\n--- Mean time-to-hit per taxonomy (s) ---\n")
    print(df_r.groupby("mutant_taxonomy")["time_to_first_hit_sec"].mean().round(1))


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "results/time_budget_aggregated_results.csv"
    out_dir = "plots"
    os.makedirs(out_dir, exist_ok=True)

    df = load(csv_path)
    print_summary(df)

    plot_tool_overview(df, out_dir)
    plot_taxonomy_heatmap(df, out_dir)
    plot_efficiency_curves(df, out_dir)
    plot_taxonomy_boxplot(df, out_dir)

    print(f"\n[green]Plots saved in ./{out_dir}/ (PDF for LaTeX + PNG for slides)[/green]")