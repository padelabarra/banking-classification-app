"""
Page 1 — Upload CSV, classify, review, and save to DB.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from src.parsers import parse_csv, CHECKING, CC_PEDRO, CC_RENATTA
from src.classifier import classify_dataframe, reload_ml
from src.rules import CATEGORIES
from src.db import upsert_transactions, check_duplicates

st.set_page_config(page_title="Upload Transactions", page_icon="📤", layout="wide")
st.title("📤 Upload & Classify Transactions")

# ── Row status constants ─────────────────────────────────────────────────────
S_DUPLICATE = "🔁 Already in DB"
S_REVIEW    = "⚠️ Needs Review"
S_READY     = "✅ Ready"

# Row background colors used in the Styler preview
BG = {
    S_DUPLICATE: "#ffd6d6",   # soft red
    S_REVIEW:    "#fff3cd",   # soft yellow
    S_READY:     "#d4edda",   # soft green
}

# ── Source selection ─────────────────────────────────────────────────────────
SOURCE_OPTIONS = {
    "Auto-detect": None,
    "Cuenta Corriente (Checking)": CHECKING,
    "Tarjeta Credito Pedro (CC Pedro)": CC_PEDRO,
    "Tarjeta Credito Renatta (CC Renatta)": CC_RENATTA,
}

col1, col2 = st.columns([2, 1])
with col1:
    uploaded_files = st.file_uploader(
        "Upload one or more BofA CSV exports",
        type=["csv"],
        accept_multiple_files=True,
    )
with col2:
    source_label = st.selectbox("Account Source", list(SOURCE_OPTIONS.keys()))
    source_code = SOURCE_OPTIONS[source_label]

if not uploaded_files:
    st.info("Upload a CSV file to get started.")
    st.stop()

# ── Parse ────────────────────────────────────────────────────────────────────
all_parsed = []
for f in uploaded_files:
    try:
        parsed = parse_csv(f.read(), source=source_code)
        parsed["_filename"] = f.name
        all_parsed.append(parsed)
    except Exception as e:
        st.error(f"Error parsing {f.name}: {e}")

if not all_parsed:
    st.stop()

raw_df = pd.concat(all_parsed, ignore_index=True)
raw_df = raw_df[raw_df["description"].str.strip() != ""].reset_index(drop=True)

# ── Classify + duplicate check ───────────────────────────────────────────────
with st.spinner("Classifying and checking for duplicates..."):
    classified = classify_dataframe(raw_df)
    is_dup = check_duplicates(raw_df)

classified["is_duplicate"] = is_dup.values

# Build status column (duplicate takes priority over review)
def _status(row):
    if row["is_duplicate"]:
        return S_DUPLICATE
    if row["needs_review"]:
        return S_REVIEW
    return S_READY

classified["status"] = classified.apply(_status, axis=1)

# ── Summary metrics ──────────────────────────────────────────────────────────
n_ready = (classified["status"] == S_READY).sum()
n_review = (classified["status"] == S_REVIEW).sum()
n_dup = (classified["status"] == S_DUPLICATE).sum()

st.markdown(f"Parsed **{len(classified)}** transactions from **{len(uploaded_files)}** file(s).")

m1, m2, m3 = st.columns(3)
m1.metric("✅ Ready to save", n_ready)
m2.metric("⚠️ Needs review", n_review, delta=f"low confidence" if n_review else None,
          delta_color="off")
m3.metric("🔁 Already in DB", n_dup, delta="will be skipped" if n_dup else None,
          delta_color="off")

if n_dup > 0:
    st.warning(
        f"**{n_dup}** transaction(s) already exist in the database and are **excluded by default**. "
        "You can tick the Include checkbox to force-insert them anyway."
    )

# ── Color-coded preview (read-only Styler) ───────────────────────────────────
st.subheader("Preview")

with st.expander("Color legend", expanded=False):
    st.markdown(
        f"<span style='background:{BG[S_READY]};padding:2px 8px'>✅ Ready</span> &nbsp;"
        f"<span style='background:{BG[S_REVIEW]};padding:2px 8px'>⚠️ Needs Review</span> &nbsp;"
        f"<span style='background:{BG[S_DUPLICATE]};padding:2px 8px'>🔁 Already in DB</span>",
        unsafe_allow_html=True,
    )

preview_cols = ["status", "date", "description", "amount", "source", "activity", "category", "confidence"]
preview = classified[preview_cols].copy()
preview["date"] = preview["date"].astype(str)
preview["amount"] = preview["amount"].round(2)
preview["confidence"] = (preview["confidence"] * 100).round(1).astype(str) + "%"

def _color_row(row):
    color = BG.get(row["status"], "")
    return [f"background-color: {color}"] * len(row)

styled = preview.style.apply(_color_row, axis=1)
st.dataframe(styled, use_container_width=True, hide_index=True, height=380)

# ── Editable table — corrections + include/exclude ───────────────────────────
st.subheader("Correct & Select")
st.caption("Edit Activity / Category for ⚠️ rows. Uncheck **Include** to skip a row.")

edit_cols = ["status", "date", "description", "amount", "activity", "category"]
edit_df = classified[edit_cols].copy()
edit_df["date"] = edit_df["date"].astype(str)
edit_df["amount"] = edit_df["amount"].round(2)
# Include = True for non-duplicates, False for duplicates by default
edit_df["include"] = (classified["status"] != S_DUPLICATE).values

edited = st.data_editor(
    edit_df,
    column_config={
        "status":      st.column_config.TextColumn("Status", disabled=True, width="small"),
        "date":        st.column_config.TextColumn("Date", disabled=True, width="small"),
        "description": st.column_config.TextColumn("Description", disabled=True, width="large"),
        "amount":      st.column_config.NumberColumn("Amount", format="$%.2f", disabled=True, width="small"),
        "activity":    st.column_config.SelectboxColumn("Activity", options=["Revenue", "Expense"], width="small"),
        "category":    st.column_config.SelectboxColumn("Category", options=sorted(CATEGORIES), width="medium"),
        "include":     st.column_config.CheckboxColumn("Include", width="tiny"),
    },
    use_container_width=True,
    num_rows="fixed",
    key="review_table",
)

to_save_count = int(edited["include"].sum())

# ── Save ─────────────────────────────────────────────────────────────────────
st.divider()
col_save, col_info = st.columns([1, 3])

with col_save:
    save_btn = st.button(
        f"💾 Save {to_save_count} transaction(s)",
        type="primary",
        use_container_width=True,
        disabled=(to_save_count == 0),
    )

with col_info:
    if to_save_count == 0:
        st.info("No rows selected to save.")
    else:
        st.caption(f"{to_save_count} rows will be inserted · {len(edited) - to_save_count} skipped")

if save_btn:
    include_mask = edited["include"].values
    # Use classified as the source of truth — indexes are aligned after reset_index above
    save_df = classified[include_mask][["date", "description", "amount", "source"]].copy()
    save_df["activity"] = edited.loc[include_mask, "activity"].values
    save_df["category"] = edited.loc[include_mask, "category"].values
    save_df["manually_reviewed"] = (
        classified[include_mask]["status"] == S_REVIEW
    ).astype(int).values

    try:
        with st.spinner("Saving..."):
            stats = upsert_transactions(save_df)
    except Exception as e:
        st.error(f"Failed to save transactions: {e}")
        st.stop()

    st.success(
        f"Done! Inserted **{stats['inserted']}** new transactions. "
        f"Skipped **{stats['skipped']}** duplicates."
    )
    if stats["inserted"] > 0:
        st.balloons()

# ── Retrain hint ─────────────────────────────────────────────────────────────
with st.expander("Retrain ML model"):
    st.markdown("After reviewing and saving corrections, retrain the ML model to improve future accuracy.")
    if st.button("🔄 Reload ML Model from Disk"):
        reload_ml()
        st.success("ML model reloaded.")
