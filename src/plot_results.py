import sys
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from rich import print

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
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        transform=ax.transAxes,
        fontsize=10,
        color="0.4",
        wrap=True,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def save_figure(fig, out_dir, filename):
    """Save a figure as PDF and PNG."""
    fig.tight_layout()
    fig.savefig(
        f"{out_dir}/{filename}.pdf",
        bbox_inches="tight",
    )
    fig.savefig(
        f"{out_dir}/{filename}.png",
        dpi=300,
        bbox_inches="tight",
    )
    plt.close(fig)

# Data loading


def load(csv_path):
    df = pd.read_csv(csv_path)

    # Normalize column names with old names to the current names.
    column_aliases = {
        "is_reached": "reached",
        "interactions_to_first_execution": (
            "interactions_to_first_execution"
        ),
        "requests_to_first_hit": (
            "interactions_to_first_execution"
        ),
    }

    df = df.rename(columns={
        old: new
        for old, new in column_aliases.items()
        if old in df.columns and new not in df.columns
    })

    # Normalize boolean reachability.
    if "reached" in df.columns:
        df["reached"] = df["reached"].map(
            lambda x:
                True if str(x).lower() == "true"
                else (
                    False if str(x).lower() == "false"
                    else np.nan
                )
        )

    # Numeric conversion.
    if "interactions_to_first_execution" in df.columns:
        df["interactions_to_first_execution"] = pd.to_numeric(
            df["interactions_to_first_execution"],
            errors="coerce",
        )

    # Keep only mutation campaigns.
    if "mutant_id" not in df.columns:
        raise ValueError(
            "Input CSV does not contain the required 'mutant_id' column."
        )

    df = df[df["mutant_id"].notna()].copy()
    return df


