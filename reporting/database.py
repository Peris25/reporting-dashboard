from __future__ import annotations

from dataclasses import dataclass
import os
import re

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .schema import ACTIVITY_HEADERS, TICKET_HEADERS


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    __tablename__ = "tickets"

    ticket_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    external_key: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    summary: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), index=True)
    priority: Mapped[str | None] = mapped_column(String(30), index=True)
    severity: Mapped[str | None] = mapped_column(String(30))
    category: Mapped[str | None] = mapped_column(String(100))
    subcategory: Mapped[str | None] = mapped_column(String(100))
    assignee: Mapped[str | None] = mapped_column(String(200), index=True)
    reporter: Mapped[str | None] = mapped_column(String(200))
    team: Mapped[str | None] = mapped_column(String(100), index=True)
    channel: Mapped[str | None] = mapped_column(String(50))
    customer_email: Mapped[str | None] = mapped_column(String(320))
    customer_whatsapp: Mapped[str | None] = mapped_column(String(30))
    escalation_owner: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    first_response_at: Mapped[str | None] = mapped_column(String(40))
    diagnosed_at: Mapped[str | None] = mapped_column(String(40))
    resolved_at: Mapped[str | None] = mapped_column(String(40))
    closed_at: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    reopened_count: Mapped[int] = mapped_column(Integer, default=0)
    resolution_category: Mapped[str | None] = mapped_column(String(100))
    support_request_number: Mapped[str | None] = mapped_column(String(40), unique=True, index=True)
    requester_type: Mapped[str | None] = mapped_column(String(40), index=True)
    requester_name: Mapped[str | None] = mapped_column(String(200), index=True)
    job_request_id: Mapped[str | None] = mapped_column(String(120), index=True)
    solver_id: Mapped[str | None] = mapped_column(String(120), index=True)
    reg_no: Mapped[str | None] = mapped_column(String(120), index=True)
    reported_at: Mapped[str | None] = mapped_column(String(40))
    office_department: Mapped[str | None] = mapped_column(String(120))
    received_by: Mapped[str | None] = mapped_column(String(200), index=True)
    call_outcome: Mapped[str | None] = mapped_column(String(50))
    callback_required: Mapped[str | None] = mapped_column(String(10), index=True)
    callback_deadline: Mapped[str | None] = mapped_column(String(40))
    callback_completed_at: Mapped[str | None] = mapped_column(String(40))
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    assigned_department: Mapped[str | None] = mapped_column(String(60), index=True)
    assigned_subteam: Mapped[str | None] = mapped_column(String(60), index=True)
    reporting_department: Mapped[str | None] = mapped_column(String(60), index=True)


class Activity(Base):
    __tablename__ = "ticket_activity"

    activity_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    field: Mapped[str | None] = mapped_column(String(100))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[str] = mapped_column(String(40), index=True)
    actor: Mapped[str | None] = mapped_column(String(200))


class User(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(120), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    department: Mapped[str] = mapped_column(String(60), index=True)
    subteam: Mapped[str | None] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(20), default="member")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String(40), default="")
    updated_at: Mapped[str] = mapped_column(String(40), default="")


TICKET_MAP = {
    "Ticket ID": "ticket_id", "External Key": "external_key", "Summary": "summary",
    "Description": "description", "Status": "status", "Priority": "priority",
    "Severity": "severity", "Category": "category", "Subcategory": "subcategory",
    "Assignee": "assignee", "Reporter": "reporter", "Team": "team", "Channel": "channel",
    "Customer Email": "customer_email", "Customer WhatsApp": "customer_whatsapp",
    "Escalation Owner": "escalation_owner", "Created": "created_at",
    "First Response At": "first_response_at", "Diagnosed At": "diagnosed_at",
    "Resolved At": "resolved_at", "Closed At": "closed_at", "Updated At": "updated_at",
    "Reopened Count": "reopened_count", "Resolution Category": "resolution_category",
    "Support Request Number": "support_request_number", "Requester Type": "requester_type",
    "Requester Name": "requester_name", "Job Request ID": "job_request_id", "Solver ID": "solver_id",
    "Office Department": "office_department", "Received By": "received_by", "Call Outcome": "call_outcome",
    "Callback Required": "callback_required", "Callback Deadline": "callback_deadline",
    "Callback Completed At": "callback_completed_at", "Resolution Summary": "resolution_summary",
    "Reg No": "reg_no",
    "Reported At": "reported_at",
    "Assigned Department": "assigned_department",
    "Assigned Sub-team": "assigned_subteam",
    "Reporting Department": "reporting_department",
}
ACTIVITY_MAP = {
    "Activity ID": "activity_id", "Ticket ID": "ticket_id", "Action": "action", "Field": "field",
    "Old Value": "old_value", "New Value": "new_value", "Note": "note",
    "Timestamp": "timestamp", "Actor": "actor",
}


