from reporting.intake import DEFAULT_CATEGORIES, extract_issues
from reporting.whatsapp import parse_export
from reporting.database import create_draft_store

CHAT = (
    "[2026/09/16, 14:30:05] Alice: Hi, I cannot log in, it says wrong password\n"
    "[2026/09/16, 14:31:00] Support: Have you reset it?\n"
    "[2026/09/16, 14:32:00] Alice: yes still urgent, I am blocked\n"
)


def test_heuristic_extracts_single_draft_without_api_key():
    issues = extract_issues(parse_export(CHAT), categories=DEFAULT_CATEGORIES, api_key=None)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["category"] == "Access & login"      # keyword: "log in" / "password"
    assert issue["priority"] == "High"                # keyword: "urgent" / "blocked"
    assert issue["requester_name"] == "Alice"
    assert issue["summary"]
    assert issue["reported_at"]                        # earliest chat timestamp
    # Suggested department/subteam are left for the human when heuristic-only.
    assert issue["suggested_department"] == ""


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
