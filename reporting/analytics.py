import math

import pandas as pd

from reporting.sla import (
    RESPONSE_SLA_HOURS, DIAGNOSIS_SLA_HOURS, CLOSURE_SLA_HOURS,
    classify_sla, elapsed_hours, format_duration, parse_datetime, reported_time,
)

MILESTONES = [
    ("Response", "First Response At", RESPONSE_SLA_HOURS),
    ("Diagnosis", "Diagnosed At", DIAGNOSIS_SLA_HOURS),
    ("Closure", "Closed At", CLOSURE_SLA_HOURS),
]


def filter_requests(df, status="All statuses", priority="All priorities", month="All months",
                    owner="All agents", search=""):
    view = df.copy()
    for field, value, all_value in [
        ("Status", status, "All statuses"), ("Priority", priority, "All priorities"),
        ("Created Month", month, "All months"),
    ]:
        if value != all_value:
            view = view.loc[view[field].eq(value)]
    owners = view["Assignee"].fillna("").astype(str).str.strip()
    if owner != "All agents":
        view = view.loc[owners.eq("" if owner == "Unassigned" else owner)]
    if search.strip():
        fields = ["Ticket ID", "Support Request Number", "Reg No", "Job Request ID", "Requester Name", "Summary", "Status", "Priority", "Assignee"]
        searchable = view[fields].fillna("").astype(str)
        matches = searchable.apply(lambda col: col.str.lower().str.contains(search.strip().lower(), regex=False))
        view = view.loc[matches.any(axis=1)]
    return view.sort_values("Created_dt", ascending=True, na_position="last")


def remaining_time(hours):
    minutes = max(1, math.ceil(abs(hours) * 60 - 1e-9))
    if minutes < 60:
        return f"{minutes} min"
    days, remainder = divmod(minutes, 1440)
    hours, minutes = divmod(remainder, 60)
    return (f"{days}d " if days else "") + f"{hours}h {minutes}m"


def milestone_deadlines(ticket, now=None):
    now = parse_datetime(now) if now is not None else pd.Timestamp.now(tz="UTC")
    created = parse_datetime(reported_time(ticket))
    entries = []
    for label, field, target in MILESTONES:
        value = ticket.get(field, "")
        outcome = classify_sla(created, value, target, now)
        if pd.notna(value) and str(value).strip():
            duration = elapsed_hours(created, value)
            if duration is None:
                tone, text = "warning", f"{label}: check recorded time"
            else:
                tone = "success" if outcome == "Within SLA" else "warning"
                text = f"{label} recorded after {format_duration(duration)} ({'on time' if tone == 'success' else 'late'})"
        elif str(ticket.get("Status", "")).lower() == "closed":
            tone, text = "info", f"{label}: time not recorded"
        elif pd.isna(created) or now < created:
            tone, text = "warning", f"{label}: check logging time"
        else:
            remaining = target - (now - created).total_seconds() / 3600
            if remaining < 0:
                tone, text = "error", f"{label} overdue by {remaining_time(remaining)}"
            else:
                tone = "warning" if remaining <= min(target * 0.2, 0.5) else "info"
                text = f"{label} due in {remaining_time(remaining)}" if remaining else f"{label} due now"
        entries.append({"milestone": label, "tone": tone, "text": text})
    return entries


def weekly_report(df, now=None):
    """Compare adjacent seven-day windows using each milestone's actual date."""
    end = parse_datetime(now) if now is not None else pd.Timestamp.now(tz="UTC")
    created = pd.to_datetime(df["Created"], errors="coerce", utc=True, format="mixed")
    reported = pd.to_datetime(pd.Series([reported_time(row) for _, row in df.iterrows()], index=df.index, dtype=str), errors="coerce", utc=True, format="mixed")
    closed = pd.to_datetime(df["Closed At"], errors="coerce", utc=True, format="mixed")
    periods = []
    for start, stop in [(end - pd.Timedelta(days=7), end), (end - pd.Timedelta(days=14), end - pd.Timedelta(days=7))]:
        closing = closed.ge(start) & closed.lt(stop) & df["Status"].eq("closed")
        values = {"Requests logged": int((created.ge(start) & created.lt(stop)).sum()),
                  "Requests closed": int(closing.sum())}
        for label, field, target in MILESTONES:
            stamps = pd.to_datetime(df[field], errors="coerce", utc=True, format="mixed")
            measured = stamps.ge(start) & stamps.lt(stop) & reported.notna() & stamps.ge(reported)
            if label == "Closure":
                measured &= df["Status"].eq("closed")
            hours = (stamps[measured] - reported[measured]).dt.total_seconds().div(3600)
            values[f"{label} on time"] = float(hours.le(target).mean() * 100) if len(hours) else None
        durations = (closed[closing] - reported[closing]).dt.total_seconds().div(3600)
        valid = durations[durations.ge(0)]
        values["Average closure TAT"] = float(valid.mean()) if len(valid) else None
        periods.append(values)
    rows = []
    for metric, current in periods[0].items():
        previous = periods[1][metric]
        is_rate = metric.endswith("on time")
        def display(value):
            if value is None:
                return "Not recorded"
            if is_rate:
                return f"{value:.1f}%"
            return format_duration(value) if metric == "Average closure TAT" else str(value)
        change = "—"
        if current is not None and previous is not None:
            delta = current - previous
            change = f"{delta:+.1f} pp" if is_rate else f"{delta:+.1f} h" if metric == "Average closure TAT" else f"{delta:+d}"
        rows.append({"Metric": metric, "Last 7 days": display(current), "Previous 7 days": display(previous), "Change": change})
    return pd.DataFrame(rows)
