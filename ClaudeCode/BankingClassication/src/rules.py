"""
Rule-based keyword classifier.
Returns (activity, category, confidence) or (None, None, 0) if no match.
"""
import logging
import re

logger = logging.getLogger(__name__)

# Canonical category names (normalizing typos/case variants from Excel)
# Note: "Dinning&Activities" preserves the original spelling from the Excel data
# to avoid breaking existing DB records.
CATEGORIES = [
    "Wire",
    "Dinning&Activities",
    "Living Expenses",
    "Housing",
    "Car",
    "Groceries",
    "Pack",
    "Online Shopping",
    "Parking",
    "Car Gasoline / Transportation",
    "Clothing and Accessories",
    "Car Insurance",
    "Trips",
    "Tuition",
    "Miscellaneous",
    "Credit Card - Pedro",
    "Credit Card - Renatta",
    "Renatta's Work",
    "Renatta's Studies",
    "Renatta's Expenses",
    "Apartment Rent",
    "Renatta's Savings",
    "Amazon Stipend",
    "Insurance",
    "Pedro's Internship",
]

_CATEGORIES_SET = set(CATEGORIES)

# Normalize raw category strings from Excel
_CATEGORY_MAP = {
    "living expenses": "Living Expenses",
    "dinning&activities": "Dinning&Activities",
    "dining&activities": "Dinning&Activities",
}


def normalize_category(raw: str) -> str:
    """Normalize a raw category string to a canonical CATEGORIES value."""
    if not raw:
        return "Miscellaneous"
    key = raw.strip().lower()
    normalized = _CATEGORY_MAP.get(key, raw.strip())
    # Fix: validate against known categories; fall back to Miscellaneous if unknown
    if normalized not in _CATEGORIES_SET:
        logger.warning(f"Unknown category '{normalized}' — mapping to Miscellaneous")
        return "Miscellaneous"
    return normalized


# ---------------------------------------------------------------------------
# Rule tuples: (pattern, activity, category, confidence)
#   pattern: compiled regex applied to lowercase description
#   activity: 'Revenue' | 'Expense' | None (None = infer from amount sign)
#   confidence: float 0–1
# ---------------------------------------------------------------------------

