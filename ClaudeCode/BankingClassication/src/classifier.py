"""
Hybrid classifier orchestrator: rules → ML → fallback.
"""
import threading
import pathlib
from src.rules import classify as rule_classify
from src.ml_model import TransactionClassifier, MODEL_PATH

_ml_model: TransactionClassifier | None = None
_ml_model_lock = threading.Lock()           # Fix: thread-safe lazy loading
ML_CONFIDENCE_THRESHOLD = 0.75


def _get_ml() -> TransactionClassifier:
    global _ml_model
    with _ml_model_lock:
        if _ml_model is None:
            _ml_model = TransactionClassifier.load(MODEL_PATH)
    return _ml_model


def reload_ml():
    """Force reload the ML model from disk (call after training)."""
    global _ml_model
    with _ml_model_lock:
        _ml_model = TransactionClassifier.load(MODEL_PATH)


def classify(description: str, amount: float, source: str) -> dict:
    """
    Hybrid classify a single transaction.

    Returns:
        {
            activity: str,
            category: str,
            confidence: float,
            method: 'rule' | 'ml' | 'fallback',
            needs_review: bool,
        }
    """
    # 1. Rule-based
    rule_activity, rule_category, rule_confidence = rule_classify(description, amount, source)
    if rule_confidence >= 0.85:
        return {
            "activity": rule_activity,
            "category": rule_category,
            "confidence": rule_confidence,
            "method": "rule",
            "needs_review": False,
        }

    # 2. ML
    ml = _get_ml()
    if ml.is_trained():
        ml_activity, ml_category, ml_confidence = ml.predict(description, amount, source)

        if ml_confidence >= ML_CONFIDENCE_THRESHOLD:
            # Fix: if rule matched category but returned None activity, trust ML for activity.
            # Only override with rule activity when it's explicitly set (not None).
            final_activity = rule_activity if rule_activity is not None else ml_activity
            return {
                "activity": final_activity,
                "category": ml_category,
                "confidence": ml_confidence,
                "method": "ml",
                "needs_review": False,
            }

        # Neither fully confident — pick the better one and flag for review
        if ml_confidence > rule_confidence:
            return {
                "activity": ml_activity,
                "category": ml_category,
                "confidence": ml_confidence,
                "method": "ml",
                "needs_review": True,
            }

    # 3. Use partial rule match if available
    if rule_category:
        return {
            "activity": rule_activity,
            "category": rule_category,
            "confidence": rule_confidence,
            "method": "rule",
            "needs_review": True,
        }

    # 4. Absolute fallback
    inferred_activity = "Revenue" if amount > 0 else "Expense"
    return {
        "activity": inferred_activity,
        "category": "Miscellaneous",
        "confidence": 0.0,
        "method": "fallback",
        "needs_review": True,
    }


def classify_dataframe(df):
    """Classify all rows in a parsed DataFrame, adding result columns."""
    import pandas as pd

    results = []
    for _, row in df.iterrows():
        res = classify(
            description=str(row.get("description", "")),
            amount=float(row.get("amount", 0)),
            source=str(row.get("source", "")),
        )
        results.append(res)

    res_df = pd.DataFrame(results)
    out = df.copy()
    out["activity"] = res_df["activity"].values
    out["category"] = res_df["category"].values
    out["confidence"] = res_df["confidence"].values
    out["method"] = res_df["method"].values
    out["needs_review"] = res_df["needs_review"].values
    return out
