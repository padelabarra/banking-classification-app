"""
Page 3 — Dashboard with Plotly charts.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.db import get_transactions
from src.analytics import (
    monthly_summary,
    category_breakdown,
    category_trend,
    source_breakdown,
    cumulative_net,
)

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
st.title("📊 Financial Dashboard")

# ── Load data ──────────────────────────────────────────────────────────────────
df_all = get_transactions()

if df_all.empty:
    st.info("No data yet. Run `python train.py` or upload CSVs on the Upload page.")
    st.stop()

df_all["date"] = pd.to_datetime(df_all["date"], errors="coerce")
df_all["year"] = pd.to_numeric(df_all["year"], errors="coerce").fillna(0).astype(int)
df_all["month"] = pd.to_numeric(df_all["month"], errors="coerce").fillna(0).astype(int)

# ── Sidebar filters ────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    all_years = sorted(df_all["year"].unique().tolist(), reverse=True)
    sel_years = st.multiselect("Year", all_years, default=all_years)

    all_sources = sorted(df_all["source"].dropna().unique().tolist())
    sel_sources = st.multiselect("Source", all_sources, default=all_sources)

    all_cats = sorted(df_all["category"].dropna().unique().tolist())
    sel_cats = st.multiselect("Category (exclude)", all_cats, default=[])

# Apply filters
mask = df_all["year"].isin(sel_years) & df_all["source"].isin(sel_sources)
if sel_cats:
    mask &= ~df_all["category"].isin(sel_cats)
df = df_all[mask].copy()

# ── KPI row ───────────────────────────────────────────────────────────────────
revenue_total = df[df["activity"] == "Revenue"]["amount"].sum()
expense_total = df[df["activity"] == "Expense"]["amount"].abs().sum()
net_total = revenue_total - expense_total
tx_count = len(df)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Revenue", f"${revenue_total:,.0f}")
k2.metric("Total Expenses", f"${expense_total:,.0f}")
k3.metric("Net Savings", f"${net_total:,.0f}", delta=f"${net_total:,.0f}")
k4.metric("Transactions", f"{tx_count:,}")

st.divider()

# ── Chart 1: Monthly Revenue vs Expense ───────────────────────────────────────
summary = monthly_summary(df)

if not summary.empty:
    st.subheader("Monthly Revenue vs Expenses")
    fig1 = go.Figure()
    fig1.add_bar(x=summary["period"], y=summary["revenue"], name="Revenue", marker_color="#2ecc71")
    fig1.add_bar(x=summary["period"], y=summary["expense"], name="Expenses", marker_color="#e74c3c")
    fig1.add_scatter(
        x=summary["period"], y=summary["net"], name="Net",
        mode="lines+markers", line=dict(color="#3498db", width=2),
    )
    fig1.update_layout(
        barmode="group", xaxis_title="Month", yaxis_title="USD",
        legend=dict(orientation="h"), height=380,
    )
    st.plotly_chart(fig1, use_container_width=True)

# ── Chart 2 & 3 side by side ──────────────────────────────────────────────────
col_left, col_right = st.columns(2)

with col_left:
    # Filter to most recent month in view
    if not summary.empty:
        latest_period = summary.sort_values(["year", "month"]).iloc[-1]
        latest_year = int(latest_period["year"])
        latest_month = int(latest_period["month"])
    else:
        latest_year, latest_month = None, None

    st.subheader("Category Breakdown (Latest Month)")
    cat_df = category_breakdown(df[
        (df["year"] == latest_year) & (df["month"] == latest_month)
    ] if latest_year else df)

    if not cat_df.empty:
        fig2 = px.pie(
            cat_df, values="total", names="category",
            hole=0.4, color_discrete_sequence=px.colors.qualitative.Set3,
        )
        fig2.update_traces(textposition="inside", textinfo="percent+label")
        fig2.update_layout(height=380, showlegend=True)
        st.plotly_chart(fig2, use_container_width=True)

with col_right:
    st.subheader("Expenses by Source")
    src_df = source_breakdown(df)
    if not src_df.empty:
        fig3 = px.bar(
            src_df, x="source", y="total",
            color="source", text_auto=".2s",
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig3.update_layout(height=380, showlegend=False, yaxis_title="USD")
        st.plotly_chart(fig3, use_container_width=True)

# ── Chart 4: Category Trend over time ────────────────────────────────────────
st.subheader("Top Category Trends Over Time")
trend_df = category_trend(df, top_n=8)
if not trend_df.empty:
    fig4 = px.line(
        trend_df, x="period", y="total", color="category",
        markers=True, color_discrete_sequence=px.colors.qualitative.T10,
    )
    fig4.update_layout(height=380, xaxis_title="Month", yaxis_title="USD")
    st.plotly_chart(fig4, use_container_width=True)

# ── Chart 5: Cumulative Net Savings ──────────────────────────────────────────
st.subheader("Cumulative Net Savings")
cum_df = cumulative_net(df)
if not cum_df.empty:
    fig5 = go.Figure()
    fig5.add_bar(
        x=cum_df["period"], y=cum_df["net"], name="Monthly Net",
        marker_color=cum_df["net"].apply(lambda v: "#2ecc71" if v >= 0 else "#e74c3c"),
    )
    fig5.add_scatter(
        x=cum_df["period"], y=cum_df["cumulative_net"],
        name="Cumulative", mode="lines+markers",
        line=dict(color="#3498db", width=2),
    )
    fig5.update_layout(
        height=350, xaxis_title="Month", yaxis_title="USD",
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig5, use_container_width=True)

# ── Chart 6: All Categories Table for current filters ──────────────────────
with st.expander("Category Totals Table"):
    cat_all = category_breakdown(df)
    if not cat_all.empty:
        cat_all["total"] = cat_all["total"].round(2)
        st.dataframe(
            cat_all.rename(columns={"total": "Total ($)", "count": "# Transactions"}),
            use_container_width=True,
            hide_index=True,
        )
