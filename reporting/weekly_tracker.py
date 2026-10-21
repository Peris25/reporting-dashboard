"""Read the Weekly Manager Tracker grid into routed weekly-task records.

The tracker's SECTION 2 (Weekly Action Tracker) has one row per KPI Area and, for
each week, a three-column block of Task / Status / Comments. Each Thursday meeting
reviews the week that just ended and sets that week's tasks; those tasks are due
at the following Thursday meeting. So the tasks that matter "now" are the ones
filled for the most recently reviewed week, due at the next meeting.

This module is pure (no Streamlit, no database, no network). It takes a 2D grid
of cell values (from the Graph Excel API or a CSV) and returns normalized task
dicts routed to the right department and sub-team.
"""

from __future__ import annotations

import datetime as dt
import re

from reporting.departments import normalize_department, normalize_subteam

# KPI Area -> (department, sub-team). Only these KPI areas become weekly tasks.
KPI_ROUTING = {
    "Requests": ("BD", ""),
    "Scheduled Rate": ("Operations", "Scheduling"),
    "Inspected Rate": ("Operations", "Solver (Submissions)"),
    "Approved Rate": ("Operations", "Approval"),
    "Solvit Systems": ("IT", ""),
    "HR": ("HR and Admin", "HR"),
    "Comms Response": ("HR and Admin", "HR"),
    "Administration": ("HR and Admin", "Admin"),
}

STATUSES = ["Yet to Start", "On Track", "Off Track", "Complete"]
DONE_STATUS = "Complete"
THURSDAY = 3  # Monday is 0

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_WEEK_LABEL = re.compile(r"WEEK\s*\d+\s*\((.+)\)", re.IGNORECASE)


def _clean(value):
    return str(value or "").replace(" ", " ").strip()


def normalize_status(value):
    text = _clean(value).lower()
    for status in STATUSES:
        if text == status.lower():
            return status
    aliases = {"done": "Complete", "completed": "Complete", "not started": "Yet to Start",
               "yet to start": "Yet to Start", "on track": "On Track", "off track": "Off Track"}
    return aliases.get(text, "")


def parse_week_label(label, base_year):
    """Return (start_date, end_date) for a label like 'WEEK 42 (12-18 Oct)'."""
    match = _WEEK_LABEL.search(_clean(label))
    if not match:
        return None
    span = match.group(1)
    parts = [p.strip() for p in re.split(r"[-–]", span, maxsplit=1)]
    if len(parts) != 2:
        return None

    def parse_part(part):
        tokens = part.split()
        day = int(re.sub(r"\D", "", tokens[0]))
        month = None
        for token in tokens[1:]:
            if token.lower() in _MONTHS:
                month = _MONTHS[token.lower()]
        return day, month

    start_day, start_month = parse_part(parts[0])
    end_day, end_month = parse_part(parts[1])
    if end_month is None:
        end_month = start_month
    if start_month is None:
        start_month = end_month
    if start_month is None:
        return None
    start_year = end_year = base_year
    # A week that ends in January but starts in December belongs to the turn of
    # the year: the December part is the prior year.
    if start_month == 12 and end_month == 1:
        end_year = base_year + 1
    try:
        return dt.date(start_year, start_month, start_day), dt.date(end_year, end_month, end_day)
    except ValueError:
        return None


def find_section2_header(grid):
    """Return the row index of the week-header row within SECTION 2, or None."""
    section_row = None
    for i, row in enumerate(grid):
        if row and _clean(row[0]).upper().startswith("SECTION 2"):
            section_row = i
            break
    if section_row is None:
        return None
    for i in range(section_row + 1, min(section_row + 6, len(grid))):
        if any(_WEEK_LABEL.search(_clean(cell)) for cell in grid[i]):
            return i
    return None


def week_columns(header_row, base_year):
    """List of (col_index, label, start_date, end_date) for each week block."""
    weeks = []
    for col, cell in enumerate(header_row):
        label = _clean(cell)
        if _WEEK_LABEL.search(label):
            dates = parse_week_label(label, base_year)
            if dates:
                weeks.append((col, label, dates[0], dates[1]))
    return weeks


def kpi_rows(grid, header_index):
    """Map each routed KPI Area to its row index (searching below the header)."""
    found = {}
    for i in range(header_index + 1, len(grid)):
        label = _clean(grid[i][0]) if grid[i] else ""
        if not label:
            continue
        if label.upper().startswith("WEEKLY SUMMARY") or label.upper().startswith("SECTION"):
            break
        if label in KPI_ROUTING and label not in found:
            found[label] = i
    return found


def next_thursday(reference):
    """The first Thursday on or after the reference date."""
    return reference + dt.timedelta(days=(THURSDAY - reference.weekday()) % 7)


def active_week(weeks, now):
    """Pick the week whose tasks are due at the next meeting, with that due date.

    The upcoming Thursday meeting reviews tasks set at the previous meeting, which
    belong to the last week that ended before that previous meeting.
    """
    upcoming_meeting = next_thursday(now)
    previous_meeting = upcoming_meeting - dt.timedelta(days=7)
    candidates = [w for w in weeks if w[3] < previous_meeting]
    if not candidates:
        return None, upcoming_meeting
    return max(candidates, key=lambda w: w[3]), upcoming_meeting


def _cell(row, index):
    return _clean(row[index]) if index < len(row) else ""


def build_weekly_tasks(grid, now=None, base_year=None):
    """Return normalized weekly-task dicts for the currently active week."""
    now = now or dt.date.today()
    header_index = find_section2_header(grid)
    if header_index is None:
        return []
    if base_year is None:
        base_year = _infer_year(grid, now)
    weeks = week_columns(grid[header_index], base_year)
    week, due_at = active_week(weeks, now)
    if week is None:
        return []
    col, label, start, end = week
    rows = kpi_rows(grid, header_index)
    tasks = []
    for kpi_area, row_index in rows.items():
        row = grid[row_index]
        task = _cell(row, col)
        if not task:
            continue
        department, subteam = KPI_ROUTING[kpi_area]
        department = normalize_department(department)
        tasks.append({
            "kpi_area": kpi_area,
            "department": department,
            "subteam": normalize_subteam(department, subteam),
            "week_label": label,
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            "due_at": due_at.isoformat(),
            "task": task,
            "comments": _cell(row, col + 2),
            "status": normalize_status(_cell(row, col + 1)) or "Yet to Start",
            "source_key": f"{start.isoformat()}|{kpi_area}",
        })
    return tasks


def _infer_year(grid, now):
    for row in grid[:3]:
        for cell in row:
            match = re.search(r"\b(20\d{2})\b", _clean(cell))
            if match:
                return int(match.group(1))
    return now.year
