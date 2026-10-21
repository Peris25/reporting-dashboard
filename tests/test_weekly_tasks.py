import datetime as dt

from reporting.database import create_weekly_task_store
from reporting.weekly_sync import sync_weekly_tasks
from reporting.weekly_tracker import (
    KPI_ROUTING, active_week, build_weekly_tasks, next_thursday, parse_week_label, week_columns,
)

GRID = [
    ["WEEKLY MANAGER TRACKER 2026"],
    ["SECTION 2: WEEKLY ACTION TRACKER"],
    ["KPI Area", "Initiative", "WEEK 41 (05-11 Oct)", "", "", "WEEK 42 (12-18 Oct)", "", ""],
    ["Requests", "plan", "Onboard a partner", "On Track", "going well", "Next week BD", "", ""],
    ["Approved Rate", "plan", "Clear approvals backlog", "Complete", "done", "", "", ""],
    ["Administration", "plan", "AAR tender", "", "", "", "", ""],
    ["TAT", "plan", "should be ignored", "", "", "", "", ""],
    ["WEEKLY SUMMARY"],
]


def test_next_thursday():
    # 2026-10-21 is a Wednesday; the next Thursday is the 22nd.
    assert next_thursday(dt.date(2026, 10, 21)) == dt.date(2026, 10, 22)
    assert next_thursday(dt.date(2026, 10, 22)) == dt.date(2026, 10, 22)  # same day


def test_parse_week_label_same_and_cross_month():
    assert parse_week_label("WEEK 41 (05-11 Oct)", 2026) == (dt.date(2026, 10, 5), dt.date(2026, 10, 11))
    assert parse_week_label("WEEK 40 (28 Sep-04 Oct)", 2026) == (dt.date(2026, 9, 28), dt.date(2026, 10, 4))


def test_active_week_picks_last_reviewed():
    weeks = week_columns(GRID[2], 2026)
    week, due = active_week(weeks, dt.date(2026, 10, 21))
    assert week[1] == "WEEK 41 (05-11 Oct)"   # reviewed 15th, due the 22nd
    assert due == dt.date(2026, 10, 22)


def test_build_weekly_tasks_routes_and_skips_unmapped():
    tasks = build_weekly_tasks(GRID, now=dt.date(2026, 10, 21))
    by_kpi = {t["kpi_area"]: t for t in tasks}
    assert set(by_kpi) == {"Requests", "Approved Rate", "Administration"}  # TAT skipped
    assert by_kpi["Requests"]["department"] == "BD"
    assert by_kpi["Requests"]["task"] == "Onboard a partner"
    assert by_kpi["Requests"]["comments"] == "going well"
    assert by_kpi["Requests"]["due_at"] == "2026-10-22"
    assert by_kpi["Approved Rate"]["department"] == "Operations"
    assert by_kpi["Approved Rate"]["subteam"] == "Approval"
    assert by_kpi["Approved Rate"]["status"] == "Complete"
    assert by_kpi["Administration"]["department"] == "HR and Admin"
    assert by_kpi["Administration"]["subteam"] == "Admin"
    assert by_kpi["Administration"]["status"] == "Yet to Start"  # blank defaults


def test_routing_covers_only_mapped_kpis():
    assert "TAT" not in KPI_ROUTING and "Assessment Experience" not in KPI_ROUTING
    assert KPI_ROUTING["Comms Response"] == ("HR and Admin", "HR")


def test_store_upsert_preserves_dashboard_status(tmp_path):
    store = create_weekly_task_store(f"sqlite:///{tmp_path / 'weekly.db'}")
    task = {
        "source_key": "2026-10-05|Requests", "kpi_area": "Requests", "department": "BD",
        "subteam": "", "week_label": "WEEK 41", "week_start": "2026-10-05", "week_end": "2026-10-11",
        "due_at": "2026-10-22", "task": "Onboard a partner", "comments": "", "status": "On Track",
    }
    assert store.upsert_from_sheet(task) == "created"
    created = store.list()[0]
    store.set_status(created["task_id"], "Complete")   # a human updates the dashboard
    # Sheet re-sync with a changed task text and a stale status must not clobber it.
    task2 = dict(task, task="Onboard two partners", status="Off Track")
    assert store.upsert_from_sheet(task2) == "updated"
    refreshed = store.list()[0]
    assert refreshed["task"] == "Onboard two partners"   # text refreshed
    assert refreshed["status"] == "Complete"             # dashboard status preserved


def test_sync_with_grid(tmp_path):
    store = create_weekly_task_store(f"sqlite:///{tmp_path / 'weekly.db'}")
    summary = sync_weekly_tasks(store, grid=GRID, now=dt.date(2026, 10, 21))
    assert summary["tasks"] == 3 and summary["created"] == 3 and summary["updated"] == 0
    assert summary["week"] == "WEEK 41 (05-11 Oct)" and summary["due"] == "2026-10-22"
    # Re-sync is idempotent.
    again = sync_weekly_tasks(store, grid=GRID, now=dt.date(2026, 10, 21))
    assert again["created"] == 0 and again["updated"] == 3
