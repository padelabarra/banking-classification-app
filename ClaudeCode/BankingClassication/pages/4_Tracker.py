"""
Page 4 — Monthly Budget Tracker.
Compare actual spending vs budget (defaulting to historical averages from Excel).
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.db import get_transactions
from src.analytics import load_budget_defaults, monthly_actuals_by_category

st.set_page_config(page_title="Budget Tracker", page_icon="🎯", layout="wide")
st.title("🎯 Monthly Budget Tracker")

# ── Load transactions ──────────────────────────────────────────────────────────
df_all = get_transactions()

if df_all.empty:
    st.info("No data yet. Run `python train.py` or upload CSVs on the Upload page.")
    st.stop()

df_all["year"] = pd.to_numeric(df_all["year"], errors="coerce").fillna(0).astype(int)
df_all["month"] = pd.to_numeric(df_all["month"], errors="coerce").fillna(0).astype(int)

# ── Available months ───────────────────────────────────────────────────────────
month_pairs = (
    df_all[df_all["activity"] == "Expense"][["year", "month"]]
    .drop_duplicates()
    .sort_values(["year", "month"], ascending=False)
)
month_options = [
    f"{int(r['year'])}-{int(r['month']):02d}"
    for _, r in month_pairs.iterrows()
]

if not month_options:
    st.warning("No expense transactions found.")
    st.stop()

# ── Month selector ─────────────────────────────────────────────────────────────
sel_period = st.selectbox("Select Month", month_options, index=0)
sel_year, sel_month = int(sel_period[:4]), int(sel_period[5:])

MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}
st.subheader(f"{MONTH_NAMES[sel_month]} {sel_year}")

# ── Budget defaults (from Excel col C) ────────────────────────────────────────
budget_defaults = load_budget_defaults()

if not budget_defaults:
    st.error("Could not read budget defaults from Excel. Check that '202406_Presupuesto_MBA.xlsx' exists with a 'Tracker' sheet.")
    st.stop()

# Category display order: big-ticket first, then recurring alphabetically
BIG_TICKET = ["Car", "Pack", "Trips", "Tuition"]
RECURRING = sorted([c for c in budget_defaults if c not in BIG_TICKET])
ORDERED_CATS = BIG_TICKET + RECURRING

# ── Sidebar: editable budgets ──────────────────────────────────────────────────
with st.sidebar:
    st.header("Budget Settings")
    st.caption("Defaults = historical averages from Excel. Edit to override.")

    user_budgets: dict[str, float] = {}
    for cat in ORDERED_CATS:
        default_val = budget_defaults.get(cat, 0.0)
        label = f"{cat} {'(÷12)' if cat in BIG_TICKET else ''}"
        user_budgets[cat] = st.number_input(
            label,
            min_value=0.0,
            value=round(default_val, 2),
            step=10.0,
            format="%.2f",
            key=f"budget_{cat}",
        )

# ── Actuals for selected month ─────────────────────────────────────────────────
actuals = monthly_actuals_by_category(df_all, sel_year, sel_month)

# ── Build comparison dataframe ─────────────────────────────────────────────────
rows = []
for cat in ORDERED_CATS:
    budget = user_budgets.get(cat, 0.0)
    actual = actuals.get(cat, 0.0)
    variance = budget - actual          # positive = under budget (good)
    pct = (actual / budget * 100) if budget > 0 else None
    rows.append({
        "Category": cat,
        "Type": "Big Ticket" if cat in BIG_TICKET else "Recurring",
        "Budget ($)": budget,
        "Actual ($)": actual,
        "Variance ($)": variance,
        "% Used": pct,
    })

tracker_df = pd.DataFrame(rows)

total_budget = tracker_df["Budget ($)"].sum()
total_actual = tracker_df["Actual ($)"].sum()
total_variance = total_budget - total_actual

# ── KPI strip ─────────────────────────────────────────────────────────────────
k1, k2, k3 = st.columns(3)
k1.metric("Total Budget", f"${total_budget:,.0f}")
k2.metric("Total Actual", f"${total_actual:,.0f}")
k3.metric(
    "Surplus / Deficit",
    f"${abs(total_variance):,.0f}",
    delta=f"{'Under' if total_variance >= 0 else 'Over'} budget",
    delta_color="normal" if total_variance >= 0 else "inverse",
)

st.divider()

# ── Comparison table ───────────────────────────────────────────────────────────
st.subheader("Category Breakdown")


display_df = tracker_df.copy()
display_df["% Used"] = display_df["% Used"].apply(
    lambda v: f"{v:.1f}%" if v is not None else "—"
)
display_df["Variance ($)"] = display_df["Variance ($)"].apply(
    lambda v: f"+${v:,.2f}" if v >= 0 else f"-${abs(v):,.2f}"
)
display_df["Budget ($)"] = display_df["Budget ($)"].apply(lambda v: f"${v:,.2f}")
display_df["Actual ($)"] = display_df["Actual ($)"].apply(lambda v: f"${v:,.2f}")

st.dataframe(display_df, use_container_width=True, hide_index=True)

st.caption(
    "🟢 Positive variance = under budget  |  🔴 Negative variance = over budget  "
    "|  Big Ticket budgets shown as annual average ÷ 12"
)

st.divider()

# ── Bar chart ──────────────────────────────────────────────────────────────────
st.subheader("Budget vs Actual by Category")

fig = go.Figure()
fig.add_bar(
    x=tracker_df["Category"],
    y=tracker_df["Budget ($)"],
    name="Budget",
    marker_color="#3498db",
    opacity=0.8,
)

# Parse back numeric variance for coloring
variance_numeric = tracker_df["Variance ($)"]
bar_colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in variance_numeric]

fig.add_bar(
    x=tracker_df["Category"],
    y=tracker_df["Actual ($)"],
    name="Actual",
    marker_color=bar_colors,
    opacity=0.9,
)
fig.update_layout(
    barmode="group",
    xaxis_tickangle=-35,
    yaxis_title="USD",
    legend=dict(orientation="h"),
    height=420,
)
st.plotly_chart(fig, use_container_width=True)