def plot_mutation_target_reachability(df, out_dir):
    """
    Figure 1:
    Overall mutation target reachability per testing tool.

    The bar represents the overall fraction of executable mutation
    targets reached by the tool. The vertical range shows the minimum
    and maximum reachability observed across benchmark APIs.
    """
    required = {"tool", "api", "reached"}

    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        print(
            f"[red]Skipping mutation_target_reachability: "
            f"missing columns {sorted(missing)}.[/red]"
        )
        return

    overall = (
        df.groupby("tool")["reached"]
        .mean()
        .mul(100)
    )

    per_api = (
        df.groupby(["tool", "api"])["reached"]
        .mean()
        .mul(100)
        .reset_index(name="reachability")
    )

    order = overall.sort_values(
        ascending=False
    ).index

    stats = (
        per_api.groupby("tool")["reachability"]
        .agg(["min", "max"])
        .reindex(order)
    )

    total = df.groupby("tool").size()

    x = np.arange(len(order))

    fig, ax = plt.subplots(
        figsize=(9, 5.5),
    )

    palette = sns.color_palette(
        "crest",
        len(order),
    )

    ax.bar(
        x,
        overall.reindex(order),
        width=0.55,
        color=palette,
        edgecolor="black",
        linewidth=0.7,
    )

    # Min-max range across APIs.
    ax.vlines(
        x,
        stats["min"],
        stats["max"],
        color="0.25",
        linewidth=2,
        zorder=3,
    )

    ax.scatter(
        x,
        stats["min"],
        color="0.25",
        s=25,
        zorder=4,
    )

    ax.scatter(
        x,
        stats["max"],
        color="0.25",
        s=25,
        zorder=4,
    )

    # Overall MTR labels.
    for i, tool in enumerate(order):
        value = overall.loc[tool]
        ax.text(
            i,
            value + 2,
            f"{value:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    ax.set_ylabel(
        "Mutation Coverage (%)"
    )

    ax.set_xlabel("")

    ax.set_ylim(
        0,
        105,
    )

    ax.set_title(
        "Overall mutation coverage by tool"
    )

    ax.set_xticks(x)

    ax.set_xticklabels(
        [
            f"{tool}\n(n={total[tool]})"
            for tool in order
        ]
    )

    ax.grid(
        axis="y",
        alpha=0.25,
    )

    fig.text(
        0.5,
        0.01,
        "Bars = overall reachability    •    "
        "Vertical ranges = minimum/maximum across APIs",
        ha="center",
        fontsize=9,
        color="0.35",
    )

    fig.tight_layout(
        rect=[0, 0.05, 1, 1]
    )

    fig.savefig(
        f"{out_dir}/mutation_coverage.pdf",
        bbox_inches="tight",
    )

    fig.savefig(
        f"{out_dir}/mutation_coverage.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)

def plot_ife_curve(df, out_dir):
    """
    Figure 2:
    Cumulative fraction of all mutation campaigns whose target has
    been executed by a given number of HTTP interactions.

    Unreached campaigns remain in the denominator. Therefore, the
    final curve height equals the tool's mutation coverage.
    """

    if not has_data(
        df,
        "interactions_to_first_execution",
    ):
        print(
            "[yellow]Skipping ife_curve: no "
            "interactions_to_first_execution data available.[/yellow]"
        )
        return

    required = {"tool", "reached"}

    if not required.issubset(df.columns):
        print(
            "[red]Skipping ife_curve: missing required columns.[/red]"
        )
        return

    fig, ax = plt.subplots(
        figsize=(8.5, 5),
    )

    reach_rate = (
        df.groupby("tool")["reached"]
        .mean()
        .sort_values(ascending=False)
    )

    order = reach_rate.index

    palette = sns.color_palette(
        "tab10",
        len(order),
    )

    any_curve_drawn = False

    for tool, color in zip(order, palette):

        group = df[df["tool"] == tool]

        total_campaigns = len(group)

        if total_campaigns == 0:
            continue

        interactions = (
            group.loc[
                group["reached"] == True,
                "interactions_to_first_execution",
            ]
            .dropna()
            .sort_values()
            .values
        )

        if len(interactions) == 0:
            continue

        any_curve_drawn = True

        # Denominator is ALL campaigns.
        # Thus, the final curve height equals MC.
        fraction = (
            np.arange(1, len(interactions) + 1)
            / total_campaigns
        )

        ax.step(
            interactions,
            fraction,
            where="post",
            label=f"{tool} (n={total_campaigns})",
            linewidth=2,
            color=color,
        )

        # Mark the final observed execution point.
        ax.scatter(
            interactions[-1],
            fraction[-1],
            color=color,
            s=60,
            zorder=5,
            edgecolor="white",
            linewidth=1.5,
        )

    if not any_curve_drawn:
        empty_panel(
            ax,
            "No interactions_to_first_execution data available",
        )
    else:
        ax.legend(
            title="n = total campaigns",
            loc="lower right",
            frameon=True,
        )

    ax.set_xlabel(
        "Interactions-to-First-Execution"
    )

    ax.set_ylabel(
        "Cumulative fraction of mutation campaigns"
    )

    ax.set_title(
        "Mutation target execution by interaction count"
    )

    ax.set_ylim(
        0,
        1.05,
    )

    ax.grid(
        alpha=0.25,
    )

    fig.text(
        0.5,
        0.01,
        "Unreached campaigns remain in the denominator; "
        "final curve height equals mutation coverage",
        ha="center",
        fontsize=9,
        color="0.35",
    )

    fig.tight_layout(
        rect=[0, 0.05, 1, 1]
    )

    fig.savefig(
        f"{out_dir}/ife_curve.pdf",
        bbox_inches="tight",
    )

    fig.savefig(
        f"{out_dir}/ife_curve.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)

def plot_reachability_per_api(df, out_dir):
    """
    Figure 3:
    Mutation coverage for each tool/API combination.
    """

    required = {"tool", "api", "reached"}

    if not required.issubset(df.columns):
        print(
            "[red]Skipping reachability_per_api: missing required "
            "columns.[/red]"
        )
        return

    total = (
        df.groupby(["tool", "api"])
        .size()
    )

    reached = (
        df.groupby(["tool", "api"])["reached"]
        .sum()
    )

    reach_rate = (
        reached
        .div(total)
        .mul(100)
        .unstack("api")
    )

    tool_order = (
        df.groupby("tool")["reached"]
        .mean()
        .sort_values(ascending=False)
        .index
    )

    api_order = sorted(
        reach_rate.columns
    )

    reach_rate = reach_rate.reindex(
        index=tool_order,
        columns=api_order,
    )

   # Mask cells for which no campaigns exist.
    mask = reach_rate.isna()

    # Use a copy only for annotations.
    annot = (
        reach_rate
        .round(0)
        .astype("Int64")
        .astype(str)
        .where(
            reach_rate.notna(),
            "",
        )
    )

    fig, ax = plt.subplots(
        figsize=(12, 4.8),
    )

    sns.heatmap(
        reach_rate,
        annot=annot,
        fmt="",
        cmap="crest",
        vmin=0,
        vmax=100,
        linewidths=0.6,
        linecolor="white",
        mask=mask,
        ax=ax,
        cbar_kws={
            "label": "Mutation coverage (%)",
        },
    )

    # Explicitly write "n/a" in empty cells.
    for row in range(reach_rate.shape[0]):
        for col in range(reach_rate.shape[1]):
            if pd.isna(reach_rate.iloc[row, col]):
                ax.text(
                    col + 0.5,
                    row + 0.5,
                    "n/a",
                    ha="center",
                    va="center",
                    color="0.35",
                    fontsize=9,
                )

    ax.set_title(
        "Mutation coverage by tool and API"
    )

    ax.set_ylabel("")

    ax.set_xlabel("")

    ax.tick_params(
        axis="x",
        rotation=45,
    )

    fig.text(
        0.5,
        0.01,
        "n/a = no validated campaigns for the tool/API combination",
        ha="center",
        fontsize=9,
        color="0.35",
    )

    fig.tight_layout(
        rect=[0, 0.04, 1, 1]
    )

    fig.savefig(
        f"{out_dir}/coverage_per_api.pdf",
        bbox_inches="tight",
    )

    fig.savefig(
        f"{out_dir}/coverage_per_api.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)


def plot_reachability_per_fault_type(df, out_dir):
    """
    Figure 4:
    Mutation coverage for each tool/fault-type combination.
    """

    required = {
        "tool",
        "mutant_taxonomy",
        "reached",
    }

    if not required.issubset(df.columns):
        print(
            "[red]Skipping reachability_per_fault_type: missing "
            "required columns.[/red]"
        )
        return

    total = (
        df.groupby(
            ["tool", "mutant_taxonomy"]
        )
        .size()
    )

    reached = (
        df.groupby(
            ["tool", "mutant_taxonomy"]
        )["reached"]
        .sum()
    )

    reach_rate = (
        reached
        .div(total)
        .mul(100)
        .unstack("mutant_taxonomy")
    )

    tool_order = (
        df.groupby("tool")["reached"]
        .mean()
        .sort_values(ascending=False)
        .index
    )

    taxonomy_order = sorted(
        reach_rate.columns
    )

    reach_rate = reach_rate.reindex(
        index=tool_order,
        columns=taxonomy_order,
    )

    annot = (
        reach_rate
        .round(0)
        .astype("Int64")
        .astype(str)
        .where(
            reach_rate.notna(),
            "n/a",
        )
    )

    fig, ax = plt.subplots(
        figsize=(10, 4.8),
    )

    sns.heatmap(
        reach_rate,
        annot=annot,
        fmt="",
        cmap="crest",
        vmin=0,
        vmax=100,
        linewidths=0.6,
        linecolor="white",
        ax=ax,
        cbar_kws={
            "label": "Mutation coverage (%)",
        },
    )

    for text in ax.texts:
        if text.get_text() == "n/a":
            text.set_color("0.35")

    ax.set_title(
        "Mutation coverage by tool and fault type"
    )

    ax.set_ylabel("")

    ax.set_xlabel("")

    ax.tick_params(
        axis="x",
        rotation=25,
    )

    fig.text(
        0.5,
        0.01,
        "n/a = no validated campaigns for the tool/fault-type combination",
        ha="center",
        fontsize=9,
        color="0.35",
    )

    fig.tight_layout(
        rect=[0, 0.04, 1, 1]
    )

    fig.savefig(
        f"{out_dir}/coverage_per_fault_type.pdf",
        bbox_inches="tight",
    )

    fig.savefig(
        f"{out_dir}/coverage_per_fault_type.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)



# Console summary


def print_summary(df):

    summary = df.groupby("tool").agg(
        campaigns=("reached", "size"),
        reached=("reached", "sum"),
    )

    summary["coverage_%"] = (
        summary["reached"]
        / summary["campaigns"]
        * 100
    ).round(1)

    df_r = df[
        df["reached"] == True
    ].copy()

    if has_data(
        df_r,
        "interactions_to_first_execution",
    ):
        ife = (
            df_r.groupby("tool")[
                "interactions_to_first_execution"
            ]
            .agg(
                median="median",
                q1=lambda x: x.quantile(0.25),
                q3=lambda x: x.quantile(0.75),
            )
            .round(1)
        )

        summary = summary.join(
            ife.rename(columns={
                "median": "median_ife",
                "q1": "q1_ife",
                "q3": "q3_ife",
            })
        )

    summary = summary.sort_values(
        "coverage_%",
        ascending=False,
    )

    print(
        "\n================ SUMMARY ================\n"
    )

    print(summary)

    if has_data(
        df_r,
        "interactions_to_first_execution",
    ):
        print(
            "\n--- Median IFE per fault type ---\n"
        )

        print(
            df_r.groupby("mutant_taxonomy")[
                "interactions_to_first_execution"
            ]
            .median()
            .round(1)
        )



# Main


if __name__ == "__main__":

    csv_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "results/time_budget_aggregated_results.csv"
    )

    out_dir = "results/plots"

    os.makedirs(
        out_dir,
        exist_ok=True,
    )

    df = load(csv_path)

    print_summary(df)

    # Figure 1
    plot_mutation_target_reachability(
        df,
        out_dir,
    )

    # Figure 2
    plot_ife_curve(
        df,
        out_dir,
    )

    # Figure 3 
    plot_reachability_per_api(
        df,
        out_dir,
    )

    # Figure 4
    plot_reachability_per_fault_type(
        df,
        out_dir,
    )

    print(
        f"\n[green]Plots saved in ./{out_dir}/ "
        f"(PDF for LaTeX + PNG for slides)[/green]"
    )
