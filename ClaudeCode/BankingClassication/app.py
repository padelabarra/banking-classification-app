"""
Banking Classification App — main entry point.
Run with: streamlit run app.py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Banking Classifier",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)


def check_password() -> bool:
    """
    Password gate using st.secrets.
    Returns True if the user has entered the correct password.
    If no secrets.toml exists (local dev without it), bypasses the gate.
    """
    try:
        correct_password = st.secrets["password"]
    except (FileNotFoundError, KeyError):
        return True

    if st.session_state.get("password_correct"):
        return True

    with st.form("login_form"):
        st.subheader("🔐 Login")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Enter")

    if submitted:
        if password == correct_password:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    return False


if not check_password():
    st.stop()

# ── App content (only shown after successful login) ───────────────────────────
st.title("🏦 Banking Classification App")
st.markdown(
    """
    Welcome! Use the sidebar to navigate between pages.

    | Page | Description |
    |------|-------------|
    | **1 · Upload** | Upload a BofA CSV, classify transactions, save to DB |
    | **2 · Transactions** | Browse, filter, and edit all stored transactions |
    | **3 · Dashboard** | Charts and monthly analysis |
    | **4 · Budget Tracker** | Monthly budget vs actual spending |

    ---
    **First time?** Run `python train.py` in the project directory to load historical data
    and train the ML model.
    """
)

from src.db import get_transactions, init_db, DB_PATH

init_db(DB_PATH)
df = get_transactions()
if not df.empty:
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Transactions", f"{len(df):,}")
    min_date = pd.to_datetime(df["date"], errors="coerce").min()
    max_date = pd.to_datetime(df["date"], errors="coerce").max()
    date_range = (
        f"{min_date.strftime('%Y-%m')} → {max_date.strftime('%Y-%m')}"
        if pd.notna(min_date) and pd.notna(max_date) else "N/A"
    )
    col2.metric("Date Range", date_range)
    col3.metric("Total Net", f"${df['amount'].sum():,.0f}")
else:
    st.info("No transactions yet.")
