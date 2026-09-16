from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from reporting.database import database_handles
from reporting.schema import TICKET_HEADERS


def test_quick_milestones_save_owner_and_activity_without_overwriting_response(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'quick.db').as_posix()}")
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", "")
    tables = []
    monkeypatch.setattr(st, "dataframe", lambda data, **kwargs: tables.append(data.copy()))
    monkeypatch.setattr(st, "altair_chart", lambda chart, **kwargs: chart.to_dict())
    st.cache_resource.clear()
    tickets, activities = database_handles()
    ticket = dict.fromkeys(TICKET_HEADERS, "")
    ticket.update({"Ticket ID": "quick-1", "Created": "2026-09-04T10:00:00Z", "Summary": "App issue", "Status": "to do", "Priority": "Medium", "Callback Required": "No"})
    tickets.append_row([ticket[field] for field in TICKET_HEADERS])
    try:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
        assert not app.exception
        assert any("Analytics refresh every 10 minutes" in caption.value for caption in app.caption)
        assert any("Unassigned" in message.value for message in app.info)
        owners = [field for field in app.text_input if field.label == "Assigned support agent"]
        owners[-1].set_value("Peris")
        next(button for button in app.button if button.label == "Mark responded").click()
        app.run(timeout=30)
        assert not app.exception
        responded = tickets.get_all_records()[0]
        assert responded["First Response At"]
        assert responded["Assignee"] == "Peris"
        assert responded["Status"] == "to do"
        assert next(button for button in app.button if button.label == "Mark responded").disabled
        next(button for button in app.button if button.label == "Mark diagnosed").click()
        app.run(timeout=30)
        assert not app.exception
        diagnosed = tickets.get_all_records()[0]
        assert diagnosed["Status"] == "diagnosed"
        assert diagnosed["Diagnosed At"]
        assert diagnosed["First Response At"] == responded["First Response At"]
        assert next(button for button in app.button if button.label == "Mark diagnosed").disabled
        events = activities.get_all_records()
        assert len([event for event in events if event["Field"] == "First Response At"]) == 1
        assert any(event["Action"] == "status_changed" and event["New Value"] == "diagnosed" for event in events)
        assert any("Last 7 days" in table.columns for table in tables)
    finally:
        st.cache_resource.clear()
