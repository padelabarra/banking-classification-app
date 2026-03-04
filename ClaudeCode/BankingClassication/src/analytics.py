"""
Aggregations for dashboard charts.
"""
import pandas as pd


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Monthly Revenue vs Expense totals.
    Returns: year, month, period, revenue, expense, net
    """
    if df.empty:
        return pd.DataFrame(columns=["year", "month", "period", "revenue", "expense", "net"])

    df = df.copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)

    g = (
        df.groupby(["year", "month", "activity"])["amount"]
        .sum()
        .unstack(fill_value=0)
        .reset_index()
    )

    if "Revenue" not in g.columns:
        g["Revenue"] = 0.0
    if "Expense" not in g.columns:
        g["Expense"] = 0.0

    g["expense"] = g["Expense"].abs()
    g["revenue"] = g["Revenue"]
    g["net"] = g["revenue"] - g["expense"]
    g["period"] = g.apply(lambda r: f"{int(r['year'])}-{int(r['month']):02d}", axis=1)

    return g[["year", "month", "period", "revenue", "expense", "net"]].sort_values(
        ["year", "month"]
    )


def category_breakdown(df: pd.DataFrame, activity: str = "Expense") -> pd.DataFrame:
    """
    Total by category for a given activity filter.
    Returns: category, total (absolute), count
    """
    if df.empty:
        return pd.DataFrame(columns=["category", "total", "count"])

    filtered = df[df["activity"] == activity].copy()
    filtered["amount"] = pd.to_numeric(filtered["amount"], errors="coerce").fillna(0)

    result = (
        filtered.groupby("category")["amount"]
        .agg(total="sum", count="count")
        .reset_index()
    )
    result["total"] = result["total"].abs()
    return result.sort_values("total", ascending=False)


def category_trend(df: pd.DataFrame, top_n: int = 8) -> pd.DataFrame:
    """
    Monthly totals per top-N categories over time.
    Returns: period, category, total
    """
    if df.empty:
        return pd.DataFrame(columns=["period", "category", "total"])

    expenses = df[df["activity"] == "Expense"].copy()
    expenses["amount"] = pd.to_numeric(expenses["amount"], errors="coerce").fillna(0).abs()
    expenses["period"] = expenses.apply(
        lambda r: f"{int(r['year'])}-{int(r['month']):02d}", axis=1
    )

    # Top N categories by overall spend
    top_cats = (
        expenses.groupby("category")["amount"].sum().nlargest(top_n).index.tolist()
    )
    filtered = expenses[expenses["category"].isin(top_cats)]

    result = (
        filtered.groupby(["period", "category"])["amount"].sum().reset_index(name="total")
    )
    return result.sort_values("period")


def source_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Expense totals by source."""
    if df.empty:
        return pd.DataFrame(columns=["source", "total", "count"])

    expenses = df[df["activity"] == "Expense"].copy()
    expenses["amount"] = pd.to_numeric(expenses["amount"], errors="coerce").fillna(0).abs()

    return (
        expenses.groupby("source")["amount"]
        .agg(total="sum", count="count")
        .reset_index()
        .sort_values("total", ascending=False)
    )


def cumulative_net(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly net savings with running cumulative."""
    summary = monthly_summary(df)
    if summary.empty:
        return summary
    summary = summary.sort_values(["year", "month"])
    summary["cumulative_net"] = summary["net"].cumsum()
    return summary
