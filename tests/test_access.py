import pandas as pd
import pytest

from reporting.access import (
    CurrentUser, can_delete, can_manage, clean_subteam, generate_temp_password,
    hash_password, verify_password, visible_tickets,
)


def make_df():
    return pd.DataFrame([
        {"Ticket ID": "1", "Assigned Department": "IT", "Reporting Department": "HR"},
        {"Ticket ID": "2", "Assigned Department": "HR", "Reporting Department": "HR"},
        {"Ticket ID": "3", "Assigned Department": "Operations", "Reporting Department": "BD"},
        {"Ticket ID": "4", "Assigned Department": "BD", "Reporting Department": "IT"},
    ])


def test_password_hash_roundtrip():
    encoded = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", encoded)
    assert not verify_password("wrong", encoded)
    # A random salt means the same password hashes differently each time.
    assert encoded != hash_password("s3cret-pass")


def test_hash_empty_password_rejected():
    with pytest.raises(ValueError):
        hash_password("")


def test_verify_handles_garbage():
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "")
    assert not verify_password("x", "md5$1$aa$bb")


def test_admin_sees_everything():
    assert len(visible_tickets(make_df(), department="HR", admin=True)) == 4


def test_member_sees_assigned_and_reported():
    hr = visible_tickets(make_df(), department="HR", admin=False)
    # HR owns ticket 2 and raised ticket 1.
    assert set(hr["Ticket ID"]) == {"1", "2"}


def test_member_scope_is_case_insensitive():
    bd = visible_tickets(make_df(), department="bd", admin=False)
    assert set(bd["Ticket ID"]) == {"3", "4"}


def test_member_unknown_department_sees_nothing():
    assert visible_tickets(make_df(), department="", admin=False).empty


def test_currentuser_admin_flag():
    assert CurrentUser("a", "A", "IT", role="member").is_admin
    assert not CurrentUser("b", "B", "HR", role="member").is_admin
    assert CurrentUser("c", "C", "HR", role="admin").is_admin


def test_can_manage_rules():
    assert can_manage(department="HR", admin=False, ticket_department="HR")
    assert not can_manage(department="HR", admin=False, ticket_department="IT")
    assert can_manage(department="HR", admin=True, ticket_department="IT")
    assert not can_manage(department="", admin=False, ticket_department="")


def test_can_delete_admin_only():
    assert can_delete(admin=True)
    assert not can_delete(admin=False)


def test_clean_subteam():
    assert clean_subteam("Operations", "Scheduling") == "Scheduling"
    assert clean_subteam("Operations", "nope") == ""
    assert clean_subteam("HR", "Scheduling") == ""


def test_generate_temp_password_length():
    assert len(generate_temp_password(12)) == 12
    assert len(generate_temp_password()) == 10
