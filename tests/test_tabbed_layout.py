from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from reporting.analytics import ALL_REQUESTERS_OPTION, filter_requests
from reporting.database import DatabaseWorksheet, database_handles
from reporting.schema import TICKET_HEADERS


def _frame():
    rows = [
        {"Requester Type": "Solver", "Reported_dt": "2026-11-18T08:00:00Z"},
        {"Requester Type": "Solvit Office Team", "Reported_dt": "2026-11-01T08:00:00Z"},
        {"Requester Type": "External Clients", "Reported_dt": "2026-09-01T08:00:00Z"},
    ]
    frame = pd.DataFrame(rows)
    frame["Status"] = "to do"
    frame["Priority"] = "Medium"
    frame["Created Month"] = "2026-11"
    frame["Assigned Department"] = "IT"
    frame["Assigned Sub-team"] = ""
    frame["Assignee"] = ""
    frame["Created_dt"] = pd.to_datetime(frame["Reported_dt"], utc=True)
    return frame


def test_requester_type_filters_to_one_workspace():
    frame = _frame()
    solver = filter_requests(frame, requester_type="Solver")
    assert list(solver["Requester Type"]) == ["Solver"]
    # The default keeps every requester type.
    assert len(filter_requests(frame, requester_type=ALL_REQUESTERS_OPTION)) == 3


def test_reporting_period_keeps_only_requests_in_window():
    frame = _frame()
    windowed = filter_requests(frame, period_start=date(2026, 11, 10), period_end=date(2026, 11, 30))
    assert list(windowed["Requester Type"]) == ["Solver"]
    # An open-ended lower bound still trims everything before the start date.
    since_october = filter_requests(frame, period_start=date(2026, 10, 1))
    assert set(since_october["Requester Type"]) == {"Solver", "Solvit Office Team"}


def test_app_renders_five_tabs_and_new_sidebar(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'tabs.db').as_posix()}")
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", "")
    monkeypatch.setattr(st, "dataframe", lambda data, **kwargs: None)
    monkeypatch.setattr(st, "altair_chart", lambda chart, **kwargs: None)
    st.cache_resource.clear()
    tickets, _ = database_handles()
    ticket = dict.fromkeys(TICKET_HEADERS, "")
    ticket.update({"Ticket ID": "tab-1", "Created": "2026-11-18T10:00:00Z", "Reported At": "2026-11-18T09:30:00Z",
                   "Summary": "App issue", "Status": "to do", "Priority": "Medium",
                   "Requester Type": "Solver", "Assigned Department": "IT", "Callback Required": "No"})
    tickets.append_row([ticket[field] for field in TICKET_HEADERS])
    reads = []
    original_read = DatabaseWorksheet.get_all_records

    def count_read(worksheet):
        reads.append(worksheet.headers)
        return original_read(worksheet)

    monkeypatch.setattr(DatabaseWorksheet, "get_all_records", count_read)
    try:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
        assert not app.exception
        radio_labels = [radio.label for radio in app.radio]
        assert "Ticket workspace" in radio_labels
        select_labels = [box.label for box in app.selectbox]
        assert "Reporting period" in select_labels
        assert "Request status" in select_labels
        assert reads == [TICKET_HEADERS]
        assert not any("Analytics refresh every 10 minutes" in caption.value for caption in app.caption)
        assert not any(heading.value == "Weekly tasks" for heading in app.subheader)
        assert any("Tickets in period" in str(markdown.value) for markdown in app.markdown)
        reads.clear()
        app.session_state["dashboard_tab"] = "Reports"
        app.run(timeout=30)
        assert not app.exception
        assert reads == [TICKET_HEADERS]
        assert any("Analytics refresh every 10 minutes" in caption.value for caption in app.caption)
    finally:
        st.cache_resource.clear()
