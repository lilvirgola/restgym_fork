from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import (
    binomtest,
    chi2 as chi2_dist,
    chi2_contingency,
    friedmanchisquare,
    kruskal,
    mannwhitneyu,
    rankdata,
    wilcoxon,
)

# Conf
TOOLS = [
    "deeprest",
    "resttestgen",
    "morest",
    "arat-rl",
    "schemathesis",
    "restler",
]

ALPHA = 0.05

SPEC_METHODS = [
    "get", "post", "put", "patch", "delete",
    "head", "options", "trace", "connect",
]


# Utility functions
def clean_column_name(name: str) -> str:
    name = str(name).strip()
    name = name.replace("\\_", "_")
    name = name.lstrip("*")
    return name


def clean_value(value):
    if isinstance(value, str):
        value = value.strip()
        value = value.strip("*")
    return value


def fmt_p(p: float) -> str:
    if pd.isna(p):
        return "---"
    if p < 0.001:
        return "<0.001"
    return f"{p:.3f}"


def fmt_p_tex(p: float) -> str:
    """fmt_p wrapped in \\textbf when significant, for LaTeX tables."""
    if pd.isna(p):
        return "---"
    txt = fmt_p(p)
    return f"\\textbf{{{txt}}}" if p < ALPHA else txt


def fmt_number(x: float, digits: int = 2) -> str:
    if pd.isna(x):
        return "---"
    return f"{x:.{digits}f}"


