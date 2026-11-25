from reporting.intake import DEFAULT_CATEGORIES, extract_issues
from reporting.whatsapp import parse_export
from reporting.database import create_draft_store

# A busy ops chat: routine chatter plus one genuine complaint and one suggestion.
CHAT = (
    "24/06/2025, 15:02 - +254 716 375730: <Media omitted>\n"
    "24/06/2025, 15:03 - +254 705 606592: @approval team kindly approve KCQ 462K\n"
    "24/06/2025, 15:04 - +254 700 111222: Kangemi solver?\n"
    "24/06/2025, 15:05 - +254 700 333444: the app keeps crashing when I upload photos\n"
    "24/06/2025, 15:06 - +254 700 555666: I suggest we add a status filter to speed things up\n"
)


def test_heuristic_ignores_routine_ops_and_keeps_issues():
    issues = extract_issues(parse_export(CHAT), categories=DEFAULT_CATEGORIES, api_key=None)
    summaries = " || ".join(i["summary"].lower() for i in issues)
    # The approval, dispatch, and media lines are not issues.
    assert "approve" not in summaries and "solver?" not in summaries and "media" not in summaries
    # The complaint and the suggestion are captured.
    assert any("crashing" in i["summary"].lower() for i in issues)
    assert any(i["category"] == "Improvement suggestion" for i in issues)
    assert all(i["suggested_department"] == "" for i in issues)  # routed by a human
    assert all(i["source_fingerprint"] for i in issues)


def test_within_scan_deduplication():
    dup = (
        "24/06/2025, 15:05 - A: the app keeps crashing on upload\n"
        "24/06/2025, 16:05 - A: the app keeps crashing on upload\n"
    )
    issues = extract_issues(parse_export(dup), categories=DEFAULT_CATEGORIES, api_key=None)
    assert len(issues) == 1  # the same message reappearing collapses to one draft


def test_empty_chat_yields_no_issues():
    assert extract_issues(parse_export("no headers here\njust text"), api_key=None) == []


def test_normalization_clamps_unknown_values():
    # A fake "model" issue with out-of-vocab values gets clamped on normalization.
    from reporting.intake import _normalize_issue

    issue = _normalize_issue(
        {"summary": "x", "category": "Nonsense", "priority": "SuperHigh",
         "suggested_department": "Legal", "suggested_subteam": "Whatever"},
        categories=DEFAULT_CATEGORIES, priorities=["Low", "Medium", "High", "Highest"],
    )
    assert issue["category"] == "Other"
    assert issue["priority"] == "Medium"
    assert issue["suggested_department"] == ""
    assert issue["suggested_subteam"] == ""


def test_draft_store_roundtrip_and_resolve(tmp_path):
    store = create_draft_store(f"sqlite:///{tmp_path / 'drafts.db'}")
    draft_id = store.add({
        "summary": "Cannot log in", "description": "detail", "category": "Access & login",
        "priority": "High", "suggested_department": "IT", "source_reference": "chat.txt",
    })
    pending = store.list("pending")
    assert len(pending) == 1 and pending[0]["draft_id"] == draft_id
    store.resolve(draft_id, status="approved", reviewed_by="alice@x", approved_ticket_id="t-1")
    assert store.list("pending") == []
    approved = store.list("approved")
    assert approved[0]["approved_ticket_id"] == "t-1"
    assert approved[0]["reviewed_by"] == "alice@x"


def test_delete_removes_only_pending_draft_without_a_reason():
    store = create_draft_store("sqlite://")
    pending = store.add({"summary": "Remove this draft"})
    other = store.add({"summary": "Keep this draft"})
    approved = store.add({"summary": "Keep this approved draft"})
    assert store.resolve(approved, status="approved")
    assert store.delete_pending(pending)
    assert not store.delete_pending(pending)
    assert not store.delete_pending(approved)
    assert not store.resolve(pending, status="approved", ticket={})
    assert store.get(pending) is None
    assert [draft["draft_id"] for draft in store.list()] == [other]
    assert store.get(approved)["status"] == "approved"


def test_approval_saves_ticket_and_activity_before_draft_can_be_deleted():
    from sqlalchemy import select

    from reporting.database import Activity, Ticket

    store = create_draft_store("sqlite://")
    draft = store.add({"summary": "Example issue"})
    ticket = {
        "Ticket ID": "example-ticket", "Support Request Number": "SUP-EXAMPLE",
        "Summary": "Example issue", "Description": "Example details",
        "Status": "to do", "Created": "2026-01-01", "Updated At": "2026-01-01",
        "Assigned Department": "IT",
    }
    assert store.resolve(
        draft, status="approved", reviewed_by="test-admin",
        approved_ticket_id=ticket["Ticket ID"], ticket=ticket,
    )
    assert not store.delete_pending(draft)
    assert not store.resolve(draft, status="rejected")
    with store.session_factory() as session:
        saved = session.get(Ticket, "example-ticket")
        assert saved.assigned_department == "IT"
        actions = session.scalars(select(Activity.action).where(Activity.ticket_id == saved.ticket_id)).all()
        assert set(actions) == {"support_request_created", "intake_approved"}


def test_bulk_delete_skips_approved_missing_and_unselected_drafts():
    store = create_draft_store("sqlite://")
    first, second, other, approved = [store.add({"summary": str(i)}) for i in range(4)]
    assert store.resolve(approved, status="approved")
    assert store.delete_pending_many([]) == 0
    assert store.delete_pending_many([first, second, first, approved, "missing"]) == 2
    assert store.delete_pending_many([first, second]) == 0
    assert [draft["draft_id"] for draft in store.list()] == [other]
    assert store.get(approved)["status"] == "approved"
