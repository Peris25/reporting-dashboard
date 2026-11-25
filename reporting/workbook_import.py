"""Validate and import a workbook of historical IT support requests."""

from datetime import datetime
from io import BytesIO
from uuid import NAMESPACE_URL, uuid5
from xml.etree.ElementTree import ParseError
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import Activity, Ticket


NAIROBI = ZoneInfo("Africa/Nairobi")
REQUIRED = (
    "External Key", "Summary", "Assignee", "Status", "Reported At",
    "Resolved At", "Closed At", "Resolution Summary",
)
OPTIONAL = {
    "Job Request ID": ("job_request_id", 120),
    "Reg No": ("reg_no", 120),
    "Requester Name": ("requester_name", 200),
    "Customer WhatsApp": ("customer_whatsapp", 30),
    "Requester Type": ("requester_type", 40),
    "Channel": ("channel", 50),
    "Received By": ("received_by", 200),
}


def _text(value, column, limit):
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{column} must be text.")
    result = str(value).strip()
    if len(result) > limit or "\x00" in result:
        raise ValueError(f"{column} contains invalid or overly long text.")
    return result


def _timestamp(value, column):
    if isinstance(value, str):
        value = value.strip()
        try:
            if len(value) <= 10:
                raise ValueError
            value = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{column} needs a date and time.") from None
    if not isinstance(value, datetime):
        raise ValueError(f"{column} needs a date and time.")
    return (value.replace(tzinfo=NAIROBI) if value.tzinfo is None else value.astimezone(NAIROBI))


def _ticket(values, now):
    key = _text(values.get("External Key"), "External Key", 100)
    summary = _text(values.get("Summary"), "Summary", 500)
    assignee = _text(values.get("Assignee"), "Assignee", 200)
    resolution = _text(values.get("Resolution Summary"), "Resolution Summary", 10000)
    evidence = _text(values.get("Evidence Notes"), "Evidence Notes", 10000)
    description = _text(values.get("Description"), "Description", 10000)
    if not all((key, summary, assignee, resolution)):
        raise ValueError("External Key, Summary, Assignee and Resolution Summary are required.")
    if _text(values.get("Status"), "Status", 40).lower() != "closed":
        raise ValueError("Status must be Closed.")
    if _text(values.get("Assigned Department"), "Assigned Department", 60) not in ("", "IT"):
        raise ValueError("Assigned Department must be IT.")
    reported = _timestamp(values.get("Reported At"), "Reported At")
    closed = _timestamp(values.get("Closed At"), "Closed At")
    resolved_input = values.get("Resolved At")
    resolved = _timestamp(resolved_input, "Resolved At") if resolved_input not in (None, "") else None
    if resolved is None and not evidence:
        raise ValueError("Add Evidence Notes if the resolution time is unknown.")
    if not reported <= (resolved or reported) <= closed <= now:
        raise ValueError("Report, resolution and closure must be chronological and in the past.")
    ticket_id = str(uuid5(NAMESPACE_URL, f"it-workbook:{key}"))
    return {
        "ticket_id": ticket_id, "external_key": key, "summary": summary,
        "description": "\n\n".join(filter(None, (description, f"Evidence notes: {evidence}" if evidence else ""))),
        "status": "closed", "assignee": assignee, "assigned_department": "IT",
        "reporting_department": "IT", "created_at": now.isoformat(timespec="seconds"),
        "updated_at": now.isoformat(timespec="seconds"),
        "reported_at": reported.isoformat(timespec="seconds"),
        "resolved_at": resolved.isoformat(timespec="seconds") if resolved else None,
        "closed_at": closed.isoformat(timespec="seconds"),
        "resolution_summary": resolution,
        "support_request_number": f"XLSX-{ticket_id.replace('-', '').upper()}",
        **{field: _text(values.get(header), header, limit) or None
           for header, (field, limit) in OPTIONAL.items()},
    }


def read_it_workbook(payload, *, now=None):
    """Return validated ticket records, or a user-facing validation error."""
    now = now or datetime.now(NAIROBI)
    try:
        with ZipFile(BytesIO(payload)) as archive:
            if len(payload) > 5_000_000 or sum(item.file_size for item in archive.infolist()) > 20_000_000:
                raise ValueError("Workbook is too large. Split it into smaller batches.")
        book = load_workbook(BytesIO(payload), read_only=True, keep_links=False)
    except ValueError:
        raise
    except Exception:
        raise ValueError("Open a valid .xlsx workbook.") from None
    try:
        if "IT Requests" not in book.sheetnames:
            raise ValueError("The workbook needs a sheet named IT Requests.")
        sheet = book["IT Requests"]
        sheet.reset_dimensions()
        rows = sheet.iter_rows()
        headers = [str(cell.value or "").strip() for cell in next(rows, ())]
        missing = [name for name in REQUIRED if name not in headers]
        if missing:
            raise ValueError("Missing columns: " + ", ".join(missing))
        named_headers = [name for name in headers if name]
        if len(named_headers) != len(set(named_headers)):
            raise ValueError("Column headers must be unique.")
        tickets, keys = [], set()
        for number, cells in enumerate(rows, 2):
            if number > 501:
                raise ValueError("Import up to 500 rows at a time.")
            if not any(cell.value is not None for cell in cells):
                continue
            try:
                if any(cell.data_type in ("f", "e") for cell in cells):
                    raise ValueError("Paste values in place of formulas and spreadsheet errors.")
                ticket = _ticket(dict(zip(headers, (cell.value for cell in cells))), now)
                if ticket["external_key"] in keys:
                    raise ValueError("External Key repeats in this workbook.")
                tickets.append(ticket)
                keys.add(ticket["external_key"])
            except ValueError as error:
                raise ValueError(f"Row {number}: {error}") from None
        if not tickets:
            raise ValueError("The workbook contains no requests.")
        return tickets
    except ParseError:
        raise ValueError("The IT Requests sheet contains invalid spreadsheet data.") from None
    finally:
        book.close()


def import_it_tickets(session_factory, tickets, *, actor):
    """Commit new tickets and their activity as one transaction."""
    with session_factory.begin() as session:
        insert = {"postgresql": postgres_insert, "sqlite": sqlite_insert}[session.bind.dialect.name]
        created = 0
        for ticket in tickets:
            statement = insert(Ticket).values(**ticket).on_conflict_do_nothing(
                index_elements=[Ticket.external_key]
            ).returning(Ticket.ticket_id)
            ticket_id = session.scalar(statement)
            if ticket_id is None:
                continue
            session.add(Activity(
                activity_id=str(uuid5(NAMESPACE_URL, f"it-workbook-activity:{ticket_id}")),
                ticket_id=ticket_id, action="it_workbook_imported", field="Status",
                new_value="closed", note=ticket["resolution_summary"],
                timestamp=ticket["created_at"], actor=actor,
            ))
            created += 1
        return created
