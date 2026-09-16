from .schema import STATUSES

ALLOWED_TRANSITIONS = {
    "to do": {"diagnosed", "closed"},
    "diagnosed": {"in progress", "to do", "closed"},
    "in progress": {"qa testing", "diagnosed", "closed"},
    "qa testing": {"deployed", "in progress", "closed"},
    "deployed": {"closed", "in progress"},
    "closed": {"in progress"},
}


def normalize_status(value):
    aliases = {
        "todo": "to do",
        "to-do": "to do",
        "backlog": "to do",
        "wishlist": "to do",
        "staging": "qa testing",
        "verified by solvit": "deployed",
        "done": "closed",
        "resolved": "closed",
    }
    normalized = str(value or "").strip().lower()
    return aliases.get(normalized, normalized if normalized in STATUSES else "to do")


def can_transition(old_status, new_status):
    old_status = normalize_status(old_status)
    new_status = normalize_status(new_status)
    return old_status == new_status or new_status in ALLOWED_TRANSITIONS.get(old_status, set())
