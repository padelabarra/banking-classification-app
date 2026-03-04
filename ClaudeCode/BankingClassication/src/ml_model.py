"""
ML classifier: TF-IDF + Logistic Regression fallback.
"""
import logging
import pathlib
import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

logger = logging.getLogger(__name__)

MODEL_PATH = pathlib.Path(__file__).parent.parent / "data" / "model" / "classifier.pkl"

# Expected keys in the saved model artifact — used to validate before loading
_EXPECTED_KEYS = {"pipeline", "label_encoder", "activity_map"}


def _build_feature(description: str, amount: float, source: str) -> str:
    """Build a single text feature string."""
    bucket = _amount_bucket(amount)
    src = source.replace("_", " ")
    return f"{description} AMT_{bucket} SRC_{src}"


def _build_features(df: pd.DataFrame) -> list[str]:
    """Combine description + amount bucket + source into text features."""
    return [
        _build_feature(
            str(row.get("description", "")),
            row.get("amount", 0),
            str(row.get("source", "")),
        )
        for _, row in df.iterrows()
    ]


def _amount_bucket(amount: float) -> str:
    a = abs(amount)
    if a == 0:
        return "zero"
    elif a < 10:
        return "tiny"
    elif a < 50:
        return "small"
    elif a < 200:
        return "medium"
    elif a < 1000:
        return "large"
    elif a < 5000:
        return "xlarge"
    else:
        return "huge"


class TransactionClassifier:
    def __init__(self):
        self.pipeline: Pipeline | None = None
        self.activity_map: dict[str, str] = {}  # category → typical activity
        self.label_encoder = LabelEncoder()

    def train(self, df: pd.DataFrame) -> dict:
        """
        Train on a DataFrame with columns: description, amount, source, activity, category.
        Returns classification metrics dict.
        """
        df = df.dropna(subset=["description", "category"]).copy()
        df["category"] = df["category"].str.strip()

        X = _build_features(df)
        y = df["category"].values

        self.label_encoder.fit(y)
        y_enc = self.label_encoder.transform(y)

        # Build activity map (category → most common activity)
        for cat in df["category"].unique():
            mask = df["category"] == cat
            acts = df.loc[mask, "activity"].value_counts()
            self.activity_map[cat] = acts.index[0] if len(acts) > 0 else "Expense"

        # Only stratify if all classes have >= 2 members
        counts = pd.Series(y_enc).value_counts()
        can_stratify = (counts >= 2).all()
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_enc, test_size=0.15, random_state=42,
            stratify=y_enc if can_stratify else None,
        )

        self.pipeline = Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        ngram_range=(1, 2),
                        min_df=1,
                        max_features=8000,
                        sublinear_tf=True,
                    ),
                ),
                (
                    "lr",
                    LogisticRegression(
                        C=5.0,
                        max_iter=1000,
                        solver="lbfgs",
                    ),
                ),
            ]
        )
        self.pipeline.fit(X_train, y_train)

        y_pred = self.pipeline.predict(X_test)
        present_labels = sorted(set(y_test) | set(y_pred))
        label_names = self.label_encoder.inverse_transform(present_labels)
        report = classification_report(
            y_test, y_pred, labels=present_labels, target_names=label_names,
            output_dict=True, zero_division=0,
        )
        accuracy = report.get("accuracy", 0)
        print(f"[ML] Test accuracy: {accuracy:.1%}")
        return report

    def predict(self, description: str, amount: float, source: str) -> tuple[str, str, float]:
        """Returns (activity, category, confidence)."""
        if self.pipeline is None:
            return "Expense", "Miscellaneous", 0.0

        feature = [_build_feature(description, amount, source)]   # Fix: no DataFrame overhead
        proba = self.pipeline.predict_proba(feature)[0]
        idx = int(np.argmax(proba))
        confidence = float(proba[idx])
        category = self.label_encoder.classes_[idx]
        activity = self.activity_map.get(category, "Expense")
        if amount > 0:
            activity = "Revenue"
        return activity, category, confidence

    def save(self, path: pathlib.Path = MODEL_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"pipeline": self.pipeline, "label_encoder": self.label_encoder, "activity_map": self.activity_map},
            path,
        )
        print(f"[ML] Model saved to {path}")

    @classmethod
    def load(cls, path: pathlib.Path = MODEL_PATH) -> "TransactionClassifier":
        obj = cls()
        if not path.exists():
            return obj

        # Fix: validate file is within expected project directory before loading
        try:
            resolved = path.resolve()
            expected_parent = MODEL_PATH.parent.resolve()
            if resolved.parent != expected_parent:
                raise ValueError(f"Model file {resolved} is outside expected directory {expected_parent}")
        except Exception as e:
            logger.error(f"Model path validation failed: {e}")
            return obj

        try:
            data = joblib.load(path)
        except Exception as e:
            logger.error(f"Failed to load model from {path}: {e}")
            return obj

        # Validate the loaded artifact has expected structure
        if not isinstance(data, dict) or not _EXPECTED_KEYS.issubset(data.keys()):
            logger.error(f"Model artifact at {path} has unexpected structure. Expected keys: {_EXPECTED_KEYS}")
            return obj

        obj.pipeline = data["pipeline"]
        obj.label_encoder = data["label_encoder"]
        obj.activity_map = data["activity_map"]
        return obj

    def is_trained(self) -> bool:
        return self.pipeline is not None