_RULES = [
    # ---------- Revenue sources ----------
    (re.compile(r"amazon\.com svcs.*(payroll|direct dep)", re.I), "Revenue", "Pedro's Internship", 0.98),
    (re.compile(r"graebel holdings", re.I), "Revenue", "Amazon Stipend", 0.98),
    (re.compile(r"nium pte ltd.*estudios", re.I), "Revenue", "Renatta's Savings", 0.97),
    (re.compile(r"renatta vaccaro.*estudios", re.I), "Revenue", "Renatta's Savings", 0.97),
    (re.compile(r"zelle payment from.*janna ramirez", re.I), "Revenue", "Renatta's Work", 0.97),
    (re.compile(r"zelle payment from.*catalina.*gana", re.I), "Revenue", "Renatta's Work", 0.97),
    (re.compile(r"zelle payment from.*sebastian smith", re.I), "Revenue", "Apartment Rent", 0.97),
    (re.compile(r"zelle payment from.*uyeol jeon", re.I), "Revenue", "Apartment Rent", 0.97),
    (re.compile(r"zelle payment from.*nicole dosal", re.I), "Revenue", "Renatta's Savings", 0.95),
    (re.compile(r"zelle payment from.*jose abalos", re.I), "Revenue", "Dinning&Activities", 0.90),
    (re.compile(r"zelle payment from.*joaquin leonart", re.I), "Revenue", "Dinning&Activities", 0.90),
    (re.compile(r"zelle payment from", re.I), "Revenue", "Dinning&Activities", 0.70),
    (re.compile(r"counter credit", re.I), "Revenue", "Wire", 0.95),
    (re.compile(r"preferred rewards.wire fee waiver", re.I), "Revenue", "Wire", 0.95),

    # ---------- Wire transfers ----------
    (re.compile(r"wire type:wire in", re.I), None, "Wire", 0.98),
    (re.compile(r"wire transfer fee", re.I), "Expense", "Wire", 0.98),
    (re.compile(r"usend.*pontual", re.I), None, "Wire", 0.97),
    (re.compile(r"bank of america.*payment.*crd (1956|7860)", re.I), "Expense", "Wire", 0.95),
    (re.compile(r"online banking payment to crd 7860", re.I), "Expense", "Credit Card - Pedro", 0.98),
    (re.compile(r"online banking payment to crd 1956", re.I), "Expense", "Credit Card - Renatta", 0.98),
    (re.compile(r"online payment from chk 9208", re.I), "Revenue", "Credit Card - Pedro", 0.90),
    (re.compile(r"bank of america credit card bill payment", re.I), "Expense", "Credit Card - Pedro", 0.85),
    (re.compile(r"payment\s*-\s*thank you", re.I), "Revenue", "Credit Card - Pedro", 0.85),

    # ---------- Apartment / Housing ----------
    (re.compile(r"zelle payment to.*lucas tort", re.I), "Expense", "Housing", 0.90),
    (re.compile(r"zelle payment to.*pedro leon", re.I), "Expense", "Housing", 0.88),
    (re.compile(r"zelle payment to.*eufrasia", re.I), "Expense", "Apartment Rent", 0.92),
    (re.compile(r"zelle payment to.*sebastian smith", re.I), "Expense", "Apartment Rent", 0.92),
    (re.compile(r"zelle payment to.*yui nadalin", re.I), "Expense", "Housing", 0.88),
    (re.compile(r"zelle payment to.*soongook hong.*tv", re.I), "Expense", "Housing", 0.88),
    (re.compile(r"zelle payment to.*jennifer sellers.*tv", re.I), "Expense", "Housing", 0.88),
    (re.compile(r"wire type:wire in.*mora restrepo", re.I), "Revenue", "Apartment Rent", 0.97),
    (re.compile(r"zelle payment to.*sebastian smith.*garantia", re.I), "Expense", "Apartment Rent", 0.95),

    # ---------- Car ----------
    (re.compile(r"zelle payment to.*vicente fernandez auto", re.I), "Expense", "Car", 0.98),
    (re.compile(r"fd \*ca dmv", re.I), "Expense", "Car", 0.97),
    (re.compile(r"vioc gn", re.I), "Expense", "Car", 0.90),

    # ---------- Car Insurance ----------
    (re.compile(r"geico \*auto", re.I), "Expense", "Car Insurance", 0.99),
    (re.compile(r"progressive \*insurance", re.I), "Expense", "Car Insurance", 0.99),
    (re.compile(r"state farm.*insurance", re.I), "Expense", "Car Insurance", 0.99),

    # ---------- Gasoline / Transportation ----------
    (re.compile(r"shell oil|shell \d+", re.I), "Expense", "Car Gasoline / Transportation", 0.97),
    (re.compile(r"chevron \d+", re.I), "Expense", "Car Gasoline / Transportation", 0.97),
    (re.compile(r"sinaco oil", re.I), "Expense", "Car Gasoline / Transportation", 0.97),
    (re.compile(r"uber \*trip", re.I), "Expense", "Car Gasoline / Transportation", 0.95),
    (re.compile(r"lyft \*ride", re.I), "Expense", "Car Gasoline / Transportation", 0.95),
    (re.compile(r"waymo", re.I), "Expense", "Car Gasoline / Transportation", 0.95),
    (re.compile(r"doug's service", re.I), "Expense", "Car Gasoline / Transportation", 0.90),

    # ---------- Groceries ----------
    (re.compile(r"ralphs #", re.I), "Expense", "Groceries", 0.97),
    (re.compile(r"trader joe", re.I), "Expense", "Groceries", 0.97),
    (re.compile(r"whole foods", re.I), "Expense", "Groceries", 0.97),
    (re.compile(r"costco", re.I), "Expense", "Groceries", 0.95),
    (re.compile(r"wal.?mart|wal wal-mart", re.I), "Expense", "Groceries", 0.90),
    (re.compile(r"target #", re.I), "Expense", "Groceries", 0.88),
    (re.compile(r"cvs/pharmacy|cvs pharmacy", re.I), "Expense", "Groceries", 0.88),
    (re.compile(r"7-eleven", re.I), "Expense", "Groceries", 0.82),
    (re.compile(r"smart.*final|smart final", re.I), "Expense", "Groceries", 0.92),
    (re.compile(r"sprouts", re.I), "Expense", "Groceries", 0.92),

    # ---------- Online Shopping ----------
    (re.compile(r"amazon mktpl|amazon mark|amazon mktplace", re.I), "Expense", "Online Shopping", 0.95),
    (re.compile(r"amazon prime\*", re.I), "Expense", "Online Shopping", 0.90),
    (re.compile(r"amazon reta\*", re.I), "Expense", "Online Shopping", 0.90),
    (re.compile(r"kindle svcs", re.I), "Expense", "Online Shopping", 0.90),
    (re.compile(r"netflix", re.I), "Expense", "Online Shopping", 0.95),
    (re.compile(r"spotify", re.I), "Expense", "Online Shopping", 0.95),
    (re.compile(r"apple\.com/bill", re.I), "Expense", "Online Shopping", 0.88),

    # ---------- Parking ----------
    (re.compile(r"city of santa monica.*parking|santa monica parking", re.I), "Expense", "Parking", 0.97),
    (re.compile(r"hermosa beach parking", re.I), "Expense", "Parking", 0.97),
    (re.compile(r"united valet parking", re.I), "Expense", "Parking", 0.97),
    (re.compile(r"\bparking\b", re.I), "Expense", "Parking", 0.85),

    # ---------- Tuition ----------
    (re.compile(r"ucla des:onlinepymt", re.I), "Expense", "Tuition", 0.98),
    (re.compile(r"harvard bus education", re.I), "Expense", "Tuition", 0.97),
    (re.compile(r"\btuition\b", re.I), "Expense", "Tuition", 0.90),

    # ---------- Renatta's Studies ----------
    (re.compile(r"ucla extension cashier", re.I), "Expense", "Renatta's Studies", 0.98),
    (re.compile(r"bravo for you", re.I), "Expense", "Renatta's Studies", 0.85),

    # ---------- Insurance ----------
    (re.compile(r"sure renters insurance", re.I), "Expense", "Insurance", 0.99),
    (re.compile(r"renters insurance", re.I), "Expense", "Insurance", 0.95),

    # ---------- Living Expenses ----------
    (re.compile(r"wash laundry mobile", re.I), "Expense", "Living Expenses", 0.97),
    (re.compile(r"ladwp|la dwp|city of la dwp", re.I), "Expense", "Living Expenses", 0.97),
    (re.compile(r"swift smog", re.I), "Expense", "Living Expenses", 0.90),
    (re.compile(r"wepaprinting", re.I), "Expense", "Living Expenses", 0.85),

    # ---------- Pack ----------
    (re.compile(r"natalia rodriguez pack", re.I), "Expense", "Pack", 0.98),
    (re.compile(r"\bpack\b.*ucla|ucla.*\bpack\b", re.I), "Expense", "Pack", 0.90),

    # ---------- Clothing and Accessories ----------
    (re.compile(r"ross stores", re.I), "Expense", "Clothing and Accessories", 0.85),
    (re.compile(r"tjmaxx|tj maxx", re.I), "Expense", "Clothing and Accessories", 0.90),
    (re.compile(r"crossroads gp", re.I), "Expense", "Clothing and Accessories", 0.90),
]

# Zelle-specific amount-based rules handled in classify()
_ZELLE_PAT = re.compile(r"zelle payment to", re.I)


def classify(description: str, amount: float, source: str) -> tuple[str | None, str | None, float]:
    """
    Apply rule-based classification.

    Returns:
        (activity, category, confidence)
        activity/category are None if no rule matches.
        confidence is 0.0 if no match.
    """
    desc = description or ""

    for pattern, activity, category, confidence in _RULES:
        if pattern.search(desc):
            # Infer activity from amount sign if not hardcoded in the rule
            if activity is None:
                activity = "Revenue" if amount > 0 else "Expense"
            return activity, category, confidence

    # Zelle TO someone: small → Dinning&Activities, large → Wire
    if _ZELLE_PAT.search(desc):
        activity = "Expense"
        if abs(amount) >= 1000:
            return activity, "Wire", 0.72
        else:
            return activity, "Dinning&Activities", 0.72

    return None, None, 0.0
