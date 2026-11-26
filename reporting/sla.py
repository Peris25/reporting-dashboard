from datetime import datetime

import pandas as pd

RESPONSE_SLA_HOURS = 0.5
DIAGNOSIS_SLA_HOURS = 2
CLOSURE_SLA_HOURS = 48


def parse_datetime(value):
    return pd.to_datetime(value, errors="coerce", utc=True)


def reported_time(ticket):
    value = ticket.get("Reported At", "")
    return value if pd.notna(value) and str(value).strip() else ticket.get("Created", "")


def elapsed_hours(start, end):
    start_dt, end_dt = parse_datetime(start), parse_datetime(end)
    if pd.isna(start_dt) or pd.isna(end_dt) or end_dt < start_dt:
        return None
    return (end_dt - start_dt).total_seconds() / 3600


def classify_sla(start, end, target_hours, now=None):
    start_dt, end_dt = parse_datetime(start), parse_datetime(end)
    if pd.isna(start_dt):
        return "Unknown"
    if pd.isna(end_dt) and pd.notna(end) and str(end).strip():
        return "Invalid"
    effective_end = end_dt if pd.notna(end_dt) else parse_datetime(now or datetime.now().astimezone())
    hours = elapsed_hours(start_dt, effective_end)
    if hours is None:
        return "Invalid"
    if pd.isna(end_dt):
        return "Pending" if hours <= target_hours else "Breached"
    return "Within SLA" if hours <= target_hours else "Breached"


def breach_rate(series):
    measured = series.isin(["Within SLA", "Breached"])
    return round(float((series[measured] == "Breached").mean() * 100), 1) if measured.any() else 0.0


def enrich_tickets(df, diagnosis_target=DIAGNOSIS_SLA_HOURS, resolution_target=CLOSURE_SLA_HOURS, now=None,
                   response_target=RESPONSE_SLA_HOURS):
    result = df.copy()
    for field in ["Created", "First Response At", "Diagnosed At", "Resolved At", "Closed At", "Updated At", "Status"]:
        if field not in result:
            result[field] = ""
    result["Created_dt"] = pd.to_datetime(result["Created"], errors="coerce", utc=True)
    result["Created Month"] = result["Created_dt"].dt.tz_convert("Africa/Nairobi").dt.strftime("%Y-%m")
    current = parse_datetime(now or datetime.now().astimezone())
    reported = result.get("Reported At", pd.Series("", index=result.index))
    start = pd.to_datetime(
        reported.where(reported.notna() & reported.astype(str).str.strip().ne(""), result["Created"]),
        errors="coerce", utc=True, format="mixed",
    )
    result["Reported_dt"] = start
    closed = result["Status"].astype(str).str.strip().str.lower().eq("closed")
    open_age = (current - start).dt.total_seconds().div(3600)
    for label, field, target in [
        ("Response", "First Response At", response_target),
        ("Diagnosis", "Diagnosed At", diagnosis_target),
        ("Closure", "Closed At", resolution_target),
    ]:
        recorded = result[field].notna() & result[field].astype(str).str.strip().ne("")
        end = pd.to_datetime(result[field], errors="coerce", utc=True, format="mixed")
        elapsed = (end - start).dt.total_seconds().div(3600)
        result[f"{label} Hours"] = elapsed.where(elapsed.ge(0))
        effective_hours = elapsed.where(end.notna(), open_age)
        outcome = pd.Series("Within SLA", index=result.index, dtype=str)
        outcome = outcome.mask(end.isna(), "Pending")
        outcome = outcome.mask(effective_hours.gt(target), "Breached")
        outcome = outcome.mask(effective_hours.lt(0) | (recorded & end.isna()), "Invalid")
        outcome = outcome.mask(start.isna(), "Unknown")
        result[f"{label} SLA"] = outcome.mask(closed & ~recorded, "Not recorded")

    result["Resolution Hours"] = result["Closure Hours"]
    result["Resolution SLA"] = result["Closure SLA"]
    result["Open Hours"] = open_age.clip(lower=0)
    result.loc[result["Status"].eq("closed"), "Open Hours"] = float("nan")
    result["Age Days"] = result["Open Hours"].div(24).round(1)
    return result


def format_duration(hours):
    if pd.isna(hours):
        return "—"
    return f"{hours * 60:.0f} min" if hours < 1 else f"{hours:.1f} h"


def sla_summary(view):
    rows = []
    for label, target in [("Response", "30 minutes"), ("Diagnosis", "2 hours"), ("Closure", "48 hours")]:
        outcomes = view[f"{label} SLA"]
        completed = view[f"{label} Hours"].notna() & outcomes.isin(["Within SLA", "Breached"])
        count = int(completed.sum())
        rows.append({
            "Milestone": label, "Target": target,
            "Average time": format_duration(view.loc[completed, f"{label} Hours"].mean()),
            "On time": f"{100 * outcomes[completed].eq('Within SLA').mean():.0f}%" if count else "—",
            "Recorded": count,
            "Waiting": int(outcomes.eq("Pending").sum()),
            "Overdue": int((outcomes.eq("Breached") & ~completed).sum()),
            "Completed late": int((outcomes.eq("Breached") & completed).sum()),
            "Missing / invalid": int(outcomes.isin(["Not recorded", "Unknown", "Invalid"]).sum()),
        })
    return pd.DataFrame(rows)


def overdue_milestones(view):
    return pd.DataFrame({
        label: view[f"{label} SLA"].eq("Breached") & view[f"{label} Hours"].isna() & view["Status"].ne("closed")
        for label in ["Response", "Diagnosis", "Closure"]
    }, index=view.index)
