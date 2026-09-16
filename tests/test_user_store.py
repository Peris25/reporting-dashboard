from reporting.access import hash_password, verify_password
from reporting.database import create_user_store, database_handles
from reporting.schema import TICKET_HEADERS


def test_user_store_roundtrip(tmp_path):
    url = f"sqlite:///{tmp_path / 'users.db'}"
    store = create_user_store(url)
    store.upsert(
        username="Jane", display_name="Jane Doe", password_hash=hash_password("temp1234"),
        department="HR", role="member", must_change_password=True,
    )
    account = store.get("jane")  # lookup is case-insensitive
    assert account is not None
    assert account.department == "HR"
    assert account.must_change_password is True
    assert verify_password("temp1234", account.password_hash)
    assert store.count() == 1

    store.set_password("jane", hash_password("newpass99"), must_change_password=False)
    account = store.get("JANE")
    assert account.must_change_password is False
    assert verify_password("newpass99", account.password_hash)


def test_upsert_updates_existing(tmp_path):
    url = f"sqlite:///{tmp_path / 'users.db'}"
    store = create_user_store(url)
    store.upsert(username="ann", display_name="Ann", password_hash=hash_password("a"),
                 department="Operations", subteam="Scheduling", role="member")
    store.upsert(username="Ann", display_name="Ann Lead", password_hash=hash_password("b"),
                 department="Operations", subteam="Approval", role="admin")
    account = store.get("ann")
    assert store.count() == 1
    assert account.display_name == "Ann Lead"
    assert account.subteam == "Approval"
    assert account.role == "admin"


def test_ticket_roundtrip_includes_department(tmp_path):
    url = f"sqlite:///{tmp_path / 'tickets.db'}"
    tickets, _ = database_handles(url)
    row = {header: "" for header in TICKET_HEADERS}
    row.update({
        "Ticket ID": "T1", "Summary": "x", "Status": "to do",
        "Created": "2026-09-16T09:00:00", "Updated At": "2026-09-16T09:00:00",
        "Assigned Department": "Operations", "Assigned Sub-team": "Approval", "Reporting Department": "BD",
    })
    tickets.append_row([row[header] for header in TICKET_HEADERS])
    records = tickets.get_all_records()
    assert records[0]["Assigned Department"] == "Operations"
    assert records[0]["Assigned Sub-team"] == "Approval"
    assert records[0]["Reporting Department"] == "BD"
