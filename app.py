import streamlit as st
import pandas as pd
import altair as alt
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import uuid
from urllib.parse import quote
import hashlib
import hmac
import os

from reporting.jira import import_summary, normalize_jira_csv
from reporting.schema import ACTIVITY_HEADERS, STATUSES, TICKET_HEADERS
from reporting.sla import enrich_tickets, format_duration, overdue_milestones, reported_time
from reporting.views import render_department_breakdown, render_reporting_views, render_weekly_report
from reporting.analytics import ALL_REQUESTERS_OPTION, filter_requests
from reporting.workflow import can_transition
from reporting.history import request_history
from reporting.database import DraftStore, create_user_store, create_weekly_task_store, database_handles
from reporting.bootstrap import initialize_database
from reporting.whatsapp import parse_export, parse_timestamp
from reporting.workbook_import import import_it_tickets, read_it_workbook
from sqlalchemy.exc import SQLAlchemyError
from reporting.intake import extract_issues, DEFAULT_CATEGORIES
from reporting.graph_excel import GraphConfig
from reporting.weekly_sync import sync_weekly_tasks, DEFAULT_WORKSHEET
from reporting.weekly_tracker import (
    STATUSES as WEEKLY_STATUSES, completion_by_department, completion_by_week, completion_stats,
)
from reporting.access import (
    CurrentUser, can_delete, can_manage, clean_subteam, hash_password, verify_password, visible_tickets,
)
from reporting.departments import (
    ALL_DEPARTMENTS_OPTION, ALL_SUBTEAMS_OPTION, DEPARTMENTS, GLOBAL_VIEW_DEPARTMENT,
    normalize_department, subteams_for,
)
from sqlalchemy.engine import make_url
from reporting.theme import apply_solvit_theme, render_brand_header, render_dashboard_hero, render_kpi_cards, render_login_header, render_sidebar_footer, render_sidebar_header

st.set_page_config(page_title="Reporting", layout="wide")
apply_solvit_theme()


def setting(name, default=""):
    if name in os.environ:
        return os.environ[name]
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


# ---- Config ----
DIAGNOSIS_SLA_HOURS = 2
RESOLUTION_SLA_HOURS = 48

USE_DATABASE = str(setting("USE_DATABASE", "true")).lower() == "true"
SHEET_NAME = setting("SHEET_NAME")
WORKSHEET_NAME = setting("WORKSHEET_NAME")
ACTIVITY_WORKSHEET_NAME = setting("ACTIVITY_WORKSHEET_NAME", "ticket_activity_log")
SUPPORT_EMAIL = setting("SUPPORT_EMAIL")
SUPPORT_WHATSAPP = str(setting("SUPPORT_WHATSAPP")).replace("+", "").replace(" ", "")
DASHBOARD_PASSWORD_HASH = setting("DASHBOARD_PASSWORD_HASH")
# A bootstrap admin lets someone sign in before any accounts are seeded, and
# recover access if every account is ever locked out. It always has the IT
# global view.
BOOTSTRAP_ADMIN_USER = str(setting("DASHBOARD_ADMIN_USER")).strip()
BOOTSTRAP_ADMIN_PASSWORD = setting("DASHBOARD_ADMIN_PASSWORD")
# WhatsApp intake uses OpenAI to split and categorise chats when a key is set;
# without one it falls back to a single heuristic draft.
OPENAI_API_KEY = setting("OPENAI_API_KEY")
OPENAI_MODEL = setting("OPENAI_MODEL", "gpt-4o-mini")
# Weekly Manager Tracker (read live via Microsoft Graph).
TRACKER_SHARE_URL = setting("TRACKER_SHARE_URL")
TRACKER_WORKSHEET = setting("TRACKER_WORKSHEET", DEFAULT_WORKSHEET)

REQUIRED_HEADERS = TICKET_HEADERS
INTAKE_CATEGORIES = DEFAULT_CATEGORIES


# ---- Google Sheets helpers ----
@st.cache_resource
def get_client():
    creds_dict = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc


@st.cache_resource
def get_sheet_handles():
    if USE_DATABASE:
        configured_url = setting("DATABASE_URL")
        if str(setting("REQUIRE_POSTGRES", "false")).lower() == "true":
            try:
                is_postgres = bool(configured_url) and make_url(configured_url).get_backend_name() in ["postgres", "postgresql"]
            except Exception:
                is_postgres = False
            if not is_postgres:
                st.error("Set DATABASE_URL to your PostgreSQL connection string in Streamlit Secrets before using this dashboard.")
                st.stop()
        if str(setting("AUTO_MIGRATE", "false")).lower() == "true":
            if not configured_url:
                st.error("Set DATABASE_URL before enabling automatic database setup.")
                st.stop()
            initialize_database(configured_url)
        return database_handles(configured_url or None)
    gc = get_client()
    sh = gc.open(SHEET_NAME)
    ws = sh.worksheet(WORKSHEET_NAME)
    try:
        activity_ws = sh.worksheet(ACTIVITY_WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        activity_ws = sh.add_worksheet(title=ACTIVITY_WORKSHEET_NAME, rows=1000, cols=20)
    return ws, activity_ws


def ensure_headers(ws, expected_headers):
    values = ws.get_all_values()
    if not values:
        ws.append_row(expected_headers)
        return
    header = values[0]
    if header == expected_headers:
        return
    # Safely extend the previous schema without rearranging existing columns.
    if header == expected_headers[:len(header)]:
        ws.update(values=[expected_headers], range_name=f"A1:{column_letter(len(expected_headers))}1")
        return
    if header != expected_headers:
        st.error(
            "Your sheet headers don't match what the app expects."
            f"Expected: {expected_headers}"
            f"Found:    {header}"
            "Fix row 1 to match exactly."
        )
        st.stop()


def read_df(ws, required_headers) -> pd.DataFrame:
    rows = ws.get_all_records()
    df = pd.DataFrame(rows)
    for col in required_headers:
        if col not in df.columns:
            df[col] = ""
    return df


def append_ticket(ws, ticket):
    """Append without rewriting the sheet (safer for concurrent users)."""
    ws.append_row([ticket.get(col, "") for col in REQUIRED_HEADERS])


def update_ticket(ws, ticket_id, values):
    """Update one ticket row and preserve unrelated rows and sheet formatting."""
    ticket_cell = ws.find(str(ticket_id), in_column=1)
    if ticket_cell is None:
        raise ValueError(f"Ticket {ticket_id} no longer exists. Refresh and try again.")
    row = [values.get(col, "") for col in REQUIRED_HEADERS]
    ws.update(values=[row], range_name=f"A{ticket_cell.row}:{column_letter(len(REQUIRED_HEADERS))}{ticket_cell.row}")


def delete_tickets(ws, ticket_ids):
    """Delete exact ticket rows from bottom to top so row numbers remain valid."""
    wanted = {str(ticket_id) for ticket_id in ticket_ids}
    values = ws.get_all_values()
    rows = [row_number for row_number, row in enumerate(values, start=1) if row and str(row[0]) in wanted]
    for row_number in sorted(rows, reverse=True):
        ws.delete_rows(row_number)


def column_letter(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def append_activity(activity_ws, ticket_id, action, field="", old_value="", new_value="", note=""):
    activity_ws.append_row([
        str(uuid.uuid4()),
        ticket_id,
        action,
        field,
        old_value,
        new_value,
        note,
        datetime.now().isoformat(timespec="seconds"),
        st.session_state.get("user", "dashboard-user"),
    ])


def normalize_text(value):
    return str(value).strip()


def option_index(options, value, default=0):
    text = str(value or "").strip().lower()
    for position, option in enumerate(options):
        if option.lower() == text:
            return position
    return default


def read_whatsapp_upload(raw_bytes, filename):
    """Return the chat text from a .txt export or the _chat.txt inside a .zip."""
    if str(filename).lower().endswith(".zip"):
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".txt")]
            preferred = next((name for name in names if "_chat" in name.lower()), names[0] if names else None)
            return archive.read(preferred).decode("utf-8", errors="replace") if preferred else ""
    return raw_bytes.decode("utf-8", errors="replace")


@st.cache_data(show_spinner=False)
def parse_whatsapp_cached(raw_bytes, filename):
    """Parse an upload once and reuse across reruns (large exports are slow)."""
    return parse_export(read_whatsapp_upload(raw_bytes, filename))


def parse_dt(series_or_value):
    return pd.to_datetime(series_or_value, errors="coerce")


def valid_datetime(value):
    return bool(str(value).strip()) and not pd.isna(parse_dt(value))


def nairobi_input_value(value):
    stamp = pd.to_datetime(value, errors="coerce", utc=True)
    # The date/time widget edits minutes; compare at that precision so merely
    # saving another field does not truncate seconds from an automatic milestone.
    return stamp.tz_convert("Africa/Nairobi").tz_localize(None).floor("min").to_pydatetime() if pd.notna(stamp) else None


def nairobi_timestamp(value):
    return pd.Timestamp(value).tz_localize("Africa/Nairobi").isoformat() if value else ""


