from pathlib import Path
from datetime import datetime

import streamlit as st
from streamlit.testing.v1 import AppTest

from reporting.database import database_handles
from reporting.schema import TICKET_HEADERS


def test_save_request_update_preserves_id_and_records_activity(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'requests.db').as_posix()}")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", "")
    # Chart/table rendering is unrelated; verify stored activity directly below.
    monkeypatch.setattr(st, "dataframe", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "altair_chart", lambda chart, **kwargs: chart.to_dict())
    st.cache_resource.clear()
    tickets, activities = database_handles()
    ticket = dict.fromkeys(TICKET_HEADERS, "")
    ticket.update({
        "Ticket ID": "request-1",
        "Summary": "App will not open",
        "Status": "to do",
        "Priority": "Medium",
        "Created": "2026-09-04T10:00:00+00:00",
        "Callback Required": "No",
    })
    tickets.append_row([ticket[header] for header in TICKET_HEADERS])
    try:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        app.run(timeout=30)
        assert not app.exception
        assert any(field.label == "Reg No" for field in app.text_input)
        assert not any(field.label == "Solver ID" for field in app.text_input)
        next(field for field in app.text_area if field.label == "Resolution summary").set_value("Told to reinstall app")
        next(field for field in app.text_area if field.label == "Update note").set_value("Provided instructions")
        next(button for button in app.button if button.label == "Save request update").click()
        app.run(timeout=30)
        assert not app.exception
        saved = tickets.get_all_records()
        assert len(saved) == 1
        assert saved[0]["Ticket ID"] == "request-1"
        assert saved[0]["Resolution Summary"] == "Told to reinstall app"
        assert saved[0]["Updated At"]
        activity = activities.get_all_records()
        assert len(activity) == 1
        assert activity[0]["Ticket ID"] == "request-1"
        assert activity[0]["Field"] == "Resolution Summary"
        assert activity[0]["Note"] == "Provided instructions"

        # A direct closure must explain the resolution and leave data untouched on failure.
        next(field for field in app.selectbox if field.label == "Status").set_value("closed")
        next(field for field in app.text_area if field.label == "Resolution summary").set_value("   ")
        next(button for button in app.button if button.label == "Save request update").click()
        app.run(timeout=30)
        assert not app.exception
        assert any("Add a resolution summary" in error.value for error in app.error)
        assert tickets.get_all_records()[0]["Status"] == "to do"
        assert len(activities.get_all_records()) == 1

        next(field for field in app.text_area if field.label == "Resolution summary").set_value("Told to reinstall app")
        next(button for button in app.button if button.label == "Save request update").click()
        app.run(timeout=30)
        assert not app.exception
        closed = tickets.get_all_records()[0]
        assert closed["Status"] == "closed"
        assert closed["Closed At"] == closed["Resolved At"]
        assert closed["Diagnosed At"] == ""
        assert closed["First Response At"] == ""
        assert closed["Closed At"]
        status_events = [row for row in activities.get_all_records() if row["Action"] == "status_changed"]
        assert len(status_events) == 1
        assert status_events[0]["Old Value"] == "to do"
        assert status_events[0]["New Value"] == "closed"
        assert any("To do → Closed" in element.value for element in app.text)

        # Backfill actual milestones in Nairobi time, without changing closure time.
        next(field for field in app.datetime_input if field.label == "First response sent at").set_value(datetime(2026, 9, 4, 12, 0))
        next(button for button in app.button if button.label == "Save request update").click()
        app.run(timeout=30)
        assert any("between when the request was reported and now" in error.value for error in app.error)
        assert tickets.get_all_records()[0]["First Response At"] == ""
        next(field for field in app.datetime_input if field.label == "First response sent at").set_value(datetime(2026, 9, 4, 13, 20))
        next(field for field in app.datetime_input if field.label == "Problem diagnosed at").set_value(datetime(2026, 9, 4, 14, 0))
        next(button for button in app.button if button.label == "Save request update").click()
        app.run(timeout=30)
        assert not app.exception
        milestones = tickets.get_all_records()[0]
        assert milestones["First Response At"] == "2026-09-04T13:20:00+03:00"
        assert milestones["Diagnosed At"] == "2026-09-04T14:00:00+03:00"
        assert milestones["Closed At"] == closed["Closed At"]

        # Reopening resumes the original logged-to-closed clock.
        next(field for field in app.selectbox if field.label == "Status").set_value("in progress")
        next(button for button in app.button if button.label == "Save request update").click()
        app.run(timeout=30)
        assert not app.exception
        reopened = tickets.get_all_records()[0]
        assert reopened["Closed At"] == ""
        assert reopened["Created"] == ticket["Created"]
        assert reopened["First Response At"] == milestones["First Response At"]
    finally:
        st.cache_resource.clear()
