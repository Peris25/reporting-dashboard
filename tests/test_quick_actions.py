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
        app.button(key="ticket_card_tickets").click().run(timeout=30)
        assert not any(button.label == "Save request update" for button in app.button)
        app.session_state["editing_ticket_id"] = "quick-1"
        app.run(timeout=30)
        assert not app.exception
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
    finally:
        st.cache_resource.clear()


def test_ticket_cards_filter_the_register(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'cards.db').as_posix()}")
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", "")
    tables = []
    monkeypatch.setattr(st, "dataframe", lambda data, **kwargs: tables.append(data.copy()))
    monkeypatch.setattr(st, "altair_chart", lambda *args, **kwargs: None)
    st.cache_resource.clear()
    tickets, _ = database_handles()
    for status in ("to do", "in progress", "closed"):
        row = {"Ticket ID": status, "Support Request Number": f"TEST-{status}", "Summary": status, "Status": status, "Created": "2026-09-04T10:00:00Z"}
        tickets.append_row([row.get(field, "") for field in TICKET_HEADERS])

    try:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
        for card, expected in (
            ("open", {"to do", "in progress"}), ("resolved", {"closed"}),
            ("tickets", {"to do", "in progress", "closed"}),
        ):
            tables.clear()
            app.button(key=f"ticket_card_{card}").click().run()
            assert not app.exception
            assert app.session_state["dashboard_tab"] == "Tickets"
            table = next(frame for frame in tables if "Reg No / Request ID" in frame.columns)
            assert set(table["Issue"]) == expected
        assert len(tickets.get_all_records()) == 3
    finally:
        st.cache_resource.clear()
