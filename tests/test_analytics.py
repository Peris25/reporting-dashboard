import pandas as pd

from reporting.analytics import filter_requests, milestone_deadlines, weekly_report
from reporting.schema import TICKET_HEADERS
from reporting.sla import enrich_tickets


def test_deadlines_cross_boundary_and_keep_completed_milestones_stopped():
    ticket = {"Created": "2026-09-09T10:00:00Z", "Status": "to do"}
    before = milestone_deadlines(ticket, "2026-09-09T10:20:00Z")
    assert before[0]["text"] == "Response due in 10 min"
    assert before[0]["tone"] == "info"
    due = milestone_deadlines(ticket, "2026-09-09T10:30:00Z")
    assert due[0]["text"] == "Response due now"
    late = milestone_deadlines(ticket, "2026-09-09T10:31:00Z")
    assert late[0]["tone"] == "error"
    assert late[0]["text"] == "Response overdue by 1 min"
    ticket["First Response At"] = "2026-09-09T10:25:00Z"
    completed = milestone_deadlines(ticket, "2026-09-11T12:00:00Z")
    assert completed[0]["tone"] == "success"
    assert "25 min" in completed[0]["text"]
    ticket["Status"] = "closed"
    assert milestone_deadlines(ticket)[1]["text"] == "Diagnosis: time not recorded"


def test_weekly_report_uses_milestone_dates_and_nonoverlapping_windows():
    base = dict.fromkeys(TICKET_HEADERS, "")
    df = pd.DataFrame([
        {**base, "Created": "2026-09-08T10:00Z", "First Response At": "2026-09-08T10:20Z", "Status": "to do"},
        {**base, "Created": "2026-09-01T10:00Z", "First Response At": "2026-09-01T11:00Z", "Status": "to do"},
        # Logged earlier, closed in the current period: count by closure date.
        {**base, "Created": "2026-08-20T00:00Z", "Closed At": "2026-09-08T00:00Z", "Status": "closed"},
        # Exactly at the boundary belongs only to the current period.
        {**base, "Created": "2026-09-02T00:00Z", "Status": "to do"},
    ])
    report = weekly_report(df, "2026-09-09T00:00Z").set_index("Metric")
    assert report.loc["Requests logged", "Last 7 days"] == "2"
    assert report.loc["Requests logged", "Previous 7 days"] == "1"
    assert report.loc["Requests closed", "Last 7 days"] == "1"
    assert report.loc["Response on time", "Last 7 days"] == "100.0%"
    assert report.loc["Response on time", "Previous 7 days"] == "0.0%"
    assert report.loc["Response on time", "Change"] == "+100.0 pp"
    assert report.loc["Diagnosis on time", "Last 7 days"] == "Not recorded"
    assert report.loc["Average closure TAT", "Last 7 days"] == "456.0 h"


def test_owner_filter_combines_with_search_and_does_not_mutate_source():
    base = dict.fromkeys(TICKET_HEADERS, "")
    df = enrich_tickets(pd.DataFrame([
        {**base, "Ticket ID": "1", "Created": "2026-09-09", "Status": "to do", "Assignee": " Peris ", "Summary": "App"},
        {**base, "Ticket ID": "2", "Created": "2026-09-09", "Status": "to do", "Assignee": "", "Summary": "App"},
    ]))
    assert filter_requests(df, owner="Peris", search="app")["Ticket ID"].tolist() == ["1"]
    assert filter_requests(df, owner="Unassigned")["Ticket ID"].tolist() == ["2"]
    assert df.loc[0, "Assignee"] == " Peris "


def test_empty_weekly_report_does_not_claim_compliance():
    report = weekly_report(pd.DataFrame(columns=TICKET_HEADERS)).set_index("Metric")
    assert report.loc["Requests logged", "Last 7 days"] == "0"
    assert report.loc["Response on time", "Last 7 days"] == "Not recorded"
