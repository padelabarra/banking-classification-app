"""
Page 2 — Browse, filter, and edit all stored transactions.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from src.db import get_transactions, update_transaction, DB_PATH
from src.rules import CATEGORIES

st.set_page_config(page_title="Transactions", page_icon="📋", layout="wide")
st.title("📋 All Transactions")

# ── Filters ──────────────────────────────────────────────────────────────────
df_all = get_transactions()

if df_all.empty:
    st.info("No transactions in the database yet. Use the Upload page to add some.")
    st.stop()

df_all["date"] = pd.to_datetime(df_all["date"], errors="coerce")
df_all["year"] = df_all["year"].fillna(df_all["date"].dt.year).astype("Int64")
df_all["month"] = df_all["month"].fillna(df_all["date"].dt.month).astype("Int64")

with st.sidebar:
    st.header("Filters")
    years = sorted(df_all["year"].dropna().unique().tolist(), reverse=True)
    sel_years = st.multiselect("Year", years, default=years[:2] if len(years) >= 2 else years)

    months = list(range(1, 13))
    month_names = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
                   7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}
    sel_months = st.multiselect("Month", months, format_func=lambda m: month_names[m])

    sources = sorted(df_all["source"].dropna().unique().tolist())
    sel_sources = st.multiselect("Source", sources, default=sources)

    categories = sorted(df_all["category"].dropna().unique().tolist())
    sel_cats = st.multiselect("Category", categories, default=categories)

    activities = ["Revenue", "Expense"]
    sel_acts = st.multiselect("Activity", activities, default=activities)

    search_text = st.text_input("Search description")

# ── Apply filters ─────────────────────────────────────────────────────────────
mask = pd.Series([True] * len(df_all))
if sel_years:
    mask &= df_all["year"].isin(sel_years)
if sel_months:
    mask &= df_all["month"].isin(sel_months)
if sel_sources:
    mask &= df_all["source"].isin(sel_sources)
if sel_cats:
    mask &= df_all["category"].isin(sel_cats)
if sel_acts:
    mask &= df_all["activity"].isin(sel_acts)
if search_text:
    mask &= df_all["description"].str.contains(search_text, case=False, na=False, regex=False)

df_filtered = df_all[mask].copy()
st.caption(f"Showing **{len(df_filtered):,}** of **{len(df_all):,}** transactions")

# ── Summary row ───────────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
revenue = df_filtered[df_filtered["activity"] == "Revenue"]["amount"].sum()
expense = df_filtered[df_filtered["activity"] == "Expense"]["amount"].sum()
col1.metric("Revenue", f"${revenue:,.0f}")
col2.metric("Expenses", f"${abs(expense):,.0f}")
col3.metric("Net", f"${revenue + expense:,.0f}")
col4.metric("Transactions", f"{len(df_filtered):,}")

st.divider()

# ── Editable table ────────────────────────────────────────────────────────────
display = df_filtered[["id", "date", "description", "amount", "source", "activity", "category", "manually_reviewed"]].copy()
display["date"] = display["date"].astype(str).str[:10]
display["amount"] = display["amount"].round(2)

edited = st.data_editor(
    display,
    column_config={
        "id": st.column_config.NumberColumn("ID", disabled=True, width="tiny"),
        "date": st.column_config.TextColumn("Date", disabled=True, width="small"),
        "description": st.column_config.TextColumn("Description", disabled=True, width="large"),
        "amount": st.column_config.NumberColumn("Amount", format="$%.2f", disabled=True, width="small"),
        "source": st.column_config.TextColumn("Source", disabled=True, width="small"),
        "activity": st.column_config.SelectboxColumn("Activity", options=["Revenue", "Expense"], width="small"),
        "category": st.column_config.SelectboxColumn("Category", options=sorted(CATEGORIES), width="medium"),
        "manually_reviewed": st.column_config.CheckboxColumn("Reviewed", width="small"),
    },
    use_container_width=True,
    num_rows="fixed",
    key="tx_table",
)

# ── Save edits ────────────────────────────────────────────────────────────────
col_save, col_export = st.columns([1, 1])

with col_save:
    if st.button("💾 Save Changes", type="primary"):
        # Detect changed rows — use label-based .loc to avoid index mismatch after filtering
        changed = 0
        for idx, new_row in edited.iterrows():
            orig = display.loc[idx]
            if (new_row["activity"] != orig["activity"] or
                new_row["category"] != orig["category"] or
                new_row["manually_reviewed"] != orig["manually_reviewed"]):
                update_transaction(
                    int(new_row["id"]),
                    {
                        "activity": new_row["activity"],
                        "category": new_row["category"],
                        "manually_reviewed": int(new_row["manually_reviewed"]),
                    },
                )
                changed += 1

        if changed:
            st.success(f"Updated {changed} transaction(s).")
            st.rerun()
        else:
            st.info("No changes detected.")

with col_export:
    csv_bytes = df_filtered.to_csv(index=False).encode()
    st.download_button(
        "⬇️ Export to CSV",
        data=csv_bytes,
        file_name="transactions_export.csv",
        mime="text/csv",
        use_container_width=True,
    )