def contact_message(view):
    breached_response = int((view["Response SLA"] == "Breached").sum())
    breached_diagnosis = int((view["Diagnosis SLA"] == "Breached").sum())
    breached_resolution = int((view["Closure SLA"] == "Breached").sum())
    return (
        "Reporting dashboard update: "
        f"{len(view)} request(s), {breached_response} response SLA breach(es), "
        f"{breached_diagnosis} diagnosis SLA breach(es), "
        f"and {breached_resolution} closure SLA breach(es). Targets: 30 minutes / 2 hours / 48 hours."
    )


def require_login():
    """Enable a lightweight access gate when a password hash is configured."""
    if not DASHBOARD_PASSWORD_HASH or st.session_state.get("authenticated"):
        return
    render_login_header()
    left, center, right = st.columns([1, 1.15, 1])
    with center, st.form("login_form"):
        password = st.text_input("Password", type="password", placeholder="Enter your dashboard password")
        submitted = st.form_submit_button("Sign in to dashboard", type="primary", width="stretch")
    if submitted:
        supplied_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if hmac.compare_digest(supplied_hash, DASHBOARD_PASSWORD_HASH):
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Incorrect password.")
    st.stop()


@st.cache_resource
def get_user_store():
    configured_url = setting("DATABASE_URL")
    return create_user_store(configured_url or None)


@st.cache_resource
def get_weekly_task_store():
    configured_url = setting("DATABASE_URL")
    return create_weekly_task_store(configured_url or None)


def current_user_from(account):
    return CurrentUser(
        username=account["username"], display_name=account["display_name"],
        department=account["department"], subteam=account.get("subteam", ""),
        role=account.get("role", "member"),
    )


def authenticate(user_store, username, password):
    """Return an account dict for valid credentials, otherwise None."""
    username = str(username or "").strip()
    if not username or not password:
        return None
    if BOOTSTRAP_ADMIN_USER and username.lower() == BOOTSTRAP_ADMIN_USER.lower():
        if BOOTSTRAP_ADMIN_PASSWORD and hmac.compare_digest(str(password), str(BOOTSTRAP_ADMIN_PASSWORD)):
            return {"username": username.lower(), "display_name": "Administrator",
                    "department": GLOBAL_VIEW_DEPARTMENT, "subteam": "", "role": "admin",
                    "must_change_password": False}
        return None
    account = user_store.get(username)
    if account is None or not account.active or not verify_password(password, account.password_hash):
        return None
    return {"username": account.username, "display_name": account.display_name,
            "department": account.department, "subteam": account.subteam or "",
            "role": account.role, "must_change_password": account.must_change_password}


def render_force_password_change(user_store):
    render_login_header()
    st.warning("Your temporary password must be changed before you can continue.")
    left, center, right = st.columns([1, 1.15, 1])
    with center, st.form("force_password_change"):
        new_password = st.text_input("New password", type="password", placeholder="At least 8 characters")
        confirm_password = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Set new password", type="primary", width="stretch")
    if submitted:
        if len(new_password) < 8:
            st.error("Use at least 8 characters.")
        elif new_password != confirm_password:
            st.error("The two passwords do not match.")
        else:
            user_store.set_password(st.session_state["account"]["username"], hash_password(new_password),
                                    must_change_password=False)
            st.session_state["account"]["must_change_password"] = False
            st.success("Password updated.")
            st.rerun()


def require_account_login(user_store):
    """Named-account login with a forced reset for temporary passwords."""
    if st.session_state.get("authenticated") and st.session_state.get("account"):
        if st.session_state["account"].get("must_change_password"):
            render_force_password_change(user_store)
            st.stop()
        return current_user_from(st.session_state["account"])
    render_login_header()
    if not BOOTSTRAP_ADMIN_USER and user_store.count() == 0:
        st.warning(
            "No accounts exist yet. Seed users with scripts/seed_users.py, or set "
            "DASHBOARD_ADMIN_USER and DASHBOARD_ADMIN_PASSWORD for a bootstrap admin."
        )
    left, center, right = st.columns([1, 1.15, 1])
    with center, st.form("account_login_form"):
        username = st.text_input("Username", placeholder="Your username")
        password = st.text_input("Password", type="password", placeholder="Your password")
        submitted = st.form_submit_button("Sign in to dashboard", type="primary", width="stretch")
    if submitted:
        account = authenticate(user_store, username, password)
        if account is None:
            st.error("Incorrect username or password, or the account is inactive.")
            st.stop()
        st.session_state["authenticated"] = True
        st.session_state["account"] = account
        st.session_state["user"] = account["username"]
        st.rerun()
    st.stop()


def normalize_department_columns(frame):
    """Route legacy or blank requests to the IT global view so nothing is hidden."""
    frame["Assigned Department"] = (
        frame.get("Assigned Department", "").fillna("").astype(str).str.strip().replace("", GLOBAL_VIEW_DEPARTMENT)
    )
    frame["Assigned Sub-team"] = frame.get("Assigned Sub-team", "").fillna("").astype(str).str.strip()
    frame["Reporting Department"] = frame.get("Reporting Department", "").fillna("").astype(str).str.strip()
    return frame


# ---- Shared presentation helpers ----
def within_pct(series):
    """Percentage of recorded milestones that met their SLA target."""
    measured = series.isin(["Within SLA", "Breached"])
    if not measured.any():
        return "—"
    return f"{100 * series[measured].eq('Within SLA').mean():.0f}%"


def _weekly_counts(series, status_mask=None):
    stamps = pd.to_datetime(series, errors="coerce", utc=True)
    if status_mask is not None:
        stamps = stamps[status_mask.values]
    stamps = stamps.dropna().dt.tz_convert("Africa/Nairobi").dt.tz_localize(None).dt.to_period("W").dt.start_time
    return stamps.value_counts().sort_index()


def received_resolved_chart(view, weeks=10):
    received = _weekly_counts(view["Reported_dt"])
    resolved = _weekly_counts(view["Closed At"], view["Status"].eq("closed"))
    all_weeks = sorted(set(received.index) | set(resolved.index))[-weeks:]
    order = [pd.Timestamp(w).strftime("%d %b") for w in all_weeks]
    rows = []
    for week in all_weeks:
        label = pd.Timestamp(week).strftime("%d %b")
        rows.append({"Week starting": label, "Series": "Received", "Tickets": int(received.get(week, 0))})
        rows.append({"Week starting": label, "Series": "Resolved", "Tickets": int(resolved.get(week, 0))})
    return alt.Chart(alt.Data(values=rows)).mark_line(point=True).encode(
        x=alt.X("Week starting:N", sort=order, title="Week starting"),
        y=alt.Y("Tickets:Q", title="Tickets", axis=alt.Axis(tickMinStep=1)),
        color=alt.Color("Series:N", scale=alt.Scale(domain=["Received", "Resolved"], range=["#3B82F6", "#10B981"]),
                        legend=alt.Legend(title=None, orient="bottom")),
        tooltip=["Week starting:N", "Series:N", "Tickets:Q"],
    ).properties(height=260).configure_view(strokeWidth=0)


def status_donut(view):
    closed = int(view["Status"].eq("closed").sum())
    values = [{"Status": "Open", "Tickets": len(view) - closed}, {"Status": "Resolved", "Tickets": closed}]
    return alt.Chart(alt.Data(values=values)).mark_arc(innerRadius=60).encode(
        theta=alt.Theta("Tickets:Q"),
        color=alt.Color("Status:N", scale=alt.Scale(domain=["Open", "Resolved"], range=["#3B82F6", "#10B981"]),
                        legend=alt.Legend(title=None, orient="bottom")),
        tooltip=["Status:N", "Tickets:Q"],
    ).properties(height=260).configure_view(strokeWidth=0)


# ---- App ----
ws, activity_ws = get_sheet_handles()
ensure_headers(ws, REQUIRED_HEADERS)
ensure_headers(activity_ws, ACTIVITY_HEADERS)

OPEN_ADMIN = CurrentUser(username="dashboard-user", display_name="Dashboard user",
                         department=GLOBAL_VIEW_DEPARTMENT, role="admin")

if USE_DATABASE:
    user_store = get_user_store()
    # Require named-account login only once auth is set up (accounts seeded or a
    # bootstrap admin configured). Until then the tool stays open as an IT admin,
    # matching its pre-roles default so existing deployments are never locked out.
    if bool(BOOTSTRAP_ADMIN_USER) or user_store.count() > 0:
        current_user = require_account_login(user_store)
    else:
        current_user = OPEN_ADMIN
else:
    # Google Sheets fallback keeps the legacy shared-password gate and treats the
    # single user as an IT admin, matching the tool's pre-roles behaviour.
    require_login()
    current_user = OPEN_ADMIN

is_admin_user = current_user.is_admin  # may manage any request and delete
view_all_user = current_user.can_view_all  # may see every department

render_brand_header()
render_dashboard_hero()

# The workspace card reflects the signed-in user's department so members of every
# department feel at home (IT sees "IT Support", HR sees "HR Support", etc.).
render_sidebar_header(f"{current_user.department} Support")

df = read_df(ws, REQUIRED_HEADERS)

