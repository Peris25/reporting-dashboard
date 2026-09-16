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
    monkeypatch.setattr(st, "dataframe", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "altair_chart", lambda chart, **kwargs: chart.to_dict())
    st.cache_resource.clear()
    try:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
        assert not app.exception
        app.button_group(key="intake_requester_type").set_value("External Clients").run(timeout=30)
        assert not app.exception
        assert app.datetime_input(key="intake_reported_at").value is None
        labels = [field.label for field in app.text_input]
        assert "Requester name *" not in labels
        assert "Office department" not in labels
        assert "Job Request ID *" not in labels
        for label, value in {
            "Received by *": "Peris",
            "Issue summary *": "Need help with an inspection", "Job Request ID": job_id,
            "Reg No": reg_no, "Phone / WhatsApp number": "254700000000",
        }.items():
            next(field for field in app.text_input if field.label == label).set_value(value)
        app.datetime_input(key="intake_reported_at").set_value(datetime(2026, 9, 9, 21, 0))
        next(button for button in app.button if button.label == "Create support request").click()
        app.run(timeout=30)
        assert not app.exception
        tickets, activities = database_handles()
        saved = tickets.get_all_records()
        assert len(saved) == 1
        assert saved[0]["Requester Type"] == "External Clients"
        assert saved[0]["Requester Name"] == ""
        assert saved[0]["Job Request ID"] == job_id
        assert saved[0]["Reg No"] == reg_no.upper()
        assert saved[0]["Office Department"] == ""
        assert saved[0]["Status"] == "to do"
        assert saved[0]["Created"]
        assert saved[0]["Reported At"] == "2026-09-09T21:00:00+03:00"
        assert pd.Timestamp(saved[0]["Created"]) > pd.Timestamp(saved[0]["Reported At"])
        assert any(row["Note"] == "External Clients via Call" for row in activities.get_all_records())
        # A real response before dashboard entry is valid when after reporting.
        next(field for field in app.datetime_input if field.label == "First response sent at").set_value(datetime(2026, 9, 9, 21, 20))
        next(button for button in app.button if button.label == "Save request update").click()
        app.run(timeout=30)
        assert not app.exception
        assert tickets.get_all_records()[0]["First Response At"] == "2026-09-09T21:20:00+03:00"
    finally:
        st.cache_resource.clear()