def database_url(url=None):
    url = url or os.getenv("DATABASE_URL", "sqlite:///reporting.db")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def create_session_factory(url=None):
    engine = create_engine(url or database_url(), pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@dataclass
class FoundCell:
    row: int
    value: str


class DatabaseWorksheet:
    """Small compatibility layer while the Streamlit UI migrates from Sheets."""

    def __init__(self, session_factory, model, headers, mapping):
        self.session_factory = session_factory
        self.model = model
        self.headers = headers
        self.mapping = mapping

    def _objects(self):
        with self.session_factory() as session:
            primary_key = getattr(self.model, self.mapping[self.headers[0]])
            return list(session.scalars(select(self.model).order_by(primary_key)).all())

    def get_all_records(self):
        return [
            {header: getattr(obj, self.mapping[header]) or "" for header in self.headers}
            for obj in self._objects()
        ]

    def get_all_values(self):
        return [self.headers] + [[record[h] for h in self.headers] for record in self.get_all_records()]

    def append_row(self, values):
        self.append_rows([values])

    def append_rows(self, rows):
        with self.session_factory.begin() as session:
            for values in rows:
                data = {self.mapping[h]: (values[i] if i < len(values) else "") for i, h in enumerate(self.headers)}
                if self.model is Ticket:
                    data["reopened_count"] = int(data.get("reopened_count") or 0)
                    data["external_key"] = data.get("external_key") or None
                session.add(self.model(**data))

    def find(self, query, in_column=1, **_kwargs):
        header = self.headers[in_column - 1]
        for row_number, record in enumerate(self.get_all_records(), start=2):
            if str(record[header]) == str(query):
                return FoundCell(row_number, str(record[header]))
        return None

    def update(self, values, range_name=None, **_kwargs):
        if range_name and re.fullmatch(r"[A-Z]+1:[A-Z]+1", range_name):
            return
        if not values:
            return
        data = {self.mapping[h]: (values[0][i] if i < len(values[0]) else "") for i, h in enumerate(self.headers)}
        primary_key = self.mapping[self.headers[0]]
        with self.session_factory.begin() as session:
            obj = session.get(self.model, data[primary_key])
            if obj is None:
                raise ValueError(f"Record {data[primary_key]} no longer exists")
            for key, value in data.items():
                if key != primary_key:
                    setattr(obj, key, int(value or 0) if key == "reopened_count" else (value or None))

    def delete_rows(self, row_number):
        records = self.get_all_records()
        index = row_number - 2
        if index < 0 or index >= len(records):
            return
        key = records[index][self.headers[0]]
        with self.session_factory.begin() as session:
            obj = session.get(self.model, key)
            if obj is not None:
                session.delete(obj)


def database_handles(url=None):
    factory = create_session_factory(database_url(url))
    return (
        DatabaseWorksheet(factory, Ticket, TICKET_HEADERS, TICKET_MAP),
        DatabaseWorksheet(factory, Activity, ACTIVITY_HEADERS, ACTIVITY_MAP),
    )


@dataclass
class UserAccount:
    """A detached, read-only snapshot of a user row for use outside a session."""

    username: str
    display_name: str
    password_hash: str
    department: str
    subteam: str
    role: str
    must_change_password: bool
    active: bool


def _snapshot(user):
    if user is None:
        return None
    return UserAccount(
        username=user.username,
        display_name=user.display_name,
        password_hash=user.password_hash,
        department=user.department,
        subteam=user.subteam or "",
        role=user.role or "member",
        must_change_password=bool(user.must_change_password),
        active=bool(user.active),
    )


class UserStore:
    """Account persistence kept separate from the ticket/activity worksheets."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    @staticmethod
    def normalize_username(username):
        return str(username or "").strip().lower()

    def get(self, username):
        with self.session_factory() as session:
            return _snapshot(session.get(User, self.normalize_username(username)))

    def list(self):
        with self.session_factory() as session:
            return [_snapshot(user) for user in session.scalars(select(User).order_by(User.username)).all()]

    def count(self):
        with self.session_factory() as session:
            return len(list(session.scalars(select(User.username)).all()))

    def upsert(self, *, username, display_name, password_hash, department, subteam="",
               role="member", must_change_password=True, active=True):
        key = self.normalize_username(username)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.session_factory.begin() as session:
            user = session.get(User, key)
            if user is None:
                user = User(username=key, created_at=now)
                session.add(user)
            user.display_name = display_name
            user.password_hash = password_hash
            user.department = department
            user.subteam = subteam or None
            user.role = role or "member"
            user.must_change_password = bool(must_change_password)
            user.active = bool(active)
            user.updated_at = now
        return key

    def set_password(self, username, password_hash, *, must_change_password=False):
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.session_factory.begin() as session:
            user = session.get(User, self.normalize_username(username))
            if user is None:
                raise ValueError("This account no longer exists.")
            user.password_hash = password_hash
            user.must_change_password = bool(must_change_password)
            user.updated_at = now


def create_user_store(url=None):
    return UserStore(create_session_factory(database_url(url)))