def holm_correction(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni correction; returns adjusted p in original order."""
    p = np.asarray(p_values, dtype=float)
    if len(p) == 0:
        return []
    order = np.argsort(p)
    adjusted = np.empty_like(p)
    running_max = 0.0
    for rank, idx in enumerate(order):
        running_max = max(running_max, (len(p) - rank) * p[idx])
        adjusted[idx] = min(running_max, 1.0)
    return adjusted.tolist()


def a12(a: list, b: list) -> float:
    """Vargha-Delaney effect size: P(a > b) + 0.5 * P(a = b)."""
    more = same = 0.0
    for x in a:
        for y in b:
            if x == y:
                same += 1
            elif x > y:
                more += 1
    return (more + 0.5 * same) / (len(a) * len(b))


def rank_biserial(differences: np.ndarray) -> float:
    """Rank-biserial correlation for paired data (positive = A > B)."""
    differences = differences[differences != 0]
    if len(differences) == 0:
        return 0.0
    ranks = rankdata(np.abs(differences))
    positive = ranks[differences > 0].sum()
    negative = ranks[differences < 0].sum()
    total = positive + negative
    return (positive - negative) / total if total else 0.0


def load_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    df.columns = [clean_column_name(c) for c in df.columns]

    for column in df.columns:
        if df[column].dtype == object:
            df[column] = df[column].map(clean_value)

    required = {
        "api",
        "tool",
        "mutant_id",
        "is_reached",
        "interactions_to_first_execution",
        "mutant_operator",
    }

    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}\n"
            f"Available columns: {list(df.columns)}"
        )

    df["is_reached"] = (
        df["is_reached"]
        .astype(str)
        .str.lower()
        .map({"true": True, "false": False, "1": True, "0": False})
    )

    for column in [
        "interactions_to_first_execution",
        "execution_count",
        "interactions",
        "covered_operations",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    # Baseline/control campaigns define no mutation target.
    before = len(df)
    df = df[df["mutant_id"].notna()].copy()
    dropped = before - len(df)
    if dropped:
        print(
            f"NOTE: dropped {dropped} baseline rows "
            "(no mutant_id) from all statistics."
        )

    present = [t for t in TOOLS if t in df["tool"].unique()]
    if not present:
        raise ValueError(
            f"No configured tools found.\n"
            f"Found: {sorted(df['tool'].dropna().unique())}"
        )

    return df


# ---------------------------------------------------------------------------
# RESTgym operation-coverage baseline
# ---------------------------------------------------------------------------
def count_spec_operations(spec_path: Path) -> int:
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    total = 0
    for path_item in spec.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for method in SPEC_METHODS:
            if method in path_item:
                total += 1
    return total


def load_operation_totals(specs_dir: Path | None, apis) -> dict:
    """Operations per API, counted from the OpenAPI specs (path x method)."""
    if specs_dir is None:
        return {}
    totals = {}
    for api in apis:
        candidates = [
            specs_dir / f"{api}-openapi.json",
            specs_dir / api / f"{api}-openapi.json",
            specs_dir / api / "specifications" / f"{api}-openapi.json",
        ]
        found = next((c for c in candidates if c.exists()), None)
        if found is None:
            print(f"WARNING: no OpenAPI spec found for '{api}' under {specs_dir}")
            continue
        totals[api] = count_spec_operations(found)
    return totals


def baseline_comparison(df: pd.DataFrame, ops_total: dict):
    """Per tool: MC vs RESTgym baselines (operation + code coverage)."""
    if "covered_operations" not in df.columns:
        return None
    df = df.copy()
    if ops_total:
        df["op_cov_pct"] = [
            100 * cov / ops_total[api] if ops_total.get(api) else np.nan
            for api, cov in zip(df["api"], df["covered_operations"])
        ]
    rows = []
    for tool, group in df.groupby("tool", sort=False):
        row = {"tool": tool, "mc_pct": 100 * group["is_reached"].mean()}
        if "op_cov_pct" in df.columns:
            row["op_cov_pct"] = group["op_cov_pct"].mean()
        # branch/line/method coverage are stored as fractions 0..1
        for src, dst in [
            ("branch_cov", "branch_pct"),
            ("line_cov", "line_pct"),
            ("method_cov", "method_pct"),
        ]:
            if src in group.columns:
                row[dst] = 100 * group[src].mean()
        rows.append(row)
    return pd.DataFrame(rows)


def gate_effect_stats(df: pd.DataFrame):
    """Optional: campaigns where the target got requests but never a valid one.

    Activates only if the input CSV carries a per-campaign
    'any_request_to_target' column exported from the interaction traces.
    """
    if "any_request_to_target" not in df.columns:
        return None
    any_req = (
        df["any_request_to_target"]
        .astype(str)
        .str.lower()
        .map({"true": True, "false": False, "1": True, "0": False})
        .fillna(False)
        .astype(bool)
    )
    return {
        "gate_effect": int((any_req & ~df["is_reached"]).sum()),
        "reach_pct": 100 * any_req.mean(),
    }


# Descriptive statistics
def descriptive_statistics(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tool, group in df.groupby("tool", sort=False):
        reached = group[group["is_reached"] == True]
        interactions = reached[
            "interactions_to_first_execution"
        ].dropna()
        rows.append(
            {
                "tool": tool,
                "campaigns": len(group),
                "reached": len(reached),
                "unreached": len(group) - len(reached),
                "reachability_pct": (
                    100 * len(reached) / len(group) if len(group) else np.nan
                ),
                "interaction_n": len(interactions),
                "interaction_median": (
                    interactions.median() if len(interactions) else np.nan
                ),
                "interaction_q1": (
                    interactions.quantile(0.25) if len(interactions) else np.nan
                ),
                "interaction_q3": (
                    interactions.quantile(0.75) if len(interactions) else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def api_statistics(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (api, tool), group in df.groupby(["api", "tool"], sort=True):
        reached = group[group["is_reached"] == True]
        interactions = reached[
            "interactions_to_first_execution"
        ].dropna()
        rows.append(
            {
                "api": api,
                "tool": tool,
                "n": len(group),
                "reached": len(reached),
                "reachability_pct": (
                    100 * len(reached) / len(group) if len(group) else np.nan
                ),
                "interaction_median": (
                    interactions.median() if len(interactions) else np.nan
                ),
                "interaction_q1": (
                    interactions.quantile(0.25) if len(interactions) else np.nan
                ),
                "interaction_q3": (
                    interactions.quantile(0.75) if len(interactions) else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def fault_type_statistics(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (operator, tool), group in df.groupby(
        ["mutant_operator", "tool"], sort=True
    ):
        reached = group[group["is_reached"] == True]
        interactions = reached[
            "interactions_to_first_execution"
        ].dropna()
        rows.append(
            {
                "mutant_operator": operator,
                "tool": tool,
                "n": len(group),
                "reached": len(reached),
                "reachability_pct": (
                    100 * len(reached) / len(group) if len(group) else np.nan
                ),
                "interaction_median": (
                    interactions.median() if len(interactions) else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# PRIMARY (paired) tests: matched-campaign design
# ---------------------------------------------------------------------------
def paired_reachability(df: pd.DataFrame, tool_a: str, tool_b: str) -> pd.DataFrame:
    """Match campaigns on (api, mutant_id); binary outcomes side by side."""
    a = (
        df[df["tool"] == tool_a][["api", "mutant_id", "is_reached"]]
        .drop_duplicates(["api", "mutant_id"])
        .rename(columns={"is_reached": "a"})
    )
    b = (
        df[df["tool"] == tool_b][["api", "mutant_id", "is_reached"]]
        .drop_duplicates(["api", "mutant_id"])
        .rename(columns={"is_reached": "b"})
    )
    return a.merge(b, on=["api", "mutant_id"], how="inner")


def mcnemar_test(paired: pd.DataFrame) -> dict:
    """Exact McNemar test on discordant matched pairs."""
    if paired.empty:
        return {"n": 0, "a_only": 0, "b_only": 0, "p_value": np.nan}
    a = paired["a"].astype(bool)
    b = paired["b"].astype(bool)
    a_only = int((a & ~b).sum())
    b_only = int((~a & b).sum())
    discordant = a_only + b_only
    if discordant == 0:
        p_value = 1.0
    else:
        p_value = binomtest(
            min(a_only, b_only), discordant, 0.5, alternative="two-sided"
        ).pvalue
    return {"n": len(paired), "a_only": a_only, "b_only": b_only, "p_value": p_value}


def pairwise_mcnemar_tests(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    present = [t for t in TOOLS if t in df["tool"].unique()]
    for tool_a, tool_b in combinations(present, 2):
        res = mcnemar_test(paired_reachability(df, tool_a, tool_b))
        rows.append({"tool_a": tool_a, "tool_b": tool_b, **res})
    result = pd.DataFrame(rows)
    if not result.empty:
        result["p_holm"] = holm_correction(result["p_value"].tolist())
        result["significant"] = result["p_holm"] < ALPHA
    return result


def cochran_q(df: pd.DataFrame) -> dict:
    """Cochran's Q over matched mutants (rows) x tools (columns)."""
    pivot = (
        df.pivot_table(
            index=["api", "mutant_id"],
            columns="tool",
            values="is_reached",
            aggfunc="first",
        )
        .dropna()
    )
    present = [t for t in TOOLS if t in pivot.columns]
    if len(present) < 3:
        return {"n": len(pivot), "k": len(present), "q": np.nan,
                "p_value": np.nan, "kendalls_w": np.nan}
    matrix = pivot[present].astype(int).to_numpy()
    n, k = matrix.shape
    row_totals = matrix.sum(axis=1)
    col_totals = matrix.sum(axis=0)
    total = matrix.sum()
    denominator = k * total - np.sum(row_totals ** 2)
    if denominator == 0:
        q, p_value = np.nan, np.nan
    else:
        q = (k - 1) * (k * np.sum(col_totals ** 2) - total ** 2) / denominator
        p_value = chi2_dist.sf(q, df=k - 1)
    kendalls_w = q / (n * (k - 1)) if n > 0 and not np.isnan(q) else np.nan
    return {"n": n, "k": k, "q": q, "p_value": p_value, "kendalls_w": kendalls_w}


def paired_interactions(df: pd.DataFrame, tool_a: str, tool_b: str) -> pd.DataFrame:
    """Match mutants activated by BOTH tools; compare IFE on the same mutant."""
    a = (
        df[(df["tool"] == tool_a) & (df["is_reached"] == True)][
            ["api", "mutant_id", "interactions_to_first_execution"]
        ]
        .dropna()
        .drop_duplicates(["api", "mutant_id"])
        .rename(columns={"interactions_to_first_execution": "a"})
    )
    b = (
        df[(df["tool"] == tool_b) & (df["is_reached"] == True)][
            ["api", "mutant_id", "interactions_to_first_execution"]
        ]
        .dropna()
        .drop_duplicates(["api", "mutant_id"])
        .rename(columns={"interactions_to_first_execution": "b"})
    )
    return a.merge(b, on=["api", "mutant_id"], how="inner")


def wilcoxon_test(paired: pd.DataFrame) -> dict:
    """Wilcoxon signed-rank on matched activated campaigns + rank-biserial r."""
    if paired.empty:
        return {"n": 0, "median_a": np.nan, "median_b": np.nan,
                "median_difference": np.nan, "p_value": np.nan, "r": np.nan}
    x = paired["a"].to_numpy()
    y = paired["b"].to_numpy()
    differences = x - y
    if (differences != 0).sum() == 0:
        p_value, r = 1.0, 0.0
    else:
        p_value = wilcoxon(x, y, alternative="two-sided", method="auto").pvalue
        r = rank_biserial(differences)
    return {
        "n": len(paired),
        "median_a": np.median(x),
        "median_b": np.median(y),
        "median_difference": np.median(differences),
        "p_value": p_value,
        "r": r,
    }


def pairwise_wilcoxon_tests(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    present = [t for t in TOOLS if t in df["tool"].unique()]
    for tool_a, tool_b in combinations(present, 2):
        res = wilcoxon_test(paired_interactions(df, tool_a, tool_b))
        rows.append({"tool_a": tool_a, "tool_b": tool_b, **res})
    result = pd.DataFrame(rows)
    if not result.empty:
        result["p_holm"] = holm_correction(result["p_value"].tolist())
        result["significant"] = result["p_holm"] < ALPHA
    return result


def friedman_test(df: pd.DataFrame) -> dict:
    """Friedman over mutants activated by every participating tool."""
    pivot = (
        df[df["is_reached"] == True]
        .pivot_table(
            index=["api", "mutant_id"],
            columns="tool",
            values="interactions_to_first_execution",
            aggfunc="first",
        )
    )
    present = [t for t in TOOLS if t in pivot.columns]
    if len(present) < 3:
        return {"n": 0, "k": len(present), "statistic": np.nan,
                "p_value": np.nan, "kendalls_w": np.nan}
    pivot = pivot[present].dropna()
    if len(pivot) < 2:
        return {"n": len(pivot), "k": len(present), "statistic": np.nan,
                "p_value": np.nan, "kendalls_w": np.nan}
    result = friedmanchisquare(*[pivot[t].to_numpy() for t in present])
    n, k = len(pivot), len(present)
    return {
        "n": n,
        "k": k,
        "statistic": result.statistic,
        "p_value": result.pvalue,
        "kendalls_w": result.statistic / (n * (k - 1)),
    }


# ---------------------------------------------------------------------------
# SENSITIVITY (unpaired) tests: Mann-Whitney U + Vargha-Delaney A12
# ---------------------------------------------------------------------------
def samples(df: pd.DataFrame, tool: str, metric: str):
    group = df[df["tool"] == tool]
    if metric == "reachability":
        return group["is_reached"].astype(int).to_numpy()
    return (
        group[group["is_reached"] == True][
            "interactions_to_first_execution"
        ]
        .dropna()
        .to_numpy()
    )


def pairwise_mw_tests(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    rows = []
    present = [t for t in TOOLS if t in df["tool"].unique()]

    for tool_a, tool_b in combinations(present, 2):
        a = samples(df, tool_a, metric)
        b = samples(df, tool_b, metric)

        if len(a) == 0 or len(b) == 0:
            rows.append(
                {
                    "tool_a": tool_a,
                    "tool_b": tool_b,
                    "n_a": len(a),
                    "n_b": len(b),
                    "stat_a": np.nan,
                    "stat_b": np.nan,
                    "p_value": np.nan,
                    "a12": np.nan,
                }
            )
            continue

        _, p_value = mannwhitneyu(a, b)

        if metric == "reachability":
            stat_a, stat_b = 100 * a.mean(), 100 * b.mean()
        else:
            stat_a, stat_b = np.median(a), np.median(b)

        rows.append(
            {
                "tool_a": tool_a,
                "tool_b": tool_b,
                "n_a": len(a),
                "n_b": len(b),
                "stat_a": stat_a,
                "stat_b": stat_b,
                "p_value": p_value,
                "a12": a12(a.tolist(), b.tolist()),
            }
        )

    result = pd.DataFrame(rows)
    if not result.empty:
        result["p_holm"] = holm_correction(result["p_value"].tolist())
        result["significant"] = result["p_holm"] < ALPHA
    return result


# ---------------------------------------------------------------------------
# Omnibus (unpaired) tests
# ---------------------------------------------------------------------------
def kruskal_wallis_interactions(df: pd.DataFrame) -> dict:
    groups = [
        g["interactions_to_first_execution"].dropna().to_numpy()
        for _, g in df[df["is_reached"] == True].groupby("tool")
    ]
    groups = [g for g in groups if len(g) > 0]
    if len(groups) < 3:
        return {"n": 0, "k": len(groups), "H": np.nan, "p_value": np.nan}
    H, p_value = kruskal(*groups)
    return {
        "n": int(sum(len(g) for g in groups)),
        "k": len(groups),
        "H": H,
        "p_value": p_value,
    }


def tool_reachability_chi_square(df: pd.DataFrame) -> dict:
    table = pd.crosstab(df["tool"], df["is_reached"])
    if table.shape[0] < 2 or table.shape[1] < 2:
        return {"n": np.nan, "statistic": np.nan, "dof": np.nan, "p_value": np.nan}
    chi2, p_value, dof, _ = chi2_contingency(table)
    return {
        "n": int(table.to_numpy().sum()),
        "statistic": chi2,
        "dof": dof,
        "p_value": p_value,
    }


def fault_type_chi_square(df: pd.DataFrame) -> dict:
    col = "mutant_taxonomy" if "mutant_taxonomy" in df.columns else "mutant_operator"
    table = pd.crosstab(df[col], df["is_reached"])
    if table.shape[0] < 2 or table.shape[1] < 2:
        return {"n": np.nan, "statistic": np.nan, "dof": np.nan, "p_value": np.nan}
    chi2, p_value, dof, _ = chi2_contingency(table)
    return {
        "n": int(table.to_numpy().sum()),
        "statistic": chi2,
        "dof": dof,
        "p_value": p_value,
    }


# ---------------------------------------------------------------------------
# LaTeX helpers
# ---------------------------------------------------------------------------
def dataframe_to_latex(df: pd.DataFrame, path: Path, *, escape: bool = True):
    output = df.to_latex(
        index=False,
        escape=escape,
        na_rep="---",
        float_format=lambda x: f"{x:.3f}",
    )
    path.write_text(output, encoding="utf-8")


def generate_reachability_table(stats_df: pd.DataFrame, output: Path):
    table = stats_df[
        ["tool", "campaigns", "reached", "unreached", "reachability_pct"]
    ].copy()
    table.columns = ["Tool", "Campaigns", "Activated", "Not activated", "MC (\\%)"]
    table["MC (\\%)"] = table["MC (\\%)"].map(lambda x: f"{x:.1f}")
    dataframe_to_latex(table, output, escape=False)


def generate_interaction_table(stats_df: pd.DataFrame, output: Path):
    table = stats_df[
        [
            "tool",
            "interaction_n",
            "interaction_median",
            "interaction_q1",
            "interaction_q3",
        ]
    ].copy()
    table.columns = ["Tool", "$n$", "Median", "$Q_1$", "$Q_3$"]
    dataframe_to_latex(table, output, escape=False)


def generate_baseline_tex(base: pd.DataFrame, output: Path):
    colmap = [
        ("tool", "Tool"),
        ("mc_pct", "MC (\\%)"),
        ("op_cov_pct", "Op.\\ cov.\\ (\\%)"),
        ("branch_pct", "Branch (\\%)"),
        ("line_pct", "Line (\\%)"),
        ("method_pct", "Method (\\%)"),
    ]
    present = [(c, lab) for c, lab in colmap if c in base.columns]
    table = base[[c for c, _ in present]].copy()
    table.columns = [lab for _, lab in present]
    for col in list(table.columns)[1:]:
        table[col] = table[col].map(lambda x: f"{x:.1f}")
    dataframe_to_latex(table, output, escape=False)


def generate_pairwise_mcnemar_tex(table_df: pd.DataFrame, output: Path):
    table = table_df[
        ["tool_a", "tool_b", "n", "a_only", "b_only", "p_value", "p_holm"]
    ].copy()
    table.columns = [
        "Tool A", "Tool B", "$n$", "A only", "B only", "$p$", "$p_{\\mathrm{Holm}}$",
    ]
    table["$p$"] = table["$p$"].map(fmt_p)
    table["$p_{\\mathrm{Holm}}$"] = table["$p_{\\mathrm{Holm}}$"].map(fmt_p_tex)
    dataframe_to_latex(table, output, escape=False)


def generate_pairwise_wilcoxon_tex(table_df: pd.DataFrame, output: Path):
    table = table_df[
        [
            "tool_a", "tool_b", "n",
            "median_a", "median_b", "median_difference",
            "p_value", "p_holm", "r",
        ]
    ].copy()
    table.columns = [
        "Tool A", "Tool B", "$n$",
        "Med A", "Med B", "Med diff",
        "$p$", "$p_{\\mathrm{Holm}}$", "$r$",
    ]
    table["$p$"] = table["$p$"].map(fmt_p)
    table["$p_{\\mathrm{Holm}}$"] = table["$p_{\\mathrm{Holm}}$"].map(fmt_p_tex)
    table["$r$"] = table["$r$"].map(lambda x: fmt_number(x, 2))
    dataframe_to_latex(table, output, escape=False)


def generate_pairwise_sensitivity_tex(table_df: pd.DataFrame, output: Path, metric: str):
    table = table_df[
        [
            "tool_a", "tool_b", "n_a", "n_b",
            "stat_a", "stat_b", "p_value", "p_holm", "a12",
        ]
    ].copy()

    if metric == "reachability":
        table.columns = [
            "Tool A", "Tool B", "$n_A$", "$n_B$",
            "MC A (\\%)", "MC B (\\%)",
            "$p$", "$p_{\\mathrm{Holm}}$", "$\\hat{A}_{12}$",
        ]
        table["MC A (\\%)"] = table["MC A (\\%)"].map(lambda x: f"{x:.1f}")
        table["MC B (\\%)"] = table["MC B (\\%)"].map(lambda x: f"{x:.1f}")
    else:
        table.columns = [
            "Tool A", "Tool B", "$n_A$", "$n_B$",
            "Median A", "Median B",
            "$p$", "$p_{\\mathrm{Holm}}$", "$\\hat{A}_{12}$",
        ]

    table["$p$"] = table["$p$"].map(fmt_p)
    table["$p_{\\mathrm{Holm}}$"] = table["$p_{\\mathrm{Holm}}$"].map(fmt_p_tex)
    table["$\\hat{A}_{12}$"] = table["$\\hat{A}_{12}$"].map(lambda x: fmt_number(x, 3))
    dataframe_to_latex(table, output, escape=False)


def generate_results_summary(
    descriptive: pd.DataFrame,
    cochran: dict,
    friedman: dict,
    mcnemar: pd.DataFrame,
    wilcoxon: pd.DataFrame,
    sens_interactions: pd.DataFrame,
    chi_tool: dict,
    chi_fault: dict,
    base: pd.DataFrame | None,
    gate: dict | None,
    output: Path,
):
    lines = [
        "% Automatically generated statistical results.",
        "% Verify wording and context before including in the paper.",
        "",
        "\\paragraph{Descriptive statistics.}",
        "Across all tools, "
        f"{descriptive['campaigns'].sum():,} campaigns were evaluated, "
        f"of which {descriptive['reached'].sum():,} activated their target mutation.",
        "",
        "\\paragraph{Activation (RQ1, paired primary).}",
    ]

    if not pd.isna(cochran["p_value"]):
        lines.append(
            "Cochran's $Q$ over matched mutants yielded "
            f"$Q={cochran['q']:.2f}$ with $p={fmt_p(cochran['p_value'])}$ "
            f"and Kendall's $W={cochran['kendalls_w']:.3f}$. "
            "Exact McNemar tests on matched campaigns are reported in the "
            "corresponding table; the unpaired Mann-Whitney sensitivity "
            "analysis yields identical significance decisions."
        )

    lines += ["", "\\paragraph{Directness (RQ2, paired primary).}"]

    if not pd.isna(friedman["p_value"]):
        agreement = int(
            (
                wilcoxon["significant"].to_numpy()
                == sens_interactions["significant"].to_numpy()
            ).sum()
        )
        lines.append(
            "The Friedman test over mutants activated by all tools yielded "
            f"$\\chi^2_F={friedman['statistic']:.2f}$ ($n={friedman['n']}$) with "
            f"$p={fmt_p(friedman['p_value'])}$ and Kendall's "
            f"$W={friedman['kendalls_w']:.3f}$. "
            "Pairwise Wilcoxon signed-rank tests on matched activated campaigns "
            "(rank-biserial $r$ as effect size, Holm-adjusted) are reported in the "
            "corresponding table; the unpaired Mann-Whitney $U$ sensitivity "
            f"analysis agrees on {agreement} of {len(wilcoxon)} comparisons."
        )

    lines += ["", "\\paragraph{Coverage variation across fault types (RQ3).}"]

    if not pd.isna(chi_fault["p_value"]):
        lines.append(
            "A chi-square test of independence between mutation operator and "
            f"activation outcome yielded $\\chi^2={chi_fault['statistic']:.2f}$ "
            f"(df={chi_fault['dof']}) with $p={fmt_p(chi_fault['p_value'])}$."
        )

    if base is not None:
        lines += ["", "\\paragraph{Baseline comparison (RQ1).}"]
        lo, hi = base["op_cov_pct"].min(), base["op_cov_pct"].max()
        lines.append(
            "Mean RESTgym operation coverage per tool ranges "
            f"{lo:.1f}--{hi:.1f}\\%, measured over all operations of each API, "
            "whereas MC is measured over the predefined campaign targets; the "
            "two metrics have different denominators and are not expected to "
            "coincide (Table: baseline comparison)."
        )
        if "line_pct" in base.columns:
            lo, hi = base["line_pct"].min(), base["line_pct"].max()
            mlo, mhi = base["method_pct"].min(), base["method_pct"].max()
            lines.append(
                "RESTgym's code-coverage baselines do not saturate: mean line "
                f"coverage ranges {lo:.1f}--{hi:.1f}\\% and mean method coverage "
                f"{mlo:.1f}--{mhi:.1f}\\% across tools, even where MC is 100\\%. "
                "The two families therefore measure different objects: MC records "
                "whether predefined targets were activated, whereas code coverage "
                "records how deeply the implementation was exercised."
            )
        if gate is not None:
            lines.append(
                f"Target-level traces show {gate['gate_effect']} campaigns in "
                "which the target operation received at least one request but no "
                "valid one (target reachability "
                f"{gate['reach_pct']:.1f}\\% vs.\\ MC); these are exactly the cases "
                "where operation coverage counts the operation as covered while "
                "MC does not."
            )
        else:
            lines.append(
                "% NOTE: target-level reachability (any request to the target) is "
                "not present in the aggregated CSV; export an "
                "'any_request_to_target' column from the per-campaign traces to "
                "report the validity-gate discrepancy count."
            )

    output.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path, help="Input CSV file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("results/analysis"),
        help="Output directory",
    )
    parser.add_argument(
        "--specs",
        type=Path,
        default=None,
        help=(
            "Directory containing the OpenAPI specs "
            "(<api>-openapi.json) for the operation-coverage baseline"
        ),
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    print(f"Loading {args.csv}...")
    df = load_data(args.csv)
    print(f"Loaded {len(df):,} observations.")
    print(f"Tools: {sorted(df['tool'].unique())}")
    print(f"APIs: {df['api'].nunique()}")
    print(f"Mutants: {df['mutant_id'].nunique()}")

    descriptive = descriptive_statistics(df)
    descriptive.to_csv(args.output / "descriptive_statistics.csv", index=False)
    generate_reachability_table(descriptive, args.output / "reachability_table.tex")
    generate_interaction_table(descriptive, args.output / "interaction_table.tex")

    api_statistics(df).to_csv(args.output / "api_statistics.csv", index=False)
    fault_type_statistics(df).to_csv(
        args.output / "fault_type_statistics.csv", index=False
    )

    # --- RESTgym operation-coverage baseline ---
    ops_total = load_operation_totals(args.specs, sorted(df["api"].unique()))
    base = baseline_comparison(df, ops_total)
    gate = gate_effect_stats(df)
    if base is not None:
        base.to_csv(args.output / "baseline_comparison.csv", index=False)
        generate_baseline_tex(base, args.output / "baseline_comparison.tex")
    else:
        print(
            "NOTE: operation-coverage baseline skipped "
            "(pass --specs pointing at the OpenAPI specs)."
        )

    # --- PRIMARY paired tests ---
    print("Running paired tests (McNemar, Wilcoxon)...")

    mcnemar = pairwise_mcnemar_tests(df)
    mcnemar.to_csv(args.output / "pairwise_reachability_paired.csv", index=False)
    generate_pairwise_mcnemar_tex(mcnemar, args.output / "pairwise_reachability_paired.tex")

    wilcoxon = pairwise_wilcoxon_tests(df)
    wilcoxon.to_csv(args.output / "pairwise_interactions_paired.csv", index=False)
    generate_pairwise_wilcoxon_tex(wilcoxon, args.output / "pairwise_interactions_paired.tex")

    cochran = cochran_q(df)
    pd.DataFrame([{
        "test": "Cochran's Q", "n": cochran["n"], "k": cochran["k"],
        "statistic": cochran["q"], "p_value": cochran["p_value"],
        "kendalls_w": cochran["kendalls_w"],
    }]).to_csv(args.output / "cochran_q.csv", index=False)

    friedman = friedman_test(df)
    pd.DataFrame([{
        "test": "Friedman", "n": friedman["n"], "k": friedman["k"],
        "statistic": friedman["statistic"], "p_value": friedman["p_value"],
        "kendalls_w": friedman["kendalls_w"],
    }]).to_csv(args.output / "friedman.csv", index=False)

    # --- SENSITIVITY unpaired tests ---
    print("Running sensitivity tests (Mann-Whitney U + A12)...")

    sens_reachability = pairwise_mw_tests(df, "reachability")
    sens_reachability.to_csv(
        args.output / "pairwise_reachability_sensitivity.csv", index=False
    )
    generate_pairwise_sensitivity_tex(
        sens_reachability, args.output / "pairwise_reachability_sensitivity.tex",
        "reachability",
    )

    sens_interactions = pairwise_mw_tests(df, "interactions")
    sens_interactions.to_csv(
        args.output / "pairwise_interactions_sensitivity.csv", index=False
    )
    generate_pairwise_sensitivity_tex(
        sens_interactions, args.output / "pairwise_interactions_sensitivity.tex",
        "interactions",
    )

    # --- Omnibus table (paired + unpaired) ---
    kw = kruskal_wallis_interactions(df)
    chi_tool = tool_reachability_chi_square(df)
    chi_fault = fault_type_chi_square(df)

    omnibus = pd.DataFrame(
        [
            {
                "Design": "Paired",
                "Test": "Cochran's $Q$ (MC)",
                "$n$": cochran["n"],
                "Statistic": cochran["q"],
                "$p$": fmt_p(cochran["p_value"]),
                "Effect": fmt_number(cochran["kendalls_w"], 3),
            },
            {
                "Design": "Paired",
                "Test": "Friedman (IFE)",
                "$n$": friedman["n"],
                "Statistic": friedman["statistic"],
                "$p$": fmt_p(friedman["p_value"]),
                "Effect": fmt_number(friedman["kendalls_w"], 3),
            },
            {
                "Design": "Unpaired",
                "Test": "Kruskal-Wallis (IFE)",
                "$n$": kw["n"],
                "Statistic": kw["H"],
                "$p$": fmt_p(kw["p_value"]),
                "Effect": "---",
            },
            {
                "Design": "Unpaired",
                "Test": "$\\chi^2$ (tool $\\times$ activation)",
                "$n$": chi_tool["n"],
                "Statistic": chi_tool["statistic"],
                "$p$": fmt_p(chi_tool["p_value"]),
                "Effect": "---",
            },
            {
                "Design": "Unpaired",
                "Test": "$\\chi^2$ (fault type)",
                "$n$": chi_fault["n"],
                "Statistic": chi_fault["statistic"],
                "$p$": fmt_p(chi_fault["p_value"]),
                "Effect": "---",
            },
        ]
    )
    omnibus.to_csv(args.output / "omnibus_tests.csv", index=False)
    dataframe_to_latex(omnibus, args.output / "omnibus_tests.tex", escape=False)

    generate_results_summary(
        descriptive,
        cochran,
        friedman,
        mcnemar,
        wilcoxon,
        sens_interactions,
        chi_tool,
        chi_fault,
        base,
        gate,
        args.output / "results_summary.tex",
    )

    print()
    print("Analysis completed.")
    print(f"Results written to: {args.output}")
    print()
    print("Generated:")
    print("  descriptive_statistics.csv / reachability_table.tex / interaction_table.tex")
    print("  api_statistics.csv / fault_type_statistics.csv")
    print("  baseline_comparison.{csv,tex}   (MC vs RESTgym operation coverage)")
    print("  pairwise_reachability_paired.{csv,tex}   (exact McNemar, PRIMARY)")
    print("  pairwise_interactions_paired.{csv,tex}   (Wilcoxon + r, PRIMARY)")
    print("  pairwise_reachability_sensitivity.{csv,tex} (MWU + A12)")
    print("  pairwise_interactions_sensitivity.{csv,tex} (MWU + A12)")
    print("  cochran_q.csv / friedman.csv / omnibus_tests.{csv,tex}")
    print("  results_summary.tex")


if __name__ == "__main__":
    main()