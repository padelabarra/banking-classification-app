"""
BofA CSV parsers.
Normalizes all formats to: {date, description, amount, source, raw_row}
"""
import io
import logging
import pandas as pd

logger = logging.getLogger(__name__)

SOURCES = {
    "checking": "Cuenta Corriente",
    "cc_pedro": "Tarjeta Credito Pedro",
    "cc_renatta": "Tarjeta Credito Renatta",
}

SOURCE_LABELS = {v: k for k, v in SOURCES.items()}

# Canonical source codes
CHECKING = "checking"
CC_PEDRO = "cc_pedro"
CC_RENATTA = "cc_renatta"


def _read_csv_skip_header(content: bytes) -> pd.DataFrame:
    """BofA CSVs sometimes have intro lines before the header row."""
    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines()

    # Find the header line (contains 'Date' and 'Amount')
    header_idx = None
    for i, line in enumerate(lines):
        if "Date" in line and "Amount" in line:
            header_idx = i
            break

    # Fix: raise clearly instead of silently treating data as header
    if header_idx is None:
        raise ValueError(
            "Could not find a CSV header row containing 'Date' and 'Amount'. "
            "Make sure you are uploading a BofA export file."
        )

    clean = "\n".join(lines[header_idx:])
    return pd.read_csv(io.StringIO(clean))


def _detect_source(df: pd.DataFrame) -> str:
    """Auto-detect format from column names."""
    cols = [c.strip().lower() for c in df.columns]
    if "payee" in cols or "address" in cols:
        return None  # credit card format — caller must specify pedro/renatta
    if "running bal." in cols or "running bal" in cols:
        return CHECKING
    return None


def parse_csv(content: bytes, source: str | None = None) -> pd.DataFrame:
    """
    Parse a BofA CSV export.

    Args:
        content: raw bytes of the CSV file
        source: one of 'checking', 'cc_pedro', 'cc_renatta'.
                If None, auto-detected (works reliably only for checking).

    Returns:
        DataFrame with columns: date, description, amount, source, raw_row
    """
    df = _read_csv_skip_header(content)
    df.columns = [c.strip() for c in df.columns]

    detected = _detect_source(df)
    if source is None:
        source = detected or CHECKING  # fallback

    if detected == CHECKING or (source == CHECKING and "Running Bal." in df.columns):
        return _parse_checking(df, source)
    else:
        return _parse_credit_card(df, source)


def _parse_checking(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """
    Checking account format:
        Date | Description | Amount | Running Bal.
    """
    rows = []
    for idx, row in df.iterrows():
        try:
            date = pd.to_datetime(str(row.get("Date", "")).strip(), errors="coerce")
            description = str(row.get("Description", "")).strip()
            amount_raw = str(row.get("Amount", "0")).replace(",", "").strip()
            amount = float(amount_raw) if amount_raw else 0.0
            raw = row.to_dict()
            rows.append(
                {
                    "date": date.date() if pd.notna(date) else None,
                    "description": description,
                    "amount": amount,
                    "source": source,
                    "raw_row": str(raw),
                }
            )
        except Exception as e:
            logger.warning(f"Skipped checking row {idx} due to parse error: {e}")
            continue
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result[result["description"].notna() & (result["description"] != "")]


def _parse_credit_card(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """
    Credit card format (two variants):
        Date | Payee | Address | Amount
        Date | Posted Date | Reference | Payee | Address | Amount
    """
    cols_lower = {c.lower(): c for c in df.columns}
    date_col = cols_lower.get("date")
    payee_col = cols_lower.get("payee")
    amount_col = cols_lower.get("amount")

    rows = []
    for idx, row in df.iterrows():
        try:
            date = pd.to_datetime(str(row.get(date_col, "")).strip(), errors="coerce")
            description = str(row.get(payee_col, "")).strip()
            amount_raw = str(row.get(amount_col, "0")).replace(",", "").strip()
            amount = float(amount_raw) if amount_raw else 0.0
            # CC exports show debits as positive — invert sign to match checking convention
            # (negative = expense, positive = credit/payment)
            amount = -amount
            raw = row.to_dict()
            rows.append(
                {
                    "date": date.date() if pd.notna(date) else None,
                    "description": description,
                    "amount": amount,
                    "source": source,
                    "raw_row": str(raw),
                }
            )
        except Exception as e:
            logger.warning(f"Skipped credit card row {idx} due to parse error: {e}")
            continue
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result[result["description"].notna() & (result["description"] != "")]