# ---- Normalize main data ----
df["Status"] = df["Status"].astype(str).str.strip().str.lower()
df["Summary"] = df["Summary"].astype(str).str.strip()
df["Priority"] = df["Priority"].astype(str).str.strip()
df["Created"] = df["Created"].astype(str).str.strip()
df["Diagnosed At"] = df["Diagnosed At"].astype(str).str.strip()
df["Resolved At"] = df["Resolved At"].astype(str).str.strip()
df["Updated At"] = df["Updated At"].astype(str).str.strip()

df = normalize_department_columns(enrich_tickets(df, DIAGNOSIS_SLA_HOURS, RESOLUTION_SLA_HOURS))

# Scope every request to what this user may see before any in-page filtering.
scoped_df = visible_tickets(df, department=current_user.department, admin=view_all_user)

# ---- Sidebar identity + filters ----
access_note = "  ·  Admin (all departments)" if is_admin_user else ("  ·  Full view (all departments)" if view_all_user else "")
st.sidebar.caption(
    f"Signed in as **{current_user.display_name}**"
    f"  ·  {current_user.department}"
    + (f" ({current_user.subteam})" if current_user.subteam else "")
    + access_note
)

# Ticket workspace filters by who reported the request (requester type).
WORKSPACES = [ALL_REQUESTERS_OPTION, "Solver", "Solvit Office Team", "External Clients"]
_WORKSPACE_PRETTY = {ALL_REQUESTERS_OPTION: "All tickets", "Solver": "Solver tickets",
                     "Solvit Office Team": "Solvit Office Team", "External Clients": "External clients"}
_requester_kinds = scoped_df.get("Requester Type", "").fillna("").astype(str).str.strip()


def _workspace_label(option):
    count = len(scoped_df) if option == ALL_REQUESTERS_OPTION else int(_requester_kinds.eq(option).sum())
    return f"{_WORKSPACE_PRETTY[option]} ({count})"


workspace = st.sidebar.radio("Ticket workspace", WORKSPACES, format_func=_workspace_label, key="workspace")

