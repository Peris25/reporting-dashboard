import pandas as pd

from reporting.analytics import department_breakdown, filter_requests
from reporting.departments import (
    DEPARTMENTS, has_subteams, normalize_department, normalize_subteam, subteams_for,
)
from reporting.sla import enrich_tickets


def sample():
    now = pd.Timestamp("2026-09-16T12:00:00Z")
    rows = [
        {"Ticket ID": "1", "Status": "closed", "Assigned Department": "IT", "Assigned Sub-team": "",
         "Reporting Department": "IT", "Created": "2026-09-14T09:00:00Z", "Reported At": "2026-09-14T09:00:00Z",
         "First Response At": "2026-09-14T09:10:00Z", "Diagnosed At": "2026-09-14T10:00:00Z",
         "Closed At": "2026-09-15T09:00:00Z", "Assignee": "Ann", "Priority": "High", "Summary": "printer"},
        {"Ticket ID": "2", "Status": "to do", "Assigned Department": "Operations", "Assigned Sub-team": "Scheduling",
         "Reporting Department": "BD", "Created": "2026-09-16T08:00:00Z", "Reported At": "2026-09-16T08:00:00Z",
         "First Response At": "", "Diagnosed At": "", "Closed At": "", "Assignee": "", "Priority": "Medium", "Summary": "slot"},
        {"Ticket ID": "3", "Status": "in progress", "Assigned Department": "Operations", "Assigned Sub-team": "Approval",
         "Reporting Department": "Operations", "Created": "2026-09-16T07:00:00Z", "Reported At": "2026-09-16T07:00:00Z",
         "First Response At": "", "Diagnosed At": "", "Closed At": "", "Assignee": "Bob", "Priority": "Low", "Summary": "sign off"},
    ]
    return enrich_tickets(pd.DataFrame(rows), now=now)


def test_config_helpers():
    assert normalize_department("operations") == "Operations"
    assert normalize_department("Legal") == ""
    assert subteams_for("Operations") == ["Scheduling", "Approval", "Solver (Submissions)"]
    assert not has_subteams("HR")
    assert normalize_subteam("Operations", "approval") == "Approval"
    assert normalize_subteam("HR", "approval") == ""


def test_department_filter():
    ops = filter_requests(sample(), department="Operations")
    assert set(ops["Ticket ID"]) == {"2", "3"}


def test_subteam_filter():
    scheduling = filter_requests(sample(), department="Operations", subteam="Scheduling")
    assert set(scheduling["Ticket ID"]) == {"2"}


def test_all_departments_option_is_a_no_op():
    assert len(filter_requests(sample())) == 3


def test_breakdown_groups_and_subteams():
    table = department_breakdown(sample(), DEPARTMENTS)
    scopes = list(table["Scope"])
    assert "IT" in scopes
    assert "Operations" in scopes
    assert any("Scheduling" in scope for scope in scopes)
    assert any("Approval" in scope for scope in scopes)

    ops = table.loc[table["Scope"] == "Operations"].iloc[0]
    assert ops["Open"] == 2
    assert ops["Closed"] == 0
    # Ticket 2 is open and unassigned, so Operations needs attention on it.
    assert ops["Needs attention"] >= 1

    it_row = table.loc[table["Scope"] == "IT"].iloc[0]
    assert it_row["Closed"] == 1


def test_breakdown_empty_frame():
    empty = department_breakdown(sample().iloc[0:0], DEPARTMENTS)
    assert list(empty.columns)[:3] == ["Scope", "Total", "Open"]
    assert empty.empty
