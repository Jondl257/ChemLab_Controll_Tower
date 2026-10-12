"""Central, deliberately synthetic demo configuration."""
from datetime import timedelta

APP_TITLE = "ChemLab Control Tower"
SEED = 20261006
PRIMARY = "#004A96"
COLORS = {"pass": "#16794A", "near_limit": "#B06D00", "oos": "#B42318", "neutral": "#667085"}
SLA_HOURS = {"Routine": 24, "Produktion dringend": 4, "Stabilitätsprobe": 72}
DEMO_DAYS = 45
NEAR_LIMIT_FRACTION = 0.10
MIN_STAT_N = 2

def deadline(received_at, order_type: str):
    return received_at + timedelta(hours=SLA_HOURS[order_type])
