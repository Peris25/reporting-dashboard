from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO
import uuid

import pandas as pd

from .schema import TICKET_HEADERS
from .workflow import normalize_status


def _first_index(headers, name):
    try:
        return headers.index(name)
    except ValueError:
        return None


def _value(row, headers, name):
    index = _first_index(headers, name)
    return row[index].strip() if index is not None and index < len(row) else ""


def _jira_datetime(value):
    if not value:
        return ""
    parsed = pd.to_datetime(value, format="%d/%b/%y %I:%M %p", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.isoformat(timespec="seconds")


def normalize_jira_csv(content):
    """Convert a Jira CSV export, including duplicate headers, into ticket records."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    reader = csv.reader(StringIO(content))
    try:
        headers = next(reader)
    except StopIteration:
        return pd.DataFrame(columns=TICKET_HEADERS)

    records = []
    for row in reader:
        external_key = _value(row, headers, "Issue key")
        created = _jira_datetime(_value(row, headers, "Created"))
        resolved = _jira_datetime(_value(row, headers, "Resolved"))
        updated = _jira_datetime(_value(row, headers, "Updated"))
        status = normalize_status(_value(row, headers, "Status"))
        ticket_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"jira:{external_key}")) if external_key else str(uuid.uuid4())
        records.append(
            {
                "Ticket ID": ticket_id,
                "Summary": _value(row, headers, "Summary"),
                "Status": status,
                "Priority": _value(row, headers, "Priority").title(),
                "Created": created,
                "Diagnosed At": "",
                "Resolved At": resolved,
                "Updated At": updated or created,
                "External Key": external_key,
                "Description": _value(row, headers, "Description"),
                "Severity": "",
                "Category": _value(row, headers, "Issue Type"),
                "Subcategory": "",
                "Assignee": _value(row, headers, "Assignee"),
                "Reporter": _value(row, headers, "Reporter"),
                "Team": _value(row, headers, "Custom field (Team)"),
                "Channel": "Jira",
                "Customer Email": "",
                "Customer WhatsApp": "",
                "Escalation Owner": "",
                "First Response At": "",
                "Closed At": resolved if status == "closed" else "",
                "Reopened Count": 0,
                "Resolution Category": _value(row, headers, "Resolution"),
            }
        )
    return pd.DataFrame(records, columns=TICKET_HEADERS)


def import_summary(df):
    return {
        "rows": int(len(df)),
        "with_external_key": int(df["External Key"].astype(bool).sum()) if len(df) else 0,
        "with_assignee": int(df["Assignee"].astype(bool).sum()) if len(df) else 0,
        "invalid_created": int(pd.to_datetime(df["Created"], errors="coerce").isna().sum()) if len(df) else 0,
    }
