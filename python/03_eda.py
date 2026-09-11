"""Exploratory data analysis — write figures to output/figures/."""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

IN      = Path("data/processed/features.csv")
FIG_DIR = Path("output/figures")


def main() -> None:
    df = pd.read_csv(IN)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    # Target distribution
    fig, ax = plt.subplots()
    df["y"].value_counts().plot.bar(ax=ax, color=["#4878d0", "#ee854a"])
    ax.set_title("Term Deposit Subscription")
    ax.set_xticklabels(["No", "Yes"], rotation=0)
    fig.savefig(FIG_DIR / "target_dist.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # Age distribution by outcome
    fig, ax = plt.subplots()
    for label, group in df.groupby("y"):
        ax.hist(group["age"], bins=30, alpha=0.6, label=f"y={label}")
    ax.set_xlabel("Age")
    ax.legend()
    fig.savefig(FIG_DIR / "age_by_outcome.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # Correlation heatmap (numeric cols only, top 15 by variance)
    numeric = df.select_dtypes("number")
    top_cols = numeric.var().nlargest(15).index.tolist()
    fig, ax = plt.subplots(figsize=(10, 8))
    sns.heatmap(numeric[top_cols].corr(), annot=True, fmt=".2f", cmap="coolwarm", ax=ax)
    fig.savefig(FIG_DIR / "correlation_heatmap.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"[03_eda] Figures → {FIG_DIR}/")


if __name__ == "__main__":
    main()
