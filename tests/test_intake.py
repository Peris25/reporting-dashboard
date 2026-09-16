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
