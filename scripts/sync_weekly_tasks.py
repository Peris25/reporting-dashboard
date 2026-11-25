"""Sync the Weekly Manager Tracker into the dashboard's weekly tasks.

Reads the live workbook via Microsoft Graph and upserts the active week's tasks.
Intended for a weekly schedule (for example a GitHub Actions cron each Thursday)
and reused by the dashboard's sync button.

Environment variables:
    DATABASE_URL         PostgreSQL connection string (or local SQLite fallback)
    MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET   Graph app (Files.Read.All)
    TRACKER_SHARE_URL    the workbook's SharePoint/OneDrive sharing URL
    TRACKER_WORKSHEET    worksheet/tab name (default "Weekly Manager Tracker")

Usage:
    python scripts/sync_weekly_tasks.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reporting.database import create_weekly_task_store
from reporting.graph_excel import GraphConfig
from reporting.weekly_sync import DEFAULT_WORKSHEET, sync_weekly_tasks


def main():
    share_url = os.getenv("TRACKER_SHARE_URL", "").strip()
    if not share_url:
        print("Set TRACKER_SHARE_URL to the workbook's sharing URL.")
        return 1
    graph_config = GraphConfig.from_settings(lambda key, default="": os.getenv(key, default))
    if not graph_config.is_configured():
        print("Set MS_TENANT_ID, MS_CLIENT_ID, and MS_CLIENT_SECRET for Graph access.")
        return 1
    store = create_weekly_task_store(os.getenv("DATABASE_URL") or None)
    summary = sync_weekly_tasks(
        store, graph_config=graph_config, share_url=share_url,
        worksheet=os.getenv("TRACKER_WORKSHEET", DEFAULT_WORKSHEET),
    )
    if not summary["tasks"]:
        print("No tasks found for the active week yet.")
        return 0
    print(f"Synced {summary['week']} (due {summary['due']}): "
          f"{summary['created']} created, {summary['updated']} updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
