import pytest
from sqlalchemy import create_engine, select, text

from reporting.bootstrap import initialize_database
from reporting.database import Base, Ticket, Activity
from reporting.transfer import snapshot, copy_records


def test_cloud_initialization_is_repeatable_and_keeps_records(tmp_path):
    url = f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}"
    initialize_database(url)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(Ticket.__table__.insert(), {
            "ticket_id": "keep", "summary": "Existing request", "status": "to do",
            "created_at": "2026-09-09T21:00:00+03:00", "updated_at": "2026-09-10T10:00:00+03:00",
        })
    initialize_database(url)
    with engine.connect() as connection:
        assert connection.execute(select(Ticket.ticket_id)).scalar_one() == "keep"
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260916_05"
    engine.dispose()


def test_transfer_preserves_all_records_and_refuses_to_overwrite(tmp_path):
    source = create_engine(f"sqlite:///{(tmp_path / 'source.db').as_posix()}")
    target = create_engine(f"sqlite:///{(tmp_path / 'target.db').as_posix()}")
    Base.metadata.create_all(source)
    Base.metadata.create_all(target)
    with source.begin() as connection:
        connection.execute(Ticket.__table__.insert(), {
            "ticket_id": "ticket-1", "summary": "Original issue", "status": "closed", "reg_no": "KDA 123A",
            "created_at": "2026-09-10T10:00:00+03:00", "reported_at": "2026-09-09T21:00:00+03:00",
            "updated_at": "2026-09-10T10:00:00+03:00", "solver_id": "old-solver",
        })
        connection.execute(Activity.__table__.insert(), {
            "activity_id": "event-1", "ticket_id": "ticket-1", "action": "status_changed",
            "timestamp": "2026-09-10T10:00:00+03:00", "old_value": "to do", "new_value": "closed",
        })
    original = snapshot(source)
    assert copy_records(original, target) == {"tickets": 1, "ticket_activity": 1}
    assert snapshot(target) == original
    assert snapshot(source) == original
    with pytest.raises(ValueError, match="not empty"):
        copy_records(original, target)
    assert snapshot(target) == original
    source.dispose()
    target.dispose()


def test_failed_transfer_rolls_back_both_tables(tmp_path):
    target = create_engine(f"sqlite:///{(tmp_path / 'rollback.db').as_posix()}")
    Base.metadata.create_all(target)
    records = {"tickets": [{"ticket_id": "ticket-1", "summary": "Issue", "status": "to do",
                            "created_at": "2026-09-10", "updated_at": "2026-09-10"}],
               "ticket_activity": [{"activity_id": "activity-1", "unknown_column": "unsupported"}]}
    with pytest.raises(ValueError, match="unsupported columns"):
        copy_records(records, target)
    assert snapshot(target) == {"tickets": [], "ticket_activity": []}
    target.dispose()
