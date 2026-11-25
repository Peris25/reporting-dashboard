"""Sync the Weekly Manager Tracker into weekly-task records.

Shared by the dashboard's "Sync weekly tasks" button and the scheduled CLI, so
both behave identically. Reads the live sheet via Microsoft Graph (or takes a
pre-read grid, which keeps this testable), builds the active week's tasks, and
upserts them into the store (new tasks created, existing ones refreshed with the
latest text while their dashboard status is preserved).
"""

from __future__ import annotations

from reporting.graph_excel import read_worksheet_values
from reporting.weekly_tracker import build_all_weekly_tasks, build_weekly_tasks

DEFAULT_WORKSHEET = "Weekly Manager Tracker"


def sync_weekly_tasks(store, *, grid=None, graph_config=None, share_url=None,
                      worksheet=DEFAULT_WORKSHEET, now=None, all_weeks=False):
    """Return a summary dict: tasks, created, updated, week, due, weeks.

    With all_weeks=True, every filled week in the tracker is imported (a one-time
    backfill); otherwise only the active week's tasks are synced.
    """
    if grid is None:
        if not (graph_config and graph_config.is_configured() and share_url):
            raise ValueError("Provide a grid, or a configured Graph app plus the sheet's share URL.")
        grid = read_worksheet_values(graph_config, share_url=share_url, worksheet=worksheet)
    tasks = build_all_weekly_tasks(grid, now=now) if all_weeks else build_weekly_tasks(grid, now=now)
    created = updated = 0
    for task in tasks:
        if store.upsert_from_sheet(task) == "created":
            created += 1
        else:
            updated += 1
    week_count = len({task["week_start"] for task in tasks})
    return {
        "tasks": len(tasks),
        "created": created,
        "updated": updated,
        "weeks": week_count,
        "all_weeks": all_weeks,
        "week": (f"{week_count} week(s)" if all_weeks else tasks[0]["week_label"]) if tasks else None,
        "due": None if all_weeks else (tasks[0]["due_at"] if tasks else None),
    }
