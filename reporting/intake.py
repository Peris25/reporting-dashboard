"""Turn a (date-windowed) WhatsApp conversation into draft support requests.

The source is a busy operations group chat. Most messages are on-the-spot
operational chatter (job approvals, solver dispatch, logbook/letter submissions,
greetings, acknowledgements) that are NOT support requests. What we want to
surface are genuine issues: client complaints, app misbehaviour or bugs, and
suggestions to improve a process, workflow, or the system.

With an OpenAI API key a model reads the messages in batches and returns only
those genuine issues. Without a key, a keyword heuristic flags likely issues so
the feature still works (lower quality). Drafts come in with no department set;
the reviewer routes them on approval.

These functions return plain dicts and never touch Streamlit or the database.
"""

from __future__ import annotations

import hashlib
import json
import re

import pandas as pd

from reporting.departments import normalize_department, normalize_subteam

DEFAULT_CATEGORIES = [
    "Complaint", "App issue", "Improvement suggestion", "Access & login",
    "Job or request issue", "Payments", "Account or profile", "Technical guidance", "Other",
]
DEFAULT_PRIORITIES = ["Low", "Medium", "High", "Highest"]

# Fallback (no-API) hints. Genuine-issue words, and routine ops to ignore.
_ISSUE_HINTS = [
    "complain", "complaint", "not working", "doesn't work", "does not work", "cannot", "can't",
    "unable", "error", "bug", "crash", "fail", "failed", "issue", "problem", "delay", "delayed",
    "slow", "stuck", "wrong", "poor", "disappoint", "suggest", "suggestion", "improve",
    "improvement", "recommend", "should be able", "why is", "why does", "not able", "keeps",
]
_IGNORE_HINTS = ["approve", "approval", "logbook", "letter for", "<media omitted>"]


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def fingerprint(text):
    """A stable hash for de-duplicating drafts across overlapping re-uploads."""
    return hashlib.sha256(_clean(text).encode("utf-8")).hexdigest()[:32]


def _clamp(value, allowed, default):
    text = str(value or "").strip()
    for option in allowed:
        if text.lower() == option.lower():
            return option
    return default


def _normalize_issue(issue, *, categories, priorities, dayfirst=True):
    department = normalize_department(issue.get("suggested_department"))
    subteam = normalize_subteam(department, issue.get("suggested_subteam")) if department else ""
    reported = issue.get("reported_at") or ""
    stamp = pd.to_datetime(reported, errors="coerce", dayfirst=dayfirst) if reported else pd.NaT
    excerpt = str(issue.get("excerpt") or "").strip()
    summary = str(issue.get("summary") or "").strip()[:300]
    return {
        "summary": summary,
        "description": str(issue.get("description") or "").strip(),
        "category": _clamp(issue.get("category"), categories, "Other"),
        "priority": _clamp(issue.get("priority"), priorities, "Medium"),
        "suggested_department": department,
        "suggested_subteam": subteam,
        "requester_name": str(issue.get("requester_name") or "").strip()[:200],
        "contact": str(issue.get("contact") or "").strip()[:60],
        "reported_at": stamp.isoformat() if pd.notna(stamp) else "",
        "excerpt": excerpt,
        "source_fingerprint": fingerprint(excerpt or summary),
    }


def _batches(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _format_block(messages):
    lines = []
    for message in messages:
        stamp = f"[{message['timestamp']}] " if message.get("timestamp") else ""
        lines.append(f"{stamp}{message['sender']}: {message['text']}")
    return "\n".join(lines)


def _build_prompt(block, *, categories):
    return (
        "You review messages from Solvit's operations WhatsApp group and extract ONLY "
        "genuine support issues worth logging: client complaints, app misbehaviour or "
        "bugs, and suggestions to improve a process, workflow, or the system. IGNORE "
        "routine operational chatter such as job approvals, solver dispatch requests, "
        "logbook or letter submissions, greetings, acknowledgements, and media. If a "
        "batch has no genuine issues, return an empty list.\n\n"
        'Return STRICT JSON: {"issues": [ ... ]}. Each issue has: summary (one short '
        "line), description (what the person reported), category (one of "
        f"{categories}), priority (one of {DEFAULT_PRIORITIES}), requester_name (the "
        "sender, name or phone), contact (phone if present), reported_at (copy the "
        "message time in ISO 8601 if shown, else empty), excerpt (the exact message "
        "line(s)). Leave department out; a human routes it. Do not invent issues.\n\n"
        "MESSAGES:\n" + block
    )


def _extract_with_openai(messages, *, categories, api_key, model, batch_size):
    from openai import OpenAI  # imported lazily so the package stays optional

    client = OpenAI(api_key=api_key)
    issues = []
    for batch in _batches(messages, batch_size):
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You return only valid JSON."},
                {"role": "user", "content": _build_prompt(_format_block(batch), categories=categories)},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        payload = json.loads(response.choices[0].message.content)
        found = payload.get("issues") if isinstance(payload, dict) else payload
        issues.extend(found or [])
    return issues


def _looks_like_issue(text):
    low = _clean(text)
    if any(hint in low for hint in _IGNORE_HINTS) and not any(hint in low for hint in _ISSUE_HINTS):
        return False
    return any(hint in low for hint in _ISSUE_HINTS)


def _extract_heuristic(messages, *, categories):
    issues = []
    for message in messages:
        if not _looks_like_issue(message["text"]):
            continue
        low = message["text"].lower()
        category = "Complaint"
        if "suggest" in low or "improve" in low or "recommend" in low:
            category = "Improvement suggestion" if "Improvement suggestion" in categories else "Other"
        elif any(word in low for word in ["app", "error", "bug", "crash", "loading"]):
            category = "App issue"
        issues.append({
            "summary": message["text"].splitlines()[0][:120],
            "description": message["text"],
            "category": category,
            "priority": "Medium",
            "requester_name": message["sender"],
            "contact": message["sender"] if message["sender"].startswith("+") else "",
            "reported_at": message.get("timestamp", ""),
            "excerpt": f"{message['sender']}: {message['text']}",
        })
    return issues


def extract_issues(messages, *, categories=None, priorities=None, api_key=None,
                   model="gpt-4o-mini", batch_size=120):
    """Return normalized draft dicts from already date-filtered WhatsApp messages.

    ``messages`` should be the conversation messages for the chosen window
    (system lines and media already removed by the caller, or handled here).
    """
    categories = categories or DEFAULT_CATEGORIES
    priorities = priorities or DEFAULT_PRIORITIES
    usable = [m for m in messages if not m.get("system") and m.get("sender") and "<media omitted>" not in m["text"].lower()]
    if not usable:
        return []
    raw = None
    if api_key:
        try:
            raw = _extract_with_openai(usable, categories=categories, api_key=api_key, model=model, batch_size=batch_size)
        except Exception:
            raw = None  # fall back to the heuristic on any API/parse failure
    if raw is None:
        raw = _extract_heuristic(usable, categories=categories)
    normalized = [_normalize_issue(issue, categories=categories, priorities=priorities) for issue in raw if issue]
    # Drop duplicates within a single scan by fingerprint.
    seen, unique = set(), []
    for issue in normalized:
        if issue["source_fingerprint"] in seen:
            continue
        seen.add(issue["source_fingerprint"])
        unique.append(issue)
    return unique
