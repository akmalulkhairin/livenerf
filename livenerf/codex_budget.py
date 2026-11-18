import json
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

WEEKLY_POINTS = 20
ACCOUNT_STOP = 50
METER_HEADROOM = 1


class BudgetStop(RuntimeError):
    pass


def daily_capacity(reservation):
    required = 7 * reservation + METER_HEADROOM
    return {
        "weekly_cap_points": WEEKLY_POINTS,
        "minimum_weekly_reservation_points": required,
        "maximum_days_per_week": min(7, (WEEKLY_POINTS - METER_HEADROOM) // reservation),
        "supports_daily_series": required <= WEEKLY_POINTS,
    }


def usage_percent(window):
    percent = window["usedPercent"]
    if type(percent) is not int or not 0 <= percent <= 100:
        raise BudgetStop("Invalid Codex usage percentage")
    return percent


def check_account(limits, points=0):
    weekly = limits["primary"]
    reset = weekly["resetsAt"]
    if weekly["windowDurationMins"] != 10080 or type(reset) is not int or reset <= time.time():
        raise BudgetStop("No current weekly Codex window")
    used = usage_percent(weekly)
    secondary = limits.get("secondary")
    if max(used, usage_percent(secondary) if secondary else 0) + points + METER_HEADROOM > ACCOUNT_STOP:
        raise BudgetStop("Account usage has reached the study stop")
    return used, reset


def reserve(path, limits, points, *, weekly_points=WEEKLY_POINTS):
    used, reset = check_account(limits, points)
    state = json.loads(path.read_text()) if path.exists() else {"reset": reset, "start": used, "peak": used, "reserved": 0}
    if time.time() >= state["reset"]:
        if reset <= state["reset"]:
            raise BudgetStop("Codex has not confirmed a new weekly window")
        state = {"reset": reset, "start": used, "peak": used, "reserved": 0}
    state["peak"] = max(state["peak"], used)
    observed = state["peak"] - state["start"]
    state["reserved"] += points
    reserved = observed + state["reserved"]
    if reserved + METER_HEADROOM > weekly_points:
        raise BudgetStop("The study has reached its weekly allowance")
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
        json.dump(state, file)
    Path(file.name).replace(path)
    return used, reserved
