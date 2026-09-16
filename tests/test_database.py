from reporting.database import Activity, DatabaseWorksheet, Ticket, create_session_factory, ACTIVITY_MAP, TICKET_MAP
from reporting.schema import ACTIVITY_HEADERS, TICKET_HEADERS


def test_database_ticket_and_activity_round_trip(tmp_path):
    factory = create_session_factory(f"sqlite:///{tmp_path.joinpath('test.db').as_posix()}")
    tickets = DatabaseWorksheet(factory, Ticket, TICKET_HEADERS, TICKET_MAP)
    activities = DatabaseWorksheet(factory, Activity, ACTIVITY_HEADERS, ACTIVITY_MAP)

    ticket = {header: "" for header in TICKET_HEADERS}
    ticket.update(
        {
            "Ticket ID": "00000000-0000-0000-0000-000000000001",
            "Summary": "Database test",
            "Status": "to do",
            "Created": "2026-09-04T10:00:00+00:00",
            "Updated At": "2026-09-04T10:00:00+00:00",
            "Reg No": "KDA 123A",
            "Solver ID": "legacy-solver",
        }
    )
    tickets.append_row([ticket[header] for header in TICKET_HEADERS])
    assert tickets.get_all_records()[0]["Summary"] == "Database test"
    assert tickets.get_all_records()[0]["Reg No"] == "KDA 123A"
    assert tickets.get_all_records()[0]["Solver ID"] == "legacy-solver"

    activity = ["activity-1", ticket["Ticket ID"], "created", "Status", "", "to do", "", ticket["Created"], "tester"]
    activities.append_row(activity)
    assert activities.get_all_records()[0]["Actor"] == "tester"

    tickets.delete_rows(2)
    assert tickets.get_all_records() == []


def test_registration_migration_preserves_legacy_solver_id(tmp_path, monkeypatch):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE tickets (ticket_id TEXT PRIMARY KEY, solver_id TEXT)"))
        connection.execute(text("INSERT INTO tickets VALUES ('old-request', 'solver-123')"))
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.stamp(config, "20260904_02")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT solver_id, reg_no FROM tickets")).one()
        assert row.solver_id == "solver-123"
        assert row.reg_no is None
    engine.dispose()
