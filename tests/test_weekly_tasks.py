import datetime as dt

from reporting.database import create_weekly_task_store
from reporting.weekly_sync import sync_weekly_tasks
from reporting.weekly_tracker import (
    KPI_ROUTING, active_week, build_all_weekly_tasks, build_weekly_tasks, next_thursday,
    parse_week_label, week_columns, week_due_date,
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


def test_build_all_weekly_tasks_imports_every_filled_week():
    tasks = build_all_weekly_tasks(GRID, now=dt.date(2026, 10, 21))
    # WEEK 41 has three filled rows; WEEK 42 has only Requests ("Next week BD").
    weeks = {t["week_start"] for t in tasks}
    assert weeks == {"2026-10-05", "2026-10-12"}
    assert len(tasks) == 4
    wk42 = [t for t in tasks if t["week_start"] == "2026-10-12"]
    assert [t["kpi_area"] for t in wk42] == ["Requests"]
    assert wk42[0]["task"] == "Next week BD"
    # Each week carries its own due date (the second Thursday after it ends).
    assert wk42[0]["due_at"] == week_due_date(dt.date(2026, 10, 18)).isoformat()


def test_backfill_sync_then_weekly_is_idempotent(tmp_path):
    store = create_weekly_task_store(f"sqlite:///{tmp_path / 'weekly.db'}")
    backfill = sync_weekly_tasks(store, grid=GRID, now=dt.date(2026, 10, 21), all_weeks=True)
    assert backfill["tasks"] == 4 and backfill["created"] == 4 and backfill["weeks"] == 2
    # A later normal weekly sync refreshes the active week without duplicating it.
    weekly = sync_weekly_tasks(store, grid=GRID, now=dt.date(2026, 10, 21))
    assert weekly["created"] == 0 and weekly["updated"] == 3
    assert len(store.list()) == 4


def test_completion_stats_and_breakdowns():
    from reporting.weekly_tracker import completion_by_department, completion_by_week, completion_stats
    tasks = [
        {"department": "IT", "week_start": "2026-10-05", "week_label": "WEEK 41", "status": "Complete"},
        {"department": "IT", "week_start": "2026-10-05", "week_label": "WEEK 41", "status": "Off Track"},
        {"department": "BD", "week_start": "2026-10-05", "week_label": "WEEK 41", "status": "Complete"},
        {"department": "BD", "week_start": "2026-10-12", "week_label": "WEEK 42", "status": "Yet to Start"},
    ]
    stats = completion_stats(tasks)
    assert stats["total"] == 4 and stats["complete"] == 2 and stats["off_track"] == 1
    assert stats["rate"] == 50.0
    by_dep = {row["department"]: row for row in completion_by_department(tasks)}
    assert by_dep["IT"]["rate"] == 50.0 and by_dep["BD"]["complete"] == 1
    trend = completion_by_week(tasks)
    assert [row["week_start"] for row in trend] == ["2026-10-05", "2026-10-12"]  # oldest first
    assert round(trend[0]["rate"], 1) == 66.7 and trend[1]["rate"] == 0.0  # 2 of 3, then 0 of 1
    # An empty set is a safe zero, not a divide-by-zero.
    assert completion_stats([])["rate"] == 0.0


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
