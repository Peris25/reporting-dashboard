"""Department and sub-team configuration for role-based access.

Departments are the routing and ownership dimension for support requests. IT is
the global-view department, so its members see every request across the company.
Operations is split into sub-teams that are tagged on the request and used for
filtering rather than for separate logins.
"""

DEPARTMENTS = ["IT", "HR", "Operations", "BD"]

# The department whose members can see and manage every request.
GLOBAL_VIEW_DEPARTMENT = "IT"

# Sub-teams live under a parent department. Only Operations has them today.
SUBTEAMS = {
    "Operations": ["Scheduling", "Approval", "Solver (Submissions)"],
}

ROLES = ["member", "admin"]

ALL_DEPARTMENTS_OPTION = "All departments"
ALL_SUBTEAMS_OPTION = "All sub-teams"


def normalize_department(value):
    """Return the canonical department name, or "" if it is not recognised."""
    text = str(value or "").strip()
    for department in DEPARTMENTS:
        if text.lower() == department.lower():
            return department
    return ""


def subteams_for(department):
    """Return the ordered sub-teams for a department (empty when it has none)."""
    return SUBTEAMS.get(normalize_department(department), [])


def has_subteams(department):
    return bool(subteams_for(department))


def normalize_subteam(department, value):
    """Return the canonical sub-team for a department, or "" if unrecognised."""
    text = str(value or "").strip()
    for subteam in subteams_for(department):
        if text.lower() == subteam.lower():
            return subteam
    return ""


def is_global_view(department):
    """Members of the global-view department see every department's requests."""
    return normalize_department(department) == GLOBAL_VIEW_DEPARTMENT
