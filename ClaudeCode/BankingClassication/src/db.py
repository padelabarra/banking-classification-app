"""
SQLite database operations.
"""
import logging
import pathlib
import sqlite3
import hashlib
import pandas as pd

logger = logging.getLogger(__name__)

DB_PATH = pathlib.Path(__file__).parent.parent / "data" / "transactions.db"


def _connect(path: pathlib.Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def init_db(path: pathlib.Path = DB_PATH):
    """Create tables if they don't exist."""
    con = _connect(path)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            date             DATE,
            description      TEXT,
            amount           REAL,
            source           TEXT,
            activity         TEXT,
            category         TEXT,
            year             INTEGER,
            month            INTEGER,
            manually_reviewed BOOLEAN DEFAULT 0,
            dedup_key        TEXT UNIQUE,
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
        CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category);
        CREATE INDEX IF NOT EXISTS idx_transactions_source ON transactions(source);
        """
    )
    con.commit()
    con.close()


def _make_dedup_key(date_val, description: str, amount: float, source: str) -> str:
    raw = f"{date_val}|{description.strip().lower()}|{round(amount, 2)}|{source}"
    return hashlib.sha256(raw.encode()).hexdigest()


def check_duplicates(df: pd.DataFrame, path: pathlib.Path = DB_PATH) -> pd.Series:
    """
    Returns a boolean Series (same index as df) — True if the row already exists in DB.
    Matching is done on (date, description, amount, source).
    Uses a single batched IN query instead of N per-row lookups.
    """
    init_db(path)
    con = _connect(path)

    keys = []
    for _, row in df.iterrows():
        date_val = row.get("date")
        date_str = str(date_val)[:10] if hasattr(date_val, "year") else str(date_val)
        keys.append(_make_dedup_key(
            date_str,
            str(row.get("description", "")),
            float(row.get("amount", 0)),
            str(row.get("source", "")),
        ))

    if keys:
        placeholders = ",".join("?" * len(keys))
        existing = {
            r[0] for r in con.execute(
                f"SELECT dedup_key FROM transactions WHERE dedup_key IN ({placeholders})",
                keys,
            )
        }
    else:
        existing = set()

    con.close()
    return pd.Series([k in existing for k in keys], index=df.index)


def upsert_transactions(df: pd.DataFrame, path: pathlib.Path = DB_PATH) -> dict:
    """
    Insert new transactions; skip duplicates.

    Args:
        df: DataFrame with columns: date, description, amount, source, activity, category

    Returns:
        {'inserted': int, 'skipped': int}
    """
    init_db(path)
    con = _connect(path)
    inserted = 0
    skipped = 0

    for _, row in df.iterrows():
        date_val = row.get("date")
        description = str(row.get("description", ""))
        amount = float(row.get("amount", 0))
        source = str(row.get("source", ""))
        activity = str(row.get("activity", ""))
        category = str(row.get("category", "Miscellaneous"))
        manually_reviewed = int(row.get("manually_reviewed", 0))

        if isinstance(date_val, str):
            date_val = pd.to_datetime(date_val, errors="coerce")
        if hasattr(date_val, "year"):
            year = date_val.year
            month = date_val.month
            date_str = str(date_val)[:10]
        else:
            year = None
            month = None
            date_str = str(date_val)

        dedup_key = _make_dedup_key(date_str, description, amount, source)

        try:
            con.execute(
                """
                INSERT INTO transactions
                    (date, description, amount, source, activity, category, year, month,
                     manually_reviewed, dedup_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (date_str, description, amount, source, activity, category,
                 year, month, manually_reviewed, dedup_key),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1

    con.commit()
    con.close()
    return {"inserted": inserted, "skipped": skipped}


def get_transactions(
    path: pathlib.Path = DB_PATH,
    year: int | None = None,
    month: int | None = None,
    source: str | None = None,
    category: str | None = None,
    activity: str | None = None,
) -> pd.DataFrame:
    """Read transactions with optional filters."""
    init_db(path)
    con = _connect(path)

    # Build WHERE clause from trusted column names only; values go in params
    clauses = []
    params = []
    if year is not None:          # Fix: `if year` would be False for year=0
        clauses.append("year = ?")
        params.append(year)
    if month is not None:         # Fix: same for month
        clauses.append("month = ?")
        params.append(month)
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    if activity is not None:
        clauses.append("activity = ?")
        params.append(activity)

    query = "SELECT * FROM transactions"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY date DESC"

    df = pd.read_sql_query(query, con, params=params)
    con.close()
    return df


def update_transaction(tx_id: int, updates: dict, path: pathlib.Path = DB_PATH):
    """Update specific fields on a transaction by id."""
    allowed = {"activity", "category", "manually_reviewed"}
    safe_updates = {k: v for k, v in updates.items() if k in allowed}
    if not safe_updates:
        return
    con = _connect(path)
    sets = ", ".join(f"{k} = ?" for k in safe_updates)
    vals = list(safe_updates.values())
    con.execute(f"UPDATE transactions SET {sets} WHERE id = ?", [*vals, tx_id])
    con.commit()
    con.close()


def get_monthly_summary(path: pathlib.Path = DB_PATH) -> pd.DataFrame:
    """Return monthly totals by activity."""
    init_db(path)
    con = _connect(path)
    df = pd.read_sql_query(
        """
        SELECT year, month, activity, SUM(amount) as total, COUNT(*) as count
        FROM transactions
        GROUP BY year, month, activity
        ORDER BY year, month
        """,
        con,
    )
    con.close()
    return df


def get_category_totals(
    year: int | None = None,
    month: int | None = None,
    activity: str | None = None,
    path: pathlib.Path = DB_PATH,
) -> pd.DataFrame:
    """Return totals per category with optional filters."""
    init_db(path)
    con = _connect(path)

    # Fix: default to Expense only when no activity override is given
    clauses = []
    params = []
    if activity is not None:
        clauses.append("activity = ?")
        params.append(activity)
    else:
        clauses.append("activity = 'Expense'")
    if year is not None:
        clauses.append("year = ?")
        params.append(year)
    if month is not None:
        clauses.append("month = ?")
        params.append(month)

    query = (
        "SELECT category, SUM(ABS(amount)) as total, COUNT(*) as count "
        "FROM transactions WHERE " + " AND ".join(clauses) +
        " GROUP BY category ORDER BY total DESC"
    )
    df = pd.read_sql_query(query, con, params=params)
    con.close()
    return df
