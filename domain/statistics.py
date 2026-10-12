import numpy as np
import pandas as pd
from config import MIN_STAT_N

def process_statistics(values: pd.Series, lsl: float | None, usl: float | None) -> dict:
    x = pd.to_numeric(values, errors="coerce").dropna()
    base = {"n": len(x), "mean": None, "median": None, "std": None, "min": None, "max": None,
            "cp": None, "cpk": None, "ucl": None, "lcl": None}
    if len(x) < MIN_STAT_N: return base
    mean, std = float(x.mean()), float(x.std(ddof=1))
    base.update({"mean": mean, "median": float(x.median()), "std": std, "min": float(x.min()),
                 "max": float(x.max()), "ucl": mean + 3 * std, "lcl": mean - 3 * std})
    if std > 0 and lsl is not None and usl is not None:
        base["cp"] = (usl - lsl) / (6 * std)
        base["cpk"] = min((usl - mean) / (3 * std), (mean - lsl) / (3 * std))
    return base
