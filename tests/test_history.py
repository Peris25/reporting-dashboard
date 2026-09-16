import pandas as pd

from reporting.history import request_history


def test_history_combines_creation_and_intake_and_excludes_other_requests():
    rows = [
        {"Ticket ID": "one", "Action": "support_request_created", "New Value": "to do", "Note": "App crashes", "Timestamp": "2026-09-07T06:04:01"},
        {"Ticket ID": "one", "Action": "intake_recorded", "Note": "Solver via WhatsApp", "Timestamp": "2026-09-07T06:04:02"},
        {"Ticket ID": "one", "Action": "field_edited", "Field": "Resolution Summary", "New Value": "Reinstall app", "Note": "Reinstall app", "Timestamp": "2026-09-07T06:12:47"},
        {"Ticket ID": "two", "Action": "support_request_created", "Note": "Other request"},
    ]
    history = request_history(pd.DataFrame(rows).fillna(""), "one")
    assert len(history) == 2
    assert history[0]["title"] == "Resolution updated"
    assert history[0]["details"] == ["Reinstall app"]
    assert history[1]["title"] == "Request created"
    assert "Received from: Solver via WhatsApp" in history[1]["details"]
    assert "App crashes" in history[1]["details"]