# Reporting period narrows everything to requests reported in the window.
_PERIODS = {"All time": None, "Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90, "This year": "year"}
period_label = st.sidebar.selectbox("Reporting period", list(_PERIODS))
_today = pd.Timestamp.now(tz="Africa/Nairobi").date()
if _PERIODS[period_label] == "year":
    period_start, period_end = _today.replace(month=1, day=1), _today
elif isinstance(_PERIODS[period_label], int):
    period_start, period_end = _today - timedelta(days=_PERIODS[period_label]), _today
else:
    period_start, period_end = None, None

status_filter = st.sidebar.selectbox("Request status", ["All statuses"] + STATUSES)

# Users with the global view can scope the whole dashboard to one department;
# department members are already scoped to their own, so this filter is hidden.
if view_all_user:
    department_filter = st.sidebar.selectbox("Department", [ALL_DEPARTMENTS_OPTION] + DEPARTMENTS)
else:
    department_filter = ALL_DEPARTMENTS_OPTION

# The sub-team filter appears when the department in view has sub-teams.
effective_department = department_filter if view_all_user else current_user.department
subteam_options = subteams_for(effective_department) if effective_department != ALL_DEPARTMENTS_OPTION else []
if subteam_options:
    subteam_filter = st.sidebar.selectbox("Sub-team", [ALL_SUBTEAMS_OPTION] + subteam_options)
else:
    subteam_filter = ALL_SUBTEAMS_OPTION

with st.sidebar.expander("More filters"):
    priorities = sorted([p for p in scoped_df["Priority"].dropna().unique() if str(p).strip() != ""])
    priority_filter = st.selectbox("Priority", ["All priorities"] + priorities) if priorities else "All priorities"
    months = sorted([m for m in scoped_df["Created Month"].dropna().unique() if m != "NaT"])
    month_filter = st.selectbox("Created month", ["All months"] + months) if months else "All months"
    agents = sorted({str(value).strip() for value in scoped_df["Assignee"].fillna("") if str(value).strip()})
    owner_filter = st.selectbox("Assigned agent", ["All agents", "Unassigned"] + agents)
    search = st.text_input("Search", placeholder="Support number, Reg No, Job ID, requester, summary, or agent")

render_sidebar_footer()
if st.sidebar.button("Sign out", icon=":material/logout:", key="sidebar_logout"):
    for key in ["authenticated", "account", "user"]:
        st.session_state.pop(key, None)
    st.rerun()

view = filter_requests(
    scoped_df, status_filter, priority_filter, month_filter, owner_filter, search,
    department_filter, subteam_filter, requester_type=workspace,
    period_start=period_start, period_end=period_end,
)


def _live_view():
    """Re-read and filter the data the same way, for the auto-refreshing tabs."""
    refreshed_at = pd.Timestamp.now(tz="UTC")
    fresh = read_df(ws, REQUIRED_HEADERS)
    for field in ["Status", "Summary", "Priority", "Assignee"]:
        fresh[field] = fresh[field].fillna("").astype(str).str.strip()
    fresh["Status"] = fresh["Status"].str.lower()
    live_df = normalize_department_columns(enrich_tickets(fresh, now=refreshed_at))
    live_role = visible_tickets(live_df, department=current_user.department, admin=view_all_user)
    live_view = filter_requests(
        live_role, status_filter, priority_filter, month_filter, owner_filter, search,
        department_filter, subteam_filter, requester_type=workspace,
        period_start=period_start, period_end=period_end,
    )
    return refreshed_at, live_role, live_view


@st.fragment(run_every="10m")
def render_overview():
    st.button("Refresh overview", key="refresh_overview")
    refreshed_at, _live_role, live_view = _live_view()
    closed_mask = live_view["Status"].eq("closed")
    open_df = live_view.loc[~closed_mask]
    overdue = overdue_milestones(open_df).any(axis=1) if len(open_df) else pd.Series(dtype=bool)
    unassigned = open_df["Assignee"].fillna("").astype(str).str.strip().eq("") if len(open_df) else pd.Series(dtype=bool)
    render_kpi_cards([
        ("Tickets in period", len(live_view), "Matches the current filters", "#3B82F6"),
        ("Open", int((~closed_mask).sum()), "Awaiting resolution", "#F59E0B"),
        ("Resolved", int(closed_mask.sum()), "Closed in view", "#10B981"),
        ("Overdue", int(overdue.sum()) if len(open_df) else 0, "Past an SLA target", "#ff353e"),
        ("Unassigned", int(unassigned.sum()) if len(open_df) else 0, "No owner yet", "#8B5CF6"),
    ])
    render_kpi_cards([
        ("Response within 30 min", within_pct(live_view["Response SLA"]), "Of recorded first responses", "#3B82F6"),
        ("Resolution within 48 h", within_pct(live_view["Closure SLA"]), "Of recorded closures", "#10B981"),
        ("Average resolution", format_duration(live_view.loc[closed_mask, "Closure Hours"].mean()), "Reported to closed", "#8B5CF6"),
        ("Needs attention", int((overdue | unassigned).sum()) if len(open_df) else 0, "Overdue or unassigned", "#ff353e"),
    ])
    st.divider()
    if live_view.empty:
        st.info("No requests match the current filters.")
    else:
        left, right = st.columns([1.6, 1])
        with left:
            st.markdown("#### Requests received and resolved")
            st.altair_chart(received_resolved_chart(live_view), width="stretch")
        with right:
            st.markdown("#### Ticket status")
            st.altair_chart(status_donut(live_view), width="stretch")
    st.caption(f"Auto-refreshes every 10 minutes. Last updated {refreshed_at.tz_convert('Africa/Nairobi'):%H:%M:%S} Nairobi time.")


@st.fragment(run_every="10m")
def render_live_reporting():
    st.button("Refresh analytics now", key="refresh_analytics")
    refreshed_at, live_role, live_view = _live_view()
    # The weekly comparison ignores the in-page filters but keeps the department scope.
    weekly_scope = filter_requests(live_role, department=department_filter, subteam=subteam_filter)
    st.caption(f"Analytics refresh every 10 minutes. Last updated {refreshed_at.tz_convert('Africa/Nairobi'):%H:%M:%S} Nairobi time.")
    # ---- Summary metrics ----
    closed_requests = live_view["Status"].eq("closed")
    open_requests = live_view.loc[~closed_requests]
    overdues = overdue_milestones(open_requests).any(axis=1) | open_requests["Assignee"].fillna("").str.strip().eq("")
    render_kpi_cards([
        ("Open requests", len(open_requests), "Includes work awaiting closure", "#3B82F6"),
        ("Needs attention", int(overdues.sum()), "Overdue or awaiting an owner", "#ff353e"),
        ("Closed requests", int(closed_requests.sum()), "Completed in the current filters", "#10B981"),
        ("Average closure TAT", format_duration(live_view.loc[closed_requests, "Closure Hours"].mean()), "Reported to closed · target 48 hours", "#8B5CF6"),
    ])

    st.divider()

    # ---- Search, export, and contact actions ----
    action_left, action_middle, action_right = st.columns([1, 1, 1])
    with action_left:
        st.caption("Export or share the currently filtered report.")

    export_columns = [field for field in REQUIRED_HEADERS if field != "Solver ID"] + ["Response Hours", "Diagnosis Hours", "Closure Hours", "Response SLA", "Diagnosis SLA", "Closure SLA"]
    with action_middle:
        st.download_button(
            "Download filtered CSV",
            data=live_view[export_columns].to_csv(index=False).encode("utf-8"),
            file_name=f"ticket-report-{datetime.now():%Y-%m-%d}.csv",
            mime="text/csv",
            width="stretch",
        )

    message = contact_message(live_view)
    with action_right:
        if SUPPORT_EMAIL:
            st.link_button(
                "Email report summary",
                f"mailto:{SUPPORT_EMAIL}?subject={quote('Ticket reporting update')}&body={quote(message)}",
                width="stretch",
            )
        if SUPPORT_WHATSAPP:
            st.link_button(
                "Send via WhatsApp",
                f"https://wa.me/{SUPPORT_WHATSAPP}?text={quote(message)}",
                width="stretch",
            )
        if not SUPPORT_EMAIL and not SUPPORT_WHATSAPP:
            st.caption("Add SUPPORT_EMAIL or SUPPORT_WHATSAPP to secrets to enable sharing.")

    st.divider()

    # ---- Dashboard charts ----
    render_reporting_views(live_view)
    st.divider()

    if view_all_user:
        render_department_breakdown(live_role)
        st.divider()

    render_weekly_report(weekly_scope, refreshed_at)


# ---- Tabbed layout ----
tab_overview, tab_tickets, tab_reports, tab_weekly, tab_admin = st.tabs(
    ["Overview", "Tickets", "Reports", "Weekly tasks", "Admin"]
)

with tab_overview:
    render_overview()

with tab_reports:
    render_live_reporting()

with tab_weekly:
    # Actions from the Weekly Manager Tracker, due at the Thursday review meeting.
    # Tracked separately from support requests so they never affect SLA metrics.
    st.subheader("Weekly tasks")
    st.caption(
        "Actions from the Weekly Manager Tracker, due at the Thursday review meeting. "
        "Tracked separately from support requests, so they never affect the SLA metrics."
    )
    if not USE_DATABASE:
        st.info("Weekly tasks require the PostgreSQL database backend.")
    else:
        weekly_store = get_weekly_task_store()
        if view_all_user:
            weekly_graph = GraphConfig.from_settings(setting)
            weekly_ready = weekly_graph.is_configured() and bool(TRACKER_SHARE_URL)
            backfill = st.checkbox(
                "Import all weeks (one-time backfill)", key="weekly_backfill",
                help="Fetch every filled week from the tracker, not just the current one. "
                     "Use this once to load history; after that the weekly sync keeps up.",
            )
            sync_col, hint_col = st.columns([1, 2])
            sync_label = "Import all weeks" if backfill else "Sync weekly tasks"
            if sync_col.button(sync_label, disabled=not weekly_ready, key="sync_weekly"):
                try:
                    with st.spinner("Reading the tracker and updating weekly tasks…"):
                        weekly_summary = sync_weekly_tasks(
                            weekly_store, graph_config=weekly_graph,
                            share_url=TRACKER_SHARE_URL, worksheet=TRACKER_WORKSHEET,
                            all_weeks=backfill,
                        )
                    if weekly_summary["tasks"]:
                        scope = (
                            f"{weekly_summary['weeks']} week(s)" if backfill
                            else f"{weekly_summary['week']} (due {weekly_summary['due']})"
                        )
                        st.success(f"{scope}: {weekly_summary['created']} new, {weekly_summary['updated']} updated.")
                        st.rerun()
                    else:
                        st.error(
                            "Nothing to fetch: the tracker has no tasks filled in "
                            + ("for any week yet." if backfill else "for this week yet.")
                        )
                except Exception as error:
                    st.error(f"Sync failed: {error}")
            if not weekly_ready:
                hint_col.caption("Set the MS_* Graph secrets and TRACKER_SHARE_URL to enable live sync.")

        all_weekly = weekly_store.list()
        if not all_weekly:
            st.caption("No weekly tasks yet. An admin can sync them from the tracker.")
        else:
            # The store returns every week, newest first; let the user browse any of them.
            week_labels = {}
            for task in all_weekly:
                week_labels.setdefault(task["week_start"], task["week_label"] or task["week_start"])
            week_options = list(week_labels)
            picked_week = st.selectbox(
                "Week", week_options, format_func=lambda w: week_labels[w], key="weekly_week_pick",
            )
            week_tasks = [task for task in all_weekly if task["week_start"] == picked_week]
            visible_tasks = [
                task for task in week_tasks
                if view_all_user or normalize_department(task["department"]) == current_user.department
            ]
            label = week_tasks[0]["week_label"] or picked_week
            due = week_tasks[0]["due_at"] or ""
            done = sum(1 for task in visible_tasks if task["status"] == WEEKLY_STATUSES[-1])
            st.caption(f"{label}  ·  due {due}  ·  {done}/{len(visible_tasks)} complete in your view")
            if not visible_tasks:
                st.caption("No weekly tasks routed to your department this week.")
            else:
                # Weekly tasks get their own analysis, kept apart from ticket SLA metrics.
                stats = completion_stats(visible_tasks)
                render_kpi_cards([
                    ("Completion rate", f"{stats['rate']:.0f}%", "Complete ÷ tasks this week", "#10B981"),
                    ("Complete", stats["complete"], f"of {stats['total']} tasks", "#3B82F6"),
                    ("Off track", stats["off_track"], "Flagged at risk", "#ff353e"),
                    ("Not started", stats["not_started"], "Yet to begin", "#F59E0B"),
                ])
                visible_all_weekly = [
                    task for task in all_weekly
                    if view_all_user or normalize_department(task["department"]) == current_user.department
                ]
                analysis_cols = st.columns(2)
                with analysis_cols[0]:
                    if view_all_user:
                        st.markdown("###### Completion by department")
                        dep_data = [
                            {"Department": row["department"], "Completion %": round(row["rate"], 1),
                             "Complete": row["complete"], "Total": row["total"]}
                            for row in completion_by_department(week_tasks)
                        ]
                        st.altair_chart(
                            alt.Chart(alt.Data(values=dep_data)).mark_bar(cornerRadiusEnd=4).encode(
                                x=alt.X("Completion %:Q", scale=alt.Scale(domain=[0, 100])),
                                y=alt.Y("Department:N", sort="-x", title=None),
                                color=alt.value("#3B82F6"),
                                tooltip=["Department:N", "Completion %:Q", "Complete:Q", "Total:Q"],
                            ).properties(height=max(140, 34 * len(dep_data))).configure_view(strokeWidth=0),
                            width="stretch",
                        )
                    else:
                        st.markdown("###### Status mix")
                        mix = [
                            {"Status": status, "Tasks": sum(
                                1 for task in visible_tasks
                                if (task["status"] if task["status"] in WEEKLY_STATUSES else WEEKLY_STATUSES[0]) == status)}
                            for status in WEEKLY_STATUSES
                        ]
                        st.altair_chart(
                            alt.Chart(alt.Data(values=mix)).mark_arc(innerRadius=55).encode(
                                theta="Tasks:Q",
                                color=alt.Color("Status:N", scale=alt.Scale(
                                    domain=WEEKLY_STATUSES, range=["#F59E0B", "#3B82F6", "#ff353e", "#10B981"]),
                                    legend=alt.Legend(title=None, orient="bottom")),
                                tooltip=["Status:N", "Tasks:Q"],
                            ).properties(height=240).configure_view(strokeWidth=0),
                            width="stretch",
                        )
                with analysis_cols[1]:
                    st.markdown("###### Completion rate over weeks")
                    trend = completion_by_week(visible_all_weekly)
                    if len(trend) < 2:
                        st.caption("Backfill more weeks to see a trend.")
                    else:
                        order = [row["week_label"] for row in trend]
                        trend_data = [
                            {"Week": row["week_label"], "Completion %": round(row["rate"], 1),
                             "Complete": row["complete"], "Total": row["total"]}
                            for row in trend
                        ]
                        st.altair_chart(
                            alt.Chart(alt.Data(values=trend_data)).mark_line(point=True).encode(
                                x=alt.X("Week:N", sort=order, title=None),
                                y=alt.Y("Completion %:Q", scale=alt.Scale(domain=[0, 100])),
                                color=alt.value("#10B981"),
                                tooltip=["Week:N", "Completion %:Q", "Complete:Q", "Total:Q"],
                            ).properties(height=240).configure_view(strokeWidth=0),
                            width="stretch",
                        )
                st.divider()
            for task in visible_tasks:
                with st.container(border=True):
                    heading = f"**{task['kpi_area']}**  ·  {task['department'] or 'Unrouted'}"
                    if task["subteam"]:
                        heading += f" / {task['subteam']}"
                    st.markdown(heading)
                    st.write(task["task"])
                    if task["comments"]:
                        st.caption(f"Notes from the tracker: {task['comments']}")
                    can_edit_task = view_all_user or normalize_department(task["department"]) == current_user.department
                    status_value = task["status"] if task["status"] in WEEKLY_STATUSES else WEEKLY_STATUSES[0]
                    new_status = st.selectbox(
                        "Status", WEEKLY_STATUSES, index=WEEKLY_STATUSES.index(status_value),
                        key=f"weekly_status_{task['task_id']}", disabled=not can_edit_task,
                    )
                    if can_edit_task and new_status != task["status"]:
                        weekly_store.set_status(task["task_id"], new_status)
                        st.rerun()

def close_ticket_intake():
    st.session_state.pop("ticket_intake_open", None)
    st.session_state["ticket_intake_version"] = st.session_state.get("ticket_intake_version", 0) + 1


@st.dialog("Add new ticket", width="medium", on_dismiss=close_ticket_intake)
def add_ticket_dialog():
    key = f"ticket_intake_{st.session_state.get('ticket_intake_version', 0)}"
    requester = st.selectbox("Who needs support?", WORKSPACES[1:], index=None, key=f"{key}_requester")
    default_department = effective_department if effective_department in DEPARTMENTS else current_user.department
    assign_department = st.selectbox(
        "Assign to department", DEPARTMENTS,
        index=DEPARTMENTS.index(default_department) if default_department in DEPARTMENTS else 0,
        key=f"{key}_department",
    )
    subteams = subteams_for(assign_department)
    with st.form(key, enter_to_submit=False):
        subteam = st.selectbox("Assign to sub-team", subteams, index=None) if subteams else ""
        channel = st.selectbox("Channel", ["Email", "Call", "WhatsApp", "SMS", "Other"], index=None)
        left, right = st.columns(2)
        reg_no = left.text_input("Reg No").strip().upper()
        request_id = right.text_input("Job Request ID").strip()
        if requester == "Solver":
            st.caption("Enter the Reg No, Job Request ID, or both.")
        office_department = st.text_input("Office department (optional)").strip() if requester == "Solvit Office Team" else ""
        company = st.text_input("Company or contact (optional)").strip() if requester == "External Clients" else ""
        summary = st.text_input("Issue summary").strip()
        st.caption("Use the actual date and time in Nairobi, even when entering a ticket later.")
        left, right = st.columns(2)
        reported = left.datetime_input("Reported at", value=None)
        resolved = right.datetime_input("Resolved at (optional)", value=None)
        resolution_summary = st.text_area("Resolution summary", placeholder="Briefly describe what you did to fix the issue.").strip()
        submitted = st.form_submit_button("Save", type="primary", width="stretch")

    if not submitted:
        return
    now = pd.Timestamp.now(tz="Africa/Nairobi")
    reported_stamp = nairobi_timestamp(reported)
    resolved_stamp = nairobi_timestamp(resolved)
    errors = []
    if not requester or not channel or not summary or not reported:
        errors.append("Choose a requester type and channel, and enter an issue summary and reported time.")
    if requester == "Solver" and not (reg_no or request_id):
        errors.append("Enter a Reg No or Job Request ID.")
    if subteams and not subteam:
        errors.append(f"Select a {assign_department} sub-team.")
    if any(value and pd.Timestamp(value) > now for value in (reported_stamp, resolved_stamp)):
        errors.append("Reported and resolved times cannot be in the future.")
    if resolved and not resolution_summary:
        errors.append("Enter a resolution summary when saving a resolved ticket.")
    if reported and resolved and resolved < reported:
        errors.append("Resolved at must be at or after Reported at.")
    if errors:
        for error in errors:
            st.error(error)
        return

    ticket_id = str(uuid.uuid4())
    append_ticket(ws, {
        "Ticket ID": ticket_id,
        "Support Request Number": f"SUP-{now:%Y%m%d}-{ticket_id[:6].upper()}",
        "Summary": summary,
        "Status": "closed" if resolved else "to do",
        "Created": now.isoformat(),
        "Updated At": now.isoformat(),
        "Reported At": reported_stamp,
        "Resolved At": resolved_stamp,
        "Resolution Summary": resolution_summary,
        "Closed At": resolved_stamp,
        "Requester Type": requester,
        "Requester Name": company,
        "Channel": channel,
        "Job Request ID": request_id,
        "Reg No": reg_no,
        "Office Department": office_department,
        "Assigned Department": assign_department,
        "Assigned Sub-team": subteam or "",
        "Reporting Department": current_user.department,
    })
    active_card = st.session_state.get("ticket_card_filter", "Tickets")
    if active_card == ("Open" if resolved else "Resolved"):
        st.session_state["ticket_card_filter"] = "Tickets"
    st.session_state["new_ticket_saved"] = ticket_id
    close_ticket_intake()
    st.rerun()


def render_ticket_deletion(ticket_view):
    colA, colB = st.columns([1, 1])
    with colA:
        delete_ids = st.multiselect(
            "Delete tickets (select by Summary)",
            options=ticket_view["Ticket ID"].tolist(),
            format_func=lambda tid: ticket_view.loc[ticket_view["Ticket ID"] == tid, "Summary"].values[0],
        )
    with colB:
        delete_note = st.text_input("Delete note (optional)", placeholder="Why is this ticket being deleted?")

    if st.button("Delete selected"):
        if not delete_ids:
            st.warning("Select at least one ticket to delete.")
            st.stop()
        base = read_df(ws, REQUIRED_HEADERS)
        base = pd.DataFrame(base)
        doomed = base[base["Ticket ID"].isin(delete_ids)].copy()
        for _, row in doomed.iterrows():
            append_activity(
                activity_ws,
                ticket_id=row["Ticket ID"],
                action="ticket_deleted",
                field="Status",
                old_value=row.get("Status", ""),
                new_value="",
                note=delete_note.strip(),
            )
        delete_tickets(ws, delete_ids)
        st.success(f"Deleted {len(delete_ids)} ticket(s).")
        st.rerun()



def close_ticket_editor():
    st.session_state.pop("editing_ticket_id", None)
    st.session_state.pop("editing_ticket_revision", None)
    st.session_state["ticket_edit_version"] = st.session_state.get("ticket_edit_version", 0) + 1


@st.dialog("Ticket details", width="medium", on_dismiss=close_ticket_editor)
def edit_ticket_dialog(selected, ticket_label):
    selected_ticket_id = selected["Ticket ID"]
    form_key = f"edit_ticket_{selected_ticket_id}_{selected['Updated At']}_{st.session_state.get('ticket_edit_version', 0)}"
    st.caption(ticket_label)
    can_manage_selected = can_manage(
        department=current_user.department, admin=is_admin_user, ticket_department=selected["Assigned Department"]
    )
    if not can_manage_selected:
        st.info("This request is owned by another department. You have view-only access and can add a note below.")

    with st.expander("Department routing"):
        current_dept = normalize_department(selected["Assigned Department"]) or GLOBAL_VIEW_DEPARTMENT
        new_department = st.selectbox(
            "Assigned department", DEPARTMENTS, index=DEPARTMENTS.index(current_dept),
            key=f"{form_key}_department", disabled=not can_manage_selected,
            help="Reassign this request to another department. Choosing a department with sub-teams requires selecting one below.",
        )

    with st.form(form_key, enter_to_submit=False):
        issue = st.text_input("Issue summary", value=normalize_text(selected["Summary"]))
        references = st.columns(2)
        reg_no = references[0].text_input("Reg No", value=normalize_text(selected["Reg No"]))
        job_id = references[1].text_input("Job Request ID", value=normalize_text(selected["Job Request ID"]))
        channel = st.text_input("Channel", value=normalize_text(selected["Channel"]))
        corrected_reported_at = st.datetime_input(
            "Reported at (Nairobi time)", value=nairobi_input_value(reported_time(selected)),
            help="Correct the actual reporting time. This recalculates SLA deadlines and leaves the dashboard entry timestamp unchanged.",
        )
        status_value = normalize_text(selected["Status"]).lower()
        new_status = st.selectbox(
            "Status",
            options=STATUSES,
            index=STATUSES.index(status_value) if status_value in STATUSES else 0,
            help="Resolved requests can move directly to Closed. Add a resolution summary before saving.",
        )
        resolved_at = st.datetime_input(
            "Resolved at (Nairobi time)", value=nairobi_input_value(selected["Closed At"] or selected["Resolved At"]),
        )
        resolution_summary = st.text_area(
            "Resolution summary",
            value=normalize_text(selected["Resolution Summary"]),
            placeholder="What was done to resolve or progress this request?",
        )
        with st.expander("Assignment, callback and SLA details"):
            update_left, update_right = st.columns(2)
            with update_left:
                priority_value = normalize_text(selected["Priority"])
                priority_options = ["Low", "Medium", "High", "Urgent"]
                if priority_value not in priority_options:
                    priority_options.insert(0, priority_value)
                new_priority = st.selectbox(
                    "Priority",
                    options=priority_options,
                    index=priority_options.index(priority_value),
                    format_func=lambda value: value or "Not set",
                )
                new_assignee = st.text_input("Assigned support agent", value=normalize_text(selected["Assignee"]))
            with update_right:
                callback_value = normalize_text(selected["Callback Required"])
                new_callback_required = st.checkbox("Callback required", value=callback_value == "Yes")
                new_callback_deadline = st.text_input(
                    "Callback deadline",
                    value=normalize_text(selected["Callback Deadline"]),
                    placeholder="YYYY-MM-DD HH:MM",
                    disabled=not new_callback_required,
                )
                callback_done = st.checkbox(
                    "Callback completed",
                    value=bool(normalize_text(selected["Callback Completed At"])),
                )

            route_subteams = subteams_for(new_department)
            if route_subteams:
                current_subteam = clean_subteam(new_department, selected["Assigned Sub-team"])
                route_options = ["— Select sub-team —"] + route_subteams
                route_choice = st.selectbox(
                    f"{new_department} sub-team *", route_options,
                    index=route_options.index(current_subteam) if current_subteam in route_options else 0,
                    help="Required for this department. Pick the exact team that owns this request.",
                )
                new_subteam = "" if route_choice.startswith("—") else route_choice
            else:
                new_subteam = ""

            st.caption("Record when you first responded and understood the problem. Use Nairobi time; leave unknown times blank.")
            response_column, diagnosis_column = st.columns(2)
            with response_column:
                first_response_at = st.datetime_input(
                    "First response sent at", value=nairobi_input_value(selected["First Response At"]),
                )
                mark_responded = st.form_submit_button(
                    "Mark responded",
                    disabled=bool(normalize_text(selected["First Response At"])) or selected["Status"] == "closed" or not can_manage_selected,
                    help="Record the first response as now and save the current form edits. Use only after responding to the requester.",
                )
            with diagnosis_column:
                diagnosed_at = st.datetime_input(
                    "Problem diagnosed at", value=nairobi_input_value(selected["Diagnosed At"]),
                )
                mark_diagnosed = st.form_submit_button(
                    "Mark diagnosed",
                    disabled=bool(normalize_text(selected["Diagnosed At"])) or selected["Status"] == "closed" or not can_manage_selected,
                    help="Record diagnosis as now and save the current form edits. A To do request moves to Diagnosed.",
                )
            st.caption("Milestone buttons record the time now and save your form edits. Use the date fields to correct earlier times.")
            update_note = st.text_area("Update note", placeholder="Add context for this change")
        save_edits = st.form_submit_button("Save request update", type="primary", disabled=not can_manage_selected)

    if save_edits or mark_responded or mark_diagnosed:
        if not can_manage_selected:
            st.error("You do not have permission to edit this request.")
            return
        if subteams_for(new_department) and not clean_subteam(new_department, new_subteam):
            st.error(f"Select a {new_department} sub-team before saving.")
            return
        base = read_df(ws, REQUIRED_HEADERS)
        base = pd.DataFrame(base)
        for col in REQUIRED_HEADERS:
            if col not in base.columns:
                base[col] = ""

        if base["Ticket ID"].astype(str).duplicated().any():
            st.error("Duplicate Ticket IDs were found. Resolve them before editing.")
            return

        base_idx = base.set_index("Ticket ID", drop=False)
        tid = selected_ticket_id
        if tid not in base_idx.index:
            st.error("This request no longer exists. Refresh to select another request.")
            return
        current = {col: normalize_text(base_idx.loc[tid, col]) for col in REQUIRED_HEADERS}
        if current["Updated At"] != st.session_state.get("editing_ticket_revision", normalize_text(selected["Updated At"])):
            st.error("This ticket changed while you were editing. Close it and reopen it before saving.")
            return
        if not issue.strip():
            st.error("Enter an issue summary.")
            return
        # Treat a legacy blank department as its normalized default so simply
        # opening and saving a request does not log a phantom routing change.
        current["Assigned Department"] = normalize_department(current["Assigned Department"]) or GLOBAL_VIEW_DEPARTMENT
        proposed = current.copy()
        for field, value in {
            "Summary": issue.strip(), "Reg No": reg_no.strip(), "Job Request ID": job_id.strip(),
            "Channel": channel.strip(),
        }.items():
            if value != normalize_text(selected[field]):
                proposed[field] = value.upper() if field == "Reg No" else value
        resolution_changed = resolved_at != nairobi_input_value(selected["Closed At"] or selected["Resolved At"])
        if resolution_changed:
            proposed["Resolved At"] = nairobi_timestamp(resolved_at)
            if new_status == "closed":
                proposed["Closed At"] = proposed["Resolved At"]
        if corrected_reported_at != nairobi_input_value(reported_time(selected)):
            if corrected_reported_at is None:
                st.error("Set the date and time the request was reported.")
                return
            proposed["Reported At"] = nairobi_timestamp(corrected_reported_at)
        for field, entered in [("First Response At", first_response_at), ("Diagnosed At", diagnosed_at)]:
            # Preserve the stored timestamp unless the user actually changes it.
            if entered != nairobi_input_value(selected[field]):
                proposed[field] = nairobi_timestamp(entered)
        proposed.update({
            "Status": new_status,
            "Priority": new_priority,
            "Assignee": new_assignee.strip(),
            "Callback Required": current["Callback Required"] if new_callback_required == (callback_value == "Yes") else ("Yes" if new_callback_required else "No"),
            "Callback Deadline": "" if not new_callback_required and callback_value == "Yes" else new_callback_deadline.strip(),
            "Callback Completed At": (
                current["Callback Completed At"] or datetime.now().astimezone().isoformat(timespec="seconds")
            ) if callback_done else "",
            "Resolution Summary": resolution_summary.strip(),
            "Assigned Department": new_department,
            "Assigned Sub-team": clean_subteam(new_department, new_subteam),
        })
        current["Status"] = current["Status"].lower()
        now_stamp = datetime.now().astimezone().isoformat()
        reporting_changed = proposed["Reported At"] != current["Reported At"]
        reported_stamp = pd.to_datetime(reported_time(proposed), errors="coerce", utc=True)
        if reporting_changed and (pd.isna(reported_stamp) or reported_stamp > pd.Timestamp.now(tz="UTC") or reported_stamp > pd.to_datetime(current["Created"], utc=True)):
            st.error("Reporting time must not be later than the dashboard entry time or now.")
            return

        if mark_responded or mark_diagnosed:
            if current["Status"] == "closed":
                st.error("This request is already closed. Use the date fields to correct its recorded times.")
                return
            field = "First Response At" if mark_responded else "Diagnosed At"
            proposed[field] = current[field] or now_stamp
            if mark_diagnosed and current["Status"] == "to do" and proposed["Status"] == "to do":
                proposed["Status"] = "diagnosed"

        for field in ["First Response At", "Diagnosed At", "Resolved At", "Closed At"]:
            if (proposed[field] != current[field] or reporting_changed or resolution_changed) and proposed[field]:
                timestamp = pd.to_datetime(proposed[field], utc=True)
                received = reported_stamp
                closed = pd.to_datetime(proposed["Closed At"], errors="coerce", utc=True)
                if pd.isna(received) or timestamp < received or timestamp > pd.Timestamp.now(tz="UTC"):
                    st.error(f"{field} must be between when the request was reported and now.")
                    return
                if proposed["Status"] == "closed" and pd.notna(closed) and timestamp > closed:
                    st.error(f"{field} cannot be after request closure.")
                    return

        if new_callback_required and new_callback_deadline and not valid_datetime(new_callback_deadline):
            st.error("Callback deadline must use a valid date and time.")
            return
        if current["Status"] != proposed["Status"]:
            if proposed["Status"] == "closed" and not proposed["Resolution Summary"]:
                st.error("Add a resolution summary before closing this request.")
                return
            if not can_transition(current["Status"], proposed["Status"]):
                st.error(
                    f"This request cannot move directly from {current['Status']} "
                    f"to {proposed['Status']}. Follow the defined workflow."
                )
                return
            if proposed["Status"] in ["diagnosed", "in progress", "qa testing", "deployed"] and not proposed["Diagnosed At"]:
                proposed["Diagnosed At"] = now_stamp
            if proposed["Status"] in ["deployed", "closed"] and not proposed["Resolved At"]:
                proposed["Resolved At"] = now_stamp
            if proposed["Status"] == "closed":
                proposed["Closed At"] = nairobi_timestamp(resolved_at) or now_stamp
            if current["Status"] == "closed" and proposed["Status"] != "closed":
                proposed["Closed At"] = ""

        changed_fields = [
            field for field in REQUIRED_HEADERS
            if field not in ["Ticket ID", "Updated At"] and current[field] != proposed[field]
        ]
        if not changed_fields:
            st.info("No changes to save.")
            return

        proposed["Updated At"] = now_stamp
        update_ticket(ws, tid, proposed)
        for field in changed_fields:
            append_activity(
                activity_ws,
                ticket_id=tid,
                action="status_changed" if field == "Status" else "field_edited",
                field=field,
                old_value=current[field],
                new_value=proposed[field],
                note=update_note.strip(),
            )

        st.session_state["editing_ticket_revision"] = now_stamp
        st.toast("Support request updated.")
        st.rerun()

    if not can_manage_selected:
        with st.form("viewer_note_form", clear_on_submit=True):
            viewer_note = st.text_area("Add a note", placeholder="Add context or a question for the owning department")
            note_submitted = st.form_submit_button("Add note")
        if note_submitted and viewer_note.strip():
            append_activity(activity_ws, selected_ticket_id, "note_added", "Note", "", "", viewer_note.strip())
            st.success("Note added.")
            st.rerun()

    with st.expander("Ticket history"):
        activity_df = read_df(activity_ws, ACTIVITY_HEADERS)
        history = request_history(activity_df, selected_ticket_id)
        for entry in history:
            stamp = pd.to_datetime(entry["timestamp"], errors="coerce", utc=True)
            if pd.notna(stamp):
                stamp = stamp.tz_convert("Africa/Nairobi")
            when = stamp.strftime("%d %b %Y, %H:%M") if pd.notna(stamp) else "Date unavailable"
            with st.container(border=True):
                st.markdown(f"**{entry['title']}**")
                st.caption(when)
                for detail in entry["details"]:
                    st.text(detail)
        if not history:
            st.caption("No updates recorded for this request yet.")


with tab_tickets:
    if st.button("Add new", type="primary", icon=":material/add:"):
        close_ticket_editor()
        st.session_state["ticket_intake_open"] = True
    if st.session_state.get("ticket_intake_open"):
        add_ticket_dialog()
    saved_ticket = st.session_state.pop("new_ticket_saved", None)
    if saved_ticket:
        st.success("Ticket saved.")
        if not view["Ticket ID"].astype(str).eq(saved_ticket).any():
            st.info("The ticket is outside this view. Check the department, requester, date and status filters.")

    ticket_ids = df.sort_values(["Created_dt", "Ticket ID"], na_position="first")["Ticket ID"]
    ticket_labels = {ticket_id: f"T-{number:03d}" for number, ticket_id in enumerate(ticket_ids, start=1)}
    closed = view["Status"].eq("closed")
    active_card = st.session_state.get("ticket_card_filter", "Tickets")

    def filter_ticket_cards(card):
        if card != st.session_state.get("ticket_card_filter", "Tickets"):
            close_ticket_editor()
            st.session_state["ticket_card_filter"] = card

    with st.container(key="ticket_cards"):
        columns = st.columns(3)
        cards = [("Tickets", len(view)), ("Open", int((~closed).sum())), ("Resolved", int(closed.sum()))]
        for column, (card, count) in zip(columns, cards):
            column.button(f"{card}  \n**{count:,}**", key=f"ticket_card_{card.lower()}",
                          type="primary" if active_card == card else "secondary", width="stretch",
                          on_click=filter_ticket_cards, args=(card,),
                          help=f"Show {'all tickets' if card == 'Tickets' else card.lower() + ' tickets'}")

    if active_card == "Open":
        editor_df = view.loc[~closed]
    elif active_card == "Resolved":
        editor_df = view.loc[closed]
    else:
        editor_df = view

    if editor_df.empty:
        st.info("No support requests match the current filters.")
    else:
        display = pd.DataFrame({
            "Ticket": editor_df["Ticket ID"].map(ticket_labels),
            "Requester type": editor_df["Requester Type"].astype(str).str.strip(),
            "Department": editor_df["Assigned Department"].astype(str).str.strip(),
            "Issue": editor_df["Summary"].astype(str).str.strip(),
            "Reg No / Request ID": editor_df.apply(
                lambda row: " / ".join(
                    value for field in ("Reg No", "Job Request ID")
                    if (value := normalize_text(row[field]))
                ), axis=1,
            ),
            "Status": editor_df["Status"].astype(str).str.capitalize(),
            "Reported": pd.to_datetime(editor_df["Reported_dt"], errors="coerce", utc=True).dt.tz_convert("Africa/Nairobi").dt.strftime("%d %b %Y"),
        })
        st.caption("Select a ticket to view or edit it.")
        table_key = f"ticket_table_{st.session_state.get('ticket_edit_version', 0)}"

        def select_ticket():
            selection = st.session_state[table_key].selection
            if selection.cells:
                position = selection.cells[0][0]
            elif selection.rows:
                position = selection.rows[0]
            else:
                return
            ticket = editor_df.iloc[position]
            st.session_state["editing_ticket_id"] = ticket["Ticket ID"]
            st.session_state["editing_ticket_revision"] = normalize_text(ticket["Updated At"])

        st.dataframe(display, width="stretch", hide_index=True, key=table_key,
                     selection_mode=["single-row", "single-cell"], on_select=select_ticket)

    editing_id = st.session_state.get("editing_ticket_id")
    if editing_id is not None and not st.session_state.get("ticket_intake_open"):
        matches = scoped_df.loc[scoped_df["Ticket ID"].eq(editing_id)]
        if matches.empty:
            close_ticket_editor()
            st.warning("This ticket is no longer available.")
        else:
            edit_ticket_dialog(matches.iloc[0], ticket_labels[editing_id])

with tab_admin:
    if can_delete(admin=is_admin_user) and not view.empty:
        with st.expander("Delete tickets"):
            render_ticket_deletion(view)

    # ---- WhatsApp intake ----
    if USE_DATABASE:
        # Reuse the connection pool without caching a store instance across app updates.
        draft_store = DraftStore(ws.session_factory)
        with st.expander("Import from WhatsApp"):
            st.caption(
                "Upload an exported WhatsApp chat (.txt or .zip), choose a date range, and scan it. "
                "Genuine issues (complaints, app misbehaviour, improvement suggestions) become draft "
                "requests you review below. Routine chatter (approvals, dispatch, logbooks) is ignored. "
                + ("AI extraction is on." if OPENAI_API_KEY else "No OpenAI key set, so a keyword fallback is used (lower quality).")
            )
            wa_upload = st.file_uploader("WhatsApp chat export", type=["txt", "zip"], key="whatsapp_import")
            if wa_upload is not None:
                messages = parse_whatsapp_cached(wa_upload.getvalue(), wa_upload.name)
                convo = [m for m in messages if not m["system"] and m["sender"]]
                stamps = [s for s in (parse_timestamp(m["timestamp"]) for m in convo if m["timestamp"]) if pd.notna(s)]
                if not stamps:
                    st.warning("No dated messages were found. Export the chat without media and try again.")
                else:
                    min_date, max_date = min(stamps).date(), max(stamps).date()
                    st.caption(f"Chat spans {min_date:%d %b %Y} to {max_date:%d %b %Y} ({len(convo)} messages).")
                    default_start = max(min_date, max_date - timedelta(days=7))
                    range_left, range_right = st.columns(2)
                    start_date = range_left.date_input("From", value=default_start, min_value=min_date, max_value=max_date, key="wa_from")
                    end_date = range_right.date_input("To", value=max_date, min_value=min_date, max_value=max_date, key="wa_to")
                    if start_date > end_date:
                        st.error("The 'From' date must be on or before the 'To' date.")
                    else:
                        windowed = [
                            m for m in convo
                            if (ts := parse_timestamp(m["timestamp"])) is not None and pd.notna(ts)
                            and start_date <= ts.date() <= end_date
                        ]
                        st.caption(f"{len(windowed)} messages in the selected range.")
                        if len(windowed) > 3000:
                            st.warning("That is a large range. Narrow the dates to keep the scan fast and within API limits.")
                        if st.button("Scan range for issues", key="scan_whatsapp", disabled=not windowed):
                            with st.spinner("Reading messages and drafting issues…"):
                                issues = extract_issues(
                                    windowed, categories=INTAKE_CATEGORIES,
                                    api_key=OPENAI_API_KEY or None, model=OPENAI_MODEL,
                                )
                                known = draft_store.fingerprints()
                                added = 0
                                for issue in issues:
                                    if issue["source_fingerprint"] in known:
                                        continue
                                    draft_store.add({
                                        **issue, "source": "whatsapp",
                                        "source_reference": f"{wa_upload.name} [{start_date}..{end_date}]",
                                    })
                                    known.add(issue["source_fingerprint"])
                                    added += 1
                            skipped = len(issues) - added
                            if added:
                                st.success(f"Created {added} draft(s)" + (f", skipped {skipped} already seen." if skipped else "."))
                                st.rerun()
                            else:
                                st.info("No new issues found in that range." + (f" ({skipped} already seen.)" if skipped else ""))

        # ---- Pending intake (drafts awaiting approval) ----
        pending_drafts = draft_store.list("pending")
        visible_drafts = [
            draft for draft in pending_drafts
            if view_all_user
            or not normalize_department(draft["suggested_department"])
            or normalize_department(draft["suggested_department"]) == current_user.department
        ]
        st.subheader(f"Pending intake ({len(visible_drafts)})")
        if draft_message := st.session_state.pop("draft_action_message", None):
            st.info(draft_message)
        st.caption("Draft requests from WhatsApp. Set the department, then approve to create a support request, or reject. Drafts do not count toward SLA until approved.")
        if not visible_drafts:
            st.caption("Nothing awaiting review." if not pending_drafts else "No drafts routed to your department.")
        may_delete_drafts = can_delete(admin=is_admin_user) and current_user is not OPEN_ADMIN
        if may_delete_drafts and visible_drafts:
            with st.expander("Bulk delete drafts"):
                labels = {
                    draft["draft_id"]: f"{draft['summary'] or 'Draft request'} ({draft['draft_id'][:8]})"
                    for draft in visible_drafts
                }
                select_all = st.checkbox(f"Select all {len(labels)} pending drafts", key="delete_all_drafts")
                selected_drafts = list(labels) if select_all else st.multiselect(
                    "Drafts to delete", options=list(labels), format_func=labels.__getitem__,
                    key="bulk_draft_selection",
                )
                if st.button(
                    f"Delete {len(selected_drafts)} selected drafts", icon=":material/delete:",
                    key="bulk_delete_drafts", disabled=not selected_drafts,
                ):
                    removed = draft_store.delete_pending_many(selected_drafts)
                    st.session_state.draft_action_message = (
                        f"Deleted {removed} pending draft(s). "
                        f"{len(selected_drafts) - removed} no longer pending."
                        if removed != len(selected_drafts)
                        else f"Deleted {removed} pending draft(s)."
                    )
                    st.rerun()
        priority_choices = ["Low", "Medium", "High", "Highest"]
        for draft in visible_drafts:
            did = draft["draft_id"]
            header = f"{draft['summary'] or 'Draft request'}  ·  {draft['category'] or 'Uncategorised'}  ·  {draft['suggested_department'] or 'Unrouted'}"
            draft_details = st
            if may_delete_drafts:
                draft_details, draft_action = st.columns([11, 1], vertical_alignment="top")
                if draft_action.button("🗑", help="Delete draft", key=f"delete_draft_{did}"):
                    removed = draft_store.delete_pending(did)
                    st.session_state.draft_action_message = (
                        "Draft deleted." if removed else "This draft is no longer pending."
                    )
                    st.rerun()
            with draft_details.expander(header):
                summary = st.text_input("Summary", value=draft["summary"] or "", key=f"ds_{did}")
                description = st.text_area("Details", value=draft["description"] or "", key=f"dd_{did}")
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    category = st.selectbox("Category", INTAKE_CATEGORIES, index=option_index(INTAKE_CATEGORIES, draft["category"], len(INTAKE_CATEGORIES) - 1), key=f"dcat_{did}")
                with col_b:
                    priority = st.selectbox("Priority", priority_choices, index=option_index(priority_choices, draft["priority"], 1), key=f"dpri_{did}")
                with col_c:
                    dept_options = ["— Select department —"] + DEPARTMENTS
                    suggested_dept = normalize_department(draft["suggested_department"])
                    dept_index = dept_options.index(suggested_dept) if suggested_dept in dept_options else 0
                    department_choice = st.selectbox("Assign to department *", dept_options, index=dept_index, key=f"ddept_{did}")
                    department = "" if department_choice.startswith("—") else department_choice
                draft_subteams = subteams_for(department)
                if draft_subteams:
                    current_sub = clean_subteam(department, draft["suggested_subteam"])
                    sub_options = ["— Select sub-team —"] + draft_subteams
                    sub_choice = st.selectbox(
                        f"{department} sub-team *", sub_options,
                        index=sub_options.index(current_sub) if current_sub in sub_options else 0, key=f"dsub_{did}",
                    )
                    draft_subteam = "" if sub_choice.startswith("—") else sub_choice
                else:
                    draft_subteam = ""
                if draft["requester_name"] or draft["contact"]:
                    st.caption(f"Requester: {draft['requester_name'] or 'Unknown'}  ·  {draft['contact'] or 'no contact'}")
                if draft["excerpt"]:
                    st.caption("Chat excerpt")
                    st.code(draft["excerpt"])
                review_note = st.text_input("Note (or reason for rejecting)", key=f"dnote_{did}")
                may_route = can_manage(department=current_user.department, admin=is_admin_user, ticket_department=department)
                approve_col, reject_col = st.columns(2)
                approve = approve_col.button("Approve as support request", type="primary", key=f"dok_{did}", disabled=not may_route)
                reject = reject_col.button("Reject", key=f"dno_{did}", disabled=not may_route)
                if not may_route:
                    st.caption("Only the owning department or an admin can approve or reject this draft.")

                if approve:
                    if not department:
                        st.error("Choose a department before approving.")
                        st.stop()
                    if not summary.strip():
                        st.error("Add a summary before approving.")
                        st.stop()
                    if draft_subteams and not draft_subteam:
                        st.error(f"Select a {department} sub-team before approving.")
                        st.stop()
                    ticket_id = str(uuid.uuid4())
                    now_stamp = datetime.now().astimezone().isoformat(timespec="seconds")
                    support_number = f"SUP-{datetime.now():%Y%m%d}-{ticket_id[:6].upper()}"
                    reported_ts = pd.to_datetime(draft["reported_at"], errors="coerce", utc=True) if draft["reported_at"] else pd.NaT
                    reported_value = draft["reported_at"] if (pd.notna(reported_ts) and reported_ts <= pd.Timestamp.now(tz="UTC")) else now_stamp
                    new = {
                        "Ticket ID": ticket_id, "Support Request Number": support_number,
                        "Summary": summary.strip(), "Description": description.strip(), "Status": "to do",
                        "Priority": priority, "Category": category, "Created": now_stamp, "Updated At": now_stamp,
                        "Reported At": reported_value, "Requester Type": "External Clients",
                        "Requester Name": draft["requester_name"] or "", "Channel": "WhatsApp",
                        "Customer WhatsApp": draft["contact"] or "",
                        "Assigned Department": department, "Assigned Sub-team": draft_subteam,
                        "Reporting Department": current_user.department, "Callback Required": "No",
                    }
                    approved = draft_store.resolve(
                        did, status="approved", reviewed_by=current_user.username,
                        review_note=review_note.strip(), approved_ticket_id=ticket_id, ticket=new,
                    )
                    st.session_state.draft_action_message = (
                        f"Approved as {support_number}." if approved else "This draft is no longer pending."
                    )
                    st.rerun()
                if reject:
                    rejected = draft_store.resolve(
                        did, status="rejected", reviewed_by=current_user.username, review_note=review_note.strip(),
                    )
                    st.session_state.draft_action_message = (
                        "Draft rejected." if rejected else "This draft is no longer pending."
                    )
                    st.rerun()

with tab_admin:
    # ---- Historical IT workbook import ----
    if USE_DATABASE and is_admin_user and current_user is not OPEN_ADMIN:
        with st.expander("Upload closed IT requests (.xlsx)"):
            st.caption(
                "Upload an IT Requests workbook, check the preview, and import directly into IT. "
                "An external key can only be imported once. Dates without a timezone are Nairobi time."
            )
            if result := st.session_state.pop("it_workbook_result", None):
                st.success(f"Created {result[0]} closed IT requests. Skipped {result[1]} existing keys.")
            workbook = st.file_uploader("IT requests workbook", type=["xlsx"], key="it_workbook_import")
            if workbook is not None:
                try:
                    tickets = read_it_workbook(workbook.getvalue())
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.dataframe([
                        {
                            "External Key": ticket["external_key"], "Summary": ticket["summary"],
                            "Assignee": ticket["assignee"], "Reported At": ticket["reported_at"],
                            "Resolved At": ticket["resolved_at"], "Closed At": ticket["closed_at"],
                            "Resolution Summary": ticket["resolution_summary"],
                        }
                        for ticket in tickets
                    ], width="stretch", hide_index=True)
                    if st.button(f"Import {len(tickets)} closed IT requests", type="primary"):
                        try:
                            count = import_it_tickets(ws.session_factory, tickets, actor=current_user.username)
                        except SQLAlchemyError:
                            st.error("The database could not import this workbook. No partial batch was saved.")
                        else:
                            st.session_state.it_workbook_result = (count, len(tickets) - count)
                            st.rerun()

    # ---- Jira import ----
    with st.expander("Import and normalize Jira data"):
        st.caption("Upload a Jira CSV to preview its normalized production schema. Existing stable Ticket IDs are skipped.")
        jira_upload = st.file_uploader("Jira CSV export", type=["csv"], key="jira_import")
        if jira_upload is not None:
            normalized_jira = normalize_jira_csv(jira_upload.getvalue())
            jira_stats = import_summary(normalized_jira)
            j1, j2, j3, j4 = st.columns(4)
            j1.metric("Rows", jira_stats["rows"])
            j2.metric("Jira keys", jira_stats["with_external_key"])
            j3.metric("Assigned", jira_stats["with_assignee"])
            j4.metric("Invalid dates", jira_stats["invalid_created"])
            st.dataframe(normalized_jira.head(25), width="stretch", hide_index=True)
            st.download_button(
                "Download normalized preview",
                normalized_jira.to_csv(index=False).encode("utf-8"),
                "jira-normalized.csv",
                "text/csv",
            )
            if st.button("Import new Jira tickets", type="primary"):
                existing = read_df(ws, REQUIRED_HEADERS)
                existing_ids = set(existing["Ticket ID"].astype(str))
                new_rows = normalized_jira[~normalized_jira["Ticket ID"].isin(existing_ids)]
                if new_rows.empty:
                    st.info("No new tickets were found.")
                else:
                    ws.append_rows(new_rows[REQUIRED_HEADERS].fillna("").values.tolist())
                    now_stamp = datetime.now().isoformat(timespec="seconds")
                    actor = st.session_state.get("user", "dashboard-user")
                    activity_rows = [
                        [str(uuid.uuid4()), row["Ticket ID"], "jira_imported", "External Key", "", row["External Key"], "", now_stamp, actor]
                        for _, row in new_rows.iterrows()
                    ]
                    activity_ws.append_rows(activity_rows)
                    st.success(f"Imported {len(new_rows)} new Jira ticket(s).")
                    st.rerun()

    if not (USE_DATABASE and is_admin_user and current_user is not OPEN_ADMIN):
        st.caption("Additional admin tools appear here for administrators.")
