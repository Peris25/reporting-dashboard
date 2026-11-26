from pathlib import Path
from datetime import datetime
import pandas as pd

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from reporting.database import database_handles


@pytest.mark.parametrize("job_id,reg_no", [("", ""), ("JOB-123", "kda 123a")])
def test_external_client_intake_accepts_optional_job_details(tmp_path, monkeypatch, job_id, reg_no):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'clients.db').as_posix()}")
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", "")
    tables = []
    monkeypatch.setattr(st, "dataframe", lambda data, **kwargs: tables.append(data.copy()))
    monkeypatch.setattr(st, "altair_chart", lambda *args, **kwargs: None)
    st.cache_resource.clear()
    try:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
        assert not app.exception
        assert "New request" not in [tab.label for tab in app.tabs]
        app.button(key="ticket_card_tickets").click().run()
        next(button for button in app.button if button.label == "Add new").click().run()
        next(field for field in app.selectbox if field.label == "Who needs support?").set_value("External Clients").run()
        assert not any(field.label == "Solver ID" for field in app.text_input)
        next(field for field in app.selectbox if field.label == "Channel").set_value("Email")
        for label, value in {
            "Issue summary": "Need help with an inspection", "Job Request ID": job_id, "Reg No": reg_no,
        }.items():
            next(field for field in app.text_input if field.label == label).set_value(value)
        next(field for field in app.datetime_input if field.label == "Reported at").set_value(datetime(2026, 9, 9, 21, 0))
        next(field for field in app.datetime_input if field.label == "Resolved at (optional)").set_value(datetime(2026, 9, 9, 21, 5))
        next(button for button in app.button if button.label == "Save").click().run()
        assert any("Enter a resolution summary" in error.value for error in app.error)
        next(field for field in app.text_area if field.label == "Resolution summary").set_value("Reopened the inspection for the client.")
        next(button for button in app.button if button.label == "Save").click().run()
        assert not app.exception
        tickets, activities = database_handles()
        saved, = tickets.get_all_records()
        assert saved["Requester Type"] == "External Clients"
        assert saved["Job Request ID"] == job_id
        assert saved["Reg No"] == reg_no.upper()
        assert saved["Status"] == "closed"
        assert saved["Resolution Summary"] == "Reopened the inspection for the client."
        assert saved["Reported At"] == "2026-09-09T21:00:00+03:00"
        assert saved["Closed At"] == saved["Resolved At"] == "2026-09-09T21:05:00+03:00"
        assert pd.Timestamp(saved["Created"]) > pd.Timestamp(saved["Reported At"])
        assert activities.get_all_records() == []
        register = next(table for table in tables if "Reg No / Request ID" in table.columns)
        assert register.iloc[0]["Ticket"] == "T-001"
        assert register.iloc[0]["Reg No / Request ID"] == " / ".join(filter(None, (reg_no.upper(), job_id)))
        assert "Requester" not in register.columns
    finally:
        st.cache_resource.clear()
