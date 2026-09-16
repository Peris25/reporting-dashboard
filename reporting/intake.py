"""Turn a parsed conversation into one or more draft support requests.

When an OpenAI API key is supplied, a model reads the transcript and splits it
into distinct issues, each summarised and categorised. Without a key (or if the
call fails) a deterministic heuristic produces a single draft, so the feature
degrades gracefully and stays testable offline.

The functions here return plain dicts and never touch Streamlit or the database.
"""

from __future__ import annotations

import json

import pandas as pd

from reporting.departments import DEPARTMENTS, normalize_department, normalize_subteam, subteams_for
from reporting.whatsapp import conversation, first_timestamp, participants, transcript_text

DEFAULT_CATEGORIES = [
    "Access & login", "App issue", "Job or request issue", "Payments",
    "Account or profile", "Technical guidance", "Other",
]
DEFAULT_PRIORITIES = ["Low", "Medium", "High", "Highest"]

# Keyword hints for the no-API fallback.
_CATEGORY_HINTS = {
    "Access & login": ["login", "log in", "password", "otp", "access", "sign in", "locked out"],
    "Payments": ["payment", "pay", "refund", "invoice", "mpesa", "money", "charge", "transaction"],
    "App issue": ["app", "crash", "error", "bug", "loading", "screen", "freeze", "update"],
    "Job or request issue": ["job", "request", "assignment", "reg no", "vehicle", "valuation", "submission"],
    "Account or profile": ["account", "profile", "details", "update my", "phone number", "email address"],
}
_HIGH_PRIORITY_HINTS = ["urgent", "asap", "immediately", "critical", "cannot work", "can't work", "down", "blocked"]


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
    return {
        "summary": str(issue.get("summary") or "").strip()[:300],
        "description": str(issue.get("description") or "").strip(),
        "category": _clamp(issue.get("category"), categories, "Other"),
        "priority": _clamp(issue.get("priority"), priorities, "Medium"),
        "suggested_department": department,
        "suggested_subteam": subteam,
        "requester_name": str(issue.get("requester_name") or "").strip()[:200],
        "contact": str(issue.get("contact") or "").strip()[:60],
        "reported_at": stamp.isoformat() if pd.notna(stamp) else "",
        "excerpt": str(issue.get("excerpt") or "").strip(),
    }


def _build_prompt(transcript, *, categories, priorities):
    return (
        "You triage a customer-support WhatsApp chat for Solvit. Split the "
        "conversation into DISTINCT support issues. Return STRICT JSON of the form "
        '{"issues": [ ... ]}. Each issue has: summary (one short line), description '
        "(what happened, expected result, steps tried), category (one of "
        f"{categories}), priority (one of {priorities}), suggested_department (one of "
        f"{DEPARTMENTS} or empty), suggested_subteam (only for Operations: one of "
        f"{subteams_for('Operations')} or empty), requester_name (the customer, if "
        "clear), contact (phone if present), reported_at (ISO 8601 if a time is "
        "clear, else empty), excerpt (the few chat lines most relevant to this "
        "issue). If there is only one issue, return a single-element list. Do not "
        "invent issues that are not in the chat.\n\nCHAT:\n" + transcript
    )


def _extract_with_openai(transcript, *, categories, priorities, api_key, model):
    from openai import OpenAI  # imported lazily so the package is optional

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You return only valid JSON."},
            {"role": "user", "content": _build_prompt(transcript, categories=categories, priorities=priorities)},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    payload = json.loads(response.choices[0].message.content)
    issues = payload.get("issues") if isinstance(payload, dict) else payload
    return list(issues or [])


def _extract_heuristic(messages, transcript, *, categories, priorities):
    convo = conversation(messages)
    if not convo:
        return []
    lowered = transcript.lower()
    category = "Other"
    for name, hints in _CATEGORY_HINTS.items():
        if name in categories and any(hint in lowered for hint in hints):
            category = name
            break
    priority = "High" if any(hint in lowered for hint in _HIGH_PRIORITY_HINTS) else "Medium"
    first = first_timestamp(messages)
    names = participants(messages)
    summary = convo[0]["text"].splitlines()[0][:120] if convo else "WhatsApp support request"
    return [{
        "summary": summary or "WhatsApp support request",
        "description": transcript,
        "category": category,
        "priority": priority,
        "suggested_department": "",
        "suggested_subteam": "",
        "requester_name": names[0] if names else "",
        "contact": "",
        "reported_at": first.isoformat() if first is not None else "",
        "excerpt": transcript[:2000],
    }]


def extract_issues(messages, *, categories=None, priorities=None, api_key=None, model="gpt-4o-mini"):
    """Return a list of normalized draft dicts from parsed WhatsApp messages."""
    categories = categories or DEFAULT_CATEGORIES
    priorities = priorities or DEFAULT_PRIORITIES
    transcript = transcript_text(messages)
    if not transcript.strip():
        return []
    raw_issues = None
    if api_key:
        try:
            raw_issues = _extract_with_openai(
                transcript, categories=categories, priorities=priorities, api_key=api_key, model=model
            )
        except Exception:
            raw_issues = None  # fall back to the heuristic on any API/parse failure
    if not raw_issues:
        raw_issues = _extract_heuristic(messages, transcript, categories=categories, priorities=priorities)
    return [_normalize_issue(issue, categories=categories, priorities=priorities) for issue in raw_issues if issue]
