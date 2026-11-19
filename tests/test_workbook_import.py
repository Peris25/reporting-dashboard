from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from uuid import NAMESPACE_URL, uuid5

from reporting.database import Activity, Ticket, create_session_factory
from reporting.workbook_import import NAIROBI, import_it_tickets, read_it_workbook


def workbook(*rows):
    book = Workbook()
    sheet = book.active
    sheet.title = "IT Requests"
    sheet.append([
        "External Key", "Summary", "Assignee", "Status", "Reported At", "Resolved At",
        "Closed At", "Resolution Summary", "Job Request ID", "Evidence Notes",
    ])
    for row in rows:
        sheet.append(row)
    data = BytesIO()
    book.save(data)
    return data.getvalue()


def request(key="sample-01", resolved=datetime(2026, 1, 4, 11, 15), evidence=None):
    return [
        key, "Example valuation photo check", "Sample Agent", "Closed",
        datetime(2026, 1, 4, 10), resolved, datetime(2026, 1, 4, 11, 20),
        "Confirmed that the images were available.", "1001", evidence,
    ]


def test_workbook_creates_real_closed_it_tickets_once_with_activity():
    factory = create_session_factory("sqlite://")
    tickets = read_it_workbook(workbook(
        request(),
        request("sample-02", resolved=None, evidence="Closure recorded; resolution time unknown."),
    ), now=datetime(2026, 2, 1, tzinfo=NAIROBI))
    assert import_it_tickets(factory, tickets, actor="test-admin") == 2
    assert import_it_tickets(factory, tickets, actor="test-admin") == 0

    with factory() as session:
        saved = session.scalars(select(Ticket).order_by(Ticket.external_key)).all()
        activities = session.scalars(select(Activity)).all()
        first, second = saved
        assert first.assigned_department == first.reporting_department == "IT"
        assert first.status == "closed"
        assert first.assignee == "Sample Agent"
        assert first.job_request_id == "1001"
        assert first.reported_at == "2026-01-04T10:00:00+03:00"
        assert first.resolved_at == "2026-01-04T11:15:00+03:00"
        assert first.closed_at == "2026-01-04T11:20:00+03:00"
        assert first.resolution_summary == "Confirmed that the images were available."
        assert second.resolved_at is None
        assert "resolution time unknown" in second.description
        assert len(activities) == 2
        assert {entry.ticket_id for entry in activities} == {first.ticket_id, second.ticket_id}
        assert all(entry.actor == "test-admin" and entry.new_value == "closed" for entry in activities)


@pytest.mark.parametrize(
    ("rows", "error"),
    [
        ([request(), request()], "Row 3: External Key repeats"),
        ([request(resolved=None)], "Row 2: Add Evidence Notes"),
        ([request(resolved=datetime(2026, 1, 4, 11, 30))], "Row 2: Report, resolution and closure"),
        ([request(key="=1+1")], "Row 2: Paste values"),
    ],
)
def test_workbook_rejects_invalid_batches(rows, error):
    with pytest.raises(ValueError, match=error):
        read_it_workbook(workbook(*rows), now=datetime(2026, 2, 1, tzinfo=NAIROBI))


def test_import_rolls_back_tickets_if_activity_cannot_be_saved():
    factory = create_session_factory("sqlite://")
    tickets = read_it_workbook(workbook(request()), now=datetime(2026, 2, 1, tzinfo=NAIROBI))
    ticket_id = tickets[0]["ticket_id"]
    with factory.begin() as session:
        session.add(Activity(
            activity_id=str(uuid5(NAMESPACE_URL, f"it-workbook-activity:{ticket_id}")),
            ticket_id="unrelated", action="test", timestamp="2026-02-01T00:00:00+03:00",
        ))
    with pytest.raises(IntegrityError):
        import_it_tickets(factory, tickets, actor="test-admin")
    with factory() as session:
        assert session.get(Ticket, ticket_id) is None
