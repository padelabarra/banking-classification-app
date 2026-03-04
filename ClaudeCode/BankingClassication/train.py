"""
One-time training script:
  1. Extract labeled transactions from Excel (Gasto_BofA sheet)
  2. Save training CSV
  3. Train ML model → save to data/model/classifier.pkl
  4. Import all historical transactions into SQLite DB

Usage:
    python train.py
    python train.py --excel path/to/file.xlsx
"""
import argparse
import pathlib
import sys

import pandas as pd

# Allow running from any directory
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.rules import normalize_category, CATEGORIES
from src.ml_model import TransactionClassifier, MODEL_PATH
from src.db import upsert_transactions, init_db, DB_PATH

EXCEL_PATH = ROOT / "202406_Presupuesto_MBA.xlsx"
TRAINING_CSV = ROOT / "data" / "training_data.csv"

SOURCE_MAP = {
    "Cuenta Corriente": "checking",
    "Tarjeta Credito Pedro": "cc_pedro",
    "Tarjeta Credito Renatta": "cc_renatta",
}


def load_excel(excel_path: pathlib.Path) -> pd.DataFrame:
    print(f"[train] Reading {excel_path} ...")
    df = pd.read_excel(str(excel_path), sheet_name="Gasto_BofA")
    print(f"[train] Raw rows: {len(df)}, columns: {df.columns.tolist()}")
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    # Keep only needed columns
    needed = ["Date", "Description", "Amount", "Activity", "Type", "Year", "Month", "Fuente"]
    df = df[[c for c in needed if c in df.columns]].copy()
    df = df.rename(columns={"Type": "category", "Fuente": "source_raw"})

    # Drop rows missing key fields
    df = df.dropna(subset=["Description", "category"])
    df["Description"] = df["Description"].astype(str).str.strip()
    df["category"] = df["category"].astype(str).str.strip().apply(normalize_category)
    df["activity"] = df["Activity"].astype(str).str.strip() if "Activity" in df.columns else "Expense"
    df["source"] = df["source_raw"].map(SOURCE_MAP).fillna("checking")
    df["amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    df["date"] = pd.to_datetime(df["Date"], errors="coerce")
    # Fix: df.get() is a dict method, not a DataFrame method — check column existence explicitly
    df["year"] = df["Year"].fillna(df["date"].dt.year) if "Year" in df.columns else df["date"].dt.year
    df["month"] = df["Month"].fillna(df["date"].dt.month) if "Month" in df.columns else df["date"].dt.month

    # Lowercase description for ML features
    df["description"] = df["Description"]

    return df[["date", "description", "amount", "source", "activity", "category", "year", "month"]]


def train_model(df: pd.DataFrame) -> dict:
    model = TransactionClassifier()
    print("[train] Training ML model ...")
    report = model.train(df)
    accuracy = report.get("accuracy", 0)
    print(f"[train] Accuracy: {accuracy:.1%}")
    model.save(MODEL_PATH)
    return report


def import_to_db(df: pd.DataFrame):
    print(f"[train] Importing {len(df)} transactions to SQLite ...")
    init_db(DB_PATH)
    stats = upsert_transactions(df, DB_PATH)
    print(f"[train] Inserted: {stats['inserted']}, Skipped (duplicates): {stats['skipped']}")


def main():
    parser = argparse.ArgumentParser(description="Train banking classifier from Excel")
    parser.add_argument(
        "--excel",
        default=str(EXCEL_PATH),
        help="Path to the Excel file (default: 202406_Presupuesto_MBA.xlsx)",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip importing historical data to SQLite",
    )
    args = parser.parse_args()

    excel_path = pathlib.Path(args.excel)
    if not excel_path.exists():
        print(f"[train] ERROR: Excel file not found: {excel_path}")
        sys.exit(1)

    # 1. Load + clean
    raw_df = load_excel(excel_path)
    df = clean(raw_df)
    print(f"[train] Clean rows: {len(df)}")
    print(f"[train] Categories: {sorted(df['category'].unique())}")

    # 2. Save training CSV
    TRAINING_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(TRAINING_CSV, index=False)
    print(f"[train] Training data saved to {TRAINING_CSV}")

    # 3. Train model
    report = train_model(df)

    # 4. Import to DB
    if not args.no_db:
        import_to_db(df)
    else:
        print("[train] Skipping DB import (--no-db flag set)")

    print("\n[train] Done! Summary:")
    print(f"  Rows trained:  {len(df)}")
    print(f"  Categories:    {df['category'].nunique()}")
    print(f"  Accuracy:      {report.get('accuracy', 0):.1%}")
    print(f"  Model path:    {MODEL_PATH}")
    print(f"  DB path:       {DB_PATH}")


if __name__ == "__main__":
    main()
