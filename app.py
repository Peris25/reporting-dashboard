import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import uuid
from urllib.parse import quote
import hashlib
import hmac
import os

from reporting.jira import import_summary, normalize_jira_csv
from reporting.schema import ACTIVITY_HEADERS, STATUSES, TICKET_HEADERS
from reporting.sla import enrich_tickets, format_duration, overdue_milestones, reported_time
from reporting.views import render_reporting_views, render_weekly_report
from reporting.analytics import filter_requests, milestone_deadlines
from reporting.workflow import can_transition
from reporting.history import request_history
from reporting.database import database_handles
from reporting.bootstrap import initialize_database
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

REQUIRED_HEADERS = TICKET_HEADERS


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


@st.fragment(run_every="10m")
def render_request_deadlines(worksheet, ticket_id):
    st.button("Refresh request deadlines", key="refresh_deadlines")
    latest = read_df(worksheet, REQUIRED_HEADERS)
    matching = latest.loc[latest["Ticket ID"].eq(ticket_id)]
    if matching.empty:
        st.warning("This request is no longer available. Refresh to select another request.")
        return
    ticket = matching.iloc[0]
    st.info(f"Current status: {normalize_text(ticket['Status']).capitalize()} | Assigned to: {normalize_text(ticket['Assignee']) or 'Unassigned'}")
    reported = nairobi_input_value(reported_time(ticket))
    logged = nairobi_input_value(ticket["Created"])
    st.caption(f"Reported: {reported:%d %b %Y, %H:%M}" if reported else "Reporting time unavailable")
    st.caption(f"Entered in dashboard: {logged:%d %b %Y, %H:%M} (Nairobi time)" if logged else "Entry time unavailable")
    for column, entry in zip(st.columns(3), milestone_deadlines(ticket)):
        with column:
            getattr(st, entry["tone"])(entry["text"])
    st.caption("Deadlines refresh every 10 minutes. All clocks start at the actual reporting time.")


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


# ---- App ----
require_login()
render_brand_header()
render_dashboard_hero()

render_sidebar_header()

ws, activity_ws = get_sheet_handles()
ensure_headers(ws, REQUIRED_HEADERS)
ensure_headers(activity_ws, ACTIVITY_HEADERS)

df = read_df(ws, REQUIRED_HEADERS)
activity_df = read_df(activity_ws, ACTIVITY_HEADERS)

# ---- Normalize main data ----
df["Status"] = df["Status"].astype(str).str.strip().str.lower()
df["Summary"] = df["Summary"].astype(str).str.strip()
df["Priority"] = df["Priority"].astype(str).str.strip()
df["Created"] = df["Created"].astype(str).str.strip()
df["Diagnosed At"] = df["Diagnosed At"].astype(str).str.strip()
df["Resolved At"] = df["Resolved At"].astype(str).str.strip()
df["Updated At"] = df["Updated At"].astype(str).str.strip()

df = enrich_tickets(df, DIAGNOSIS_SLA_HOURS, RESOLUTION_SLA_HOURS)

# ---- Sidebar filters ----
status_filter = st.sidebar.selectbox("Request status", ["All statuses"] + STATUSES)

priorities = sorted([p for p in df["Priority"].dropna().unique() if str(p).strip() != ""])
priority_filter = st.sidebar.selectbox("Priority", ["All priorities"] + priorities) if priorities else "All priorities"

months = sorted([m for m in df["Created Month"].dropna().unique() if m != "NaT"])
month_filter = st.sidebar.selectbox("Created month", ["All months"] + months) if months else "All months"
agents = sorted({str(value).strip() for value in df["Assignee"].fillna("") if str(value).strip()})
owner_filter = st.sidebar.selectbox("Assigned agent", ["All agents", "Unassigned"] + agents)

render_sidebar_footer()
if DASHBOARD_PASSWORD_HASH and st.sidebar.button("Sign out", icon=":material/logout:", key="sidebar_logout"):
    st.session_state.pop("authenticated", None)
    st.rerun()

search = st.text_input("Search support requests", placeholder="Support number, Reg No, Job Request ID, requester, summary, or agent")
view = filter_requests(df, status_filter, priority_filter, month_filter, owner_filter, search)

@st.fragment(run_every="10m")
def render_live_reporting():
    st.button("Refresh analytics now", key="refresh_analytics")
    refreshed_at = pd.Timestamp.now(tz="UTC")
    fresh = read_df(ws, REQUIRED_HEADERS)
    for field in ["Status", "Summary", "Priority", "Assignee"]:
        fresh[field] = fresh[field].fillna("").astype(str).str.strip()
    fresh["Status"] = fresh["Status"].str.lower()
    live_df = enrich_tickets(fresh, now=refreshed_at)
    live_view = filter_requests(live_df, status_filter, priority_filter, month_filter, owner_filter, search)
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

    render_weekly_report(live_df, refreshed_at)

render_live_reporting()

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

st.divider()

# ---- Quick support intake ----
st.subheader("New support request")
st.caption("Capture a Solver, Solvit Office Team, or External Clients request in under a minute.")
requester_type = st.segmented_control(
    "Who needs support?", ["Solver", "Solvit Office Team", "External Clients"], default="Solver", key="intake_requester_type"
)
channel = st.segmented_control(
    "How did they reach out?", ["Call", "WhatsApp", "SMS", "Email", "Other"], default="Call", key="intake_channel"
)

with st.form("quick_support_intake", clear_on_submit=True):
    reported_at = st.datetime_input(
        "Reported at (Nairobi time) *", value=None, key="intake_reported_at",
        help="Choose when the call, message, or email was actually received. The dashboard entry time is saved separately.",
    )
    st.caption("The SLA clock starts at the reporting time selected above, including for requests entered later.")
    identity_left, identity_right = st.columns(2)
    with identity_left:
        if requester_type == "Solver":
            job_request_id = st.text_input("Job Request ID *", placeholder="The job Request-ID shared by the Solver")
            reg_no = st.text_input("Reg No", placeholder="Vehicle registration number, e.g. KDA 123A")
        elif requester_type == "External Clients":
            job_request_id = st.text_input("Job Request ID", placeholder="Optional related job Request-ID")
            reg_no = st.text_input("Reg No", placeholder="Vehicle registration number, if applicable")
        else:
            job_request_id = ""
            reg_no = ""
            office_department = st.text_input("Office department", placeholder="e.g. Operations, Finance")
    with identity_right:
        phone = st.text_input("Phone / WhatsApp number", placeholder="e.g. 2547XXXXXXXX")
        received_by = st.text_input("Received by *", placeholder="Solvit team member")
        assigned_to = st.text_input("Assigned support agent", placeholder="Leave blank if not assigned")

    issue_left, issue_right = st.columns([1.45, 1])
    with issue_left:
        summary = st.text_input("Issue summary *", placeholder="Short, clear description of the support need")
        description = st.text_area("Request details", placeholder="What happened, what was expected, and any troubleshooting already done")
    with issue_right:
        category = st.selectbox("Category", ["Access & login", "App issue", "Job or request issue", "Payments", "Account or profile", "Technical guidance", "Other"])
        priority = st.selectbox("Priority", ["Medium", "High", "Highest", "Low"])

    call_outcome = ""
    callback_required = False
    callback_deadline = ""
    if channel == "Call":
        call_left, call_middle, call_right = st.columns(3)
        with call_left:
            call_outcome = st.selectbox("Call outcome", ["Answered", "Missed", "Follow-up needed"])
        with call_middle:
            callback_required = st.checkbox("Callback required")
        with call_right:
            callback_deadline_input = st.datetime_input("Callback deadline", value=None)
            callback_deadline = callback_deadline_input.isoformat(timespec="seconds") if callback_deadline_input else ""

    submitted = st.form_submit_button("Create support request", type="primary", width="stretch")
    if submitted:
        errors = []
        if reported_at is None:
            errors.append("Set the date and time the request was reported.")
        elif pd.Timestamp(nairobi_timestamp(reported_at)) > pd.Timestamp.now(tz="UTC"):
            errors.append("Reporting time cannot be in the future.")
        if requester_type == "Solver" and not job_request_id.strip(): errors.append("Job Request ID is required for Solver requests.")
        if not received_by.strip(): errors.append("Received by is required.")
        if not summary.strip(): errors.append("Issue summary is required.")
        if callback_required and not callback_deadline: errors.append("Set a callback deadline when a callback is required.")
        if errors:
            for error in errors: st.error(error)
        else:
            ticket_id = str(uuid.uuid4())
            now_stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            support_number = f"SUP-{datetime.now():%Y%m%d}-{ticket_id[:6].upper()}"
            new = {
                "Ticket ID": ticket_id, "Support Request Number": support_number,
                "Summary": summary.strip(), "Description": description.strip(), "Status": "to do",
                "Priority": priority, "Category": category, "Created": now_stamp, "Updated At": now_stamp,
                "Reported At": nairobi_timestamp(reported_at),
                "Requester Type": requester_type,
                "Job Request ID": job_request_id.strip(), "Reg No": reg_no.strip().upper(),
                "Office Department": office_department.strip() if requester_type == "Solvit Office Team" else "",
                "Channel": channel, "Customer WhatsApp": phone.strip(), "Received By": received_by.strip(),
                "Assignee": assigned_to.strip(), "Call Outcome": call_outcome,
                "Callback Required": "Yes" if callback_required else "No", "Callback Deadline": callback_deadline,
            }
            append_ticket(ws, new)
            append_activity(activity_ws, ticket_id, "support_request_created", "Status", "", "to do", description.strip())
            append_activity(activity_ws, ticket_id, "intake_recorded", "Support Request Number", "", support_number, f"{requester_type} via {channel}")
            st.success(f"Created {support_number}.")
            st.rerun()

st.divider()

# ---- Edit + Delete ----
st.subheader("Manage support requests")
st.caption("Select one request to update its ownership, progress or callback status.")
editor_df = view.copy()

if editor_df.empty:
    st.info("No support requests match the current filters.")
else:
    selected_ticket_id = st.selectbox(
        "Support request",
        options=editor_df["Ticket ID"].tolist(),
        format_func=lambda tid: " · ".join(
            part for part in [
                normalize_text(editor_df.loc[editor_df["Ticket ID"] == tid, "Support Request Number"].iloc[0]) or "Request",
                normalize_text(editor_df.loc[editor_df["Ticket ID"] == tid, "Requester Name"].iloc[0]),
                normalize_text(editor_df.loc[editor_df["Ticket ID"] == tid, "Summary"].iloc[0]),
            ] if part
        ),
    )
    selected = editor_df.loc[editor_df["Ticket ID"] == selected_ticket_id].iloc[0]
    render_request_deadlines(ws, selected_ticket_id)

    st.caption(
        f"{normalize_text(selected['Requester Type']) or 'Requester'}"
        f"  •  {normalize_text(selected['Channel']) or 'Channel not recorded'}"
        f"  •  Job ID: {normalize_text(selected['Job Request ID']) or 'Not applicable'}"
        f"  •  Reg No: {normalize_text(selected['Reg No']) or 'Not recorded'}"
    )

    with st.form("save_edits_form"):
        corrected_reported_at = st.datetime_input(
            "Reported at (Nairobi time)", value=nairobi_input_value(reported_time(selected)), key=f"edit_reported_at_{selected_ticket_id}",
            help="Correct the actual reporting time. This recalculates SLA deadlines and leaves the dashboard entry timestamp unchanged.",
        )
        update_left, update_right = st.columns(2)
        with update_left:
            status_value = normalize_text(selected["Status"]).lower()
            new_status = st.selectbox(
                "Status",
                options=STATUSES,
                index=STATUSES.index(status_value) if status_value in STATUSES else 0,
                help="Resolved requests can move directly to Closed. Add a resolution summary before saving.",
            )
            priority_value = normalize_text(selected["Priority"])
            priority_options = ["Low", "Medium", "High", "Urgent"]
            new_priority = st.selectbox(
                "Priority",
                options=priority_options,
                index=priority_options.index(priority_value) if priority_value in priority_options else 1,
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

        resolution_summary = st.text_area(
            "Resolution summary",
            value=normalize_text(selected["Resolution Summary"]),
            placeholder="What was done to resolve or progress this request?",
        )
        st.caption("Record when you first responded and understood the problem. Use Nairobi time; leave unknown times blank.")
        response_column, diagnosis_column = st.columns(2)
        with response_column:
            first_response_at = st.datetime_input(
                "First response sent at", value=nairobi_input_value(selected["First Response At"]),
            )
            mark_responded = st.form_submit_button(
                "Mark responded", disabled=bool(normalize_text(selected["First Response At"])) or selected["Status"] == "closed",
                help="Record the first response as now and save the current form edits. Use only after responding to the requester.",
            )
        with diagnosis_column:
            diagnosed_at = st.datetime_input(
                "Problem diagnosed at", value=nairobi_input_value(selected["Diagnosed At"]),
            )
            mark_diagnosed = st.form_submit_button(
                "Mark diagnosed", disabled=bool(normalize_text(selected["Diagnosed At"])) or selected["Status"] == "closed",
                help="Record diagnosis as now and save the current form edits. A To do request moves to Diagnosed.",
            )
        st.caption("Milestone buttons record the time now and save your form edits. Use the date fields to correct earlier times.")
        update_note = st.text_area("Update note", placeholder="Add context for this change")
        save_edits = st.form_submit_button("Save request update", type="primary")

    if save_edits or mark_responded or mark_diagnosed:
        base = read_df(ws, REQUIRED_HEADERS)
        base = pd.DataFrame(base)
        for col in REQUIRED_HEADERS:
            if col not in base.columns:
                base[col] = ""

        if base["Ticket ID"].astype(str).duplicated().any():
            st.error("Duplicate Ticket IDs were found. Resolve them before editing.")
            st.stop()

        base_idx = base.set_index("Ticket ID", drop=False)
        tid = selected_ticket_id
        if tid not in base_idx.index:
            st.error("This request no longer exists. Refresh to select another request.")
            st.stop()
        current = {col: normalize_text(base_idx.loc[tid, col]) for col in REQUIRED_HEADERS}
        proposed = current.copy()
        if corrected_reported_at != nairobi_input_value(reported_time(selected)):
            if corrected_reported_at is None:
                st.error("Set the date and time the request was reported.")
                st.stop()
            proposed["Reported At"] = nairobi_timestamp(corrected_reported_at)
        for field, entered in [("First Response At", first_response_at), ("Diagnosed At", diagnosed_at)]:
            # Preserve the stored timestamp unless the user actually changes it.
            if entered != nairobi_input_value(selected[field]):
                proposed[field] = nairobi_timestamp(entered)
        proposed.update({
            "Status": new_status,
            "Priority": new_priority,
            "Assignee": new_assignee.strip(),
            "Callback Required": "Yes" if new_callback_required else "No",
            "Callback Deadline": new_callback_deadline.strip() if new_callback_required else "",
            "Callback Completed At": (
                current["Callback Completed At"] or datetime.now().astimezone().isoformat(timespec="seconds")
            ) if callback_done else "",
            "Resolution Summary": resolution_summary.strip(),
        })
        current["Status"] = current["Status"].lower()
        now_stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        reporting_changed = proposed["Reported At"] != current["Reported At"]
        reported_stamp = pd.to_datetime(reported_time(proposed), errors="coerce", utc=True)
        if reporting_changed and (pd.isna(reported_stamp) or reported_stamp > pd.Timestamp.now(tz="UTC") or reported_stamp > pd.to_datetime(current["Created"], utc=True)):
            st.error("Reporting time must not be later than the dashboard entry time or now.")
            st.stop()

        if mark_responded or mark_diagnosed:
            if current["Status"] == "closed":
                st.error("This request is already closed. Use the date fields to correct its recorded times.")
                st.stop()
            field = "First Response At" if mark_responded else "Diagnosed At"
            proposed[field] = current[field] or now_stamp
            if mark_diagnosed and current["Status"] == "to do" and proposed["Status"] == "to do":
                proposed["Status"] = "diagnosed"

        for field in ["First Response At", "Diagnosed At", "Resolved At", "Closed At"]:
            if (proposed[field] != current[field] or reporting_changed) and proposed[field]:
                timestamp = pd.to_datetime(proposed[field], utc=True)
                received = reported_stamp
                closed = pd.to_datetime(current["Closed At"], errors="coerce", utc=True)
                if pd.isna(received) or timestamp < received or timestamp > pd.Timestamp.now(tz="UTC"):
                    st.error(f"{field} must be between when the request was reported and now.")
                    st.stop()
                if current["Status"] == "closed" and pd.notna(closed) and timestamp > closed:
                    st.error(f"{field} cannot be after request closure.")
                    st.stop()

        if new_callback_required and new_callback_deadline and not valid_datetime(new_callback_deadline):
            st.error("Callback deadline must use a valid date and time.")
            st.stop()
        if current["Status"] != proposed["Status"]:
            if proposed["Status"] == "closed" and not proposed["Resolution Summary"]:
                st.error("Add a resolution summary before closing this request.")
                st.stop()
            if not can_transition(current["Status"], proposed["Status"]):
                st.error(
                    f"This request cannot move directly from {current['Status']} "
                    f"to {proposed['Status']}. Follow the defined workflow."
                )
                st.stop()
            if proposed["Status"] in ["diagnosed", "in progress", "qa testing", "deployed"] and not proposed["Diagnosed At"]:
                proposed["Diagnosed At"] = now_stamp
            if proposed["Status"] in ["deployed", "closed"] and not proposed["Resolved At"]:
                proposed["Resolved At"] = now_stamp
            if proposed["Status"] == "closed":
                proposed["Closed At"] = now_stamp
            if current["Status"] == "closed" and proposed["Status"] != "closed":
                proposed["Closed At"] = ""

        changed_fields = [
            field for field in REQUIRED_HEADERS
            if field not in ["Ticket ID", "Updated At"] and current[field] != proposed[field]
        ]
        if not changed_fields:
            st.info("No changes to save.")
            st.stop()

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

        st.success("Support request updated.")
        st.rerun()

st.divider()

colA, colB = st.columns([1, 1])
with colA:
    delete_ids = st.multiselect(
        "Delete tickets (select by Summary)",
        options=editor_df["Ticket ID"].tolist(),
        format_func=lambda tid: editor_df.loc[editor_df["Ticket ID"] == tid, "Summary"].values[0],
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

st.divider()

# ---- Activity log ----
st.subheader("History for this request")
activity_df = read_df(activity_ws, ACTIVITY_HEADERS)
if not editor_df.empty:
    request_label = normalize_text(selected["Support Request Number"]) or normalize_text(selected["Summary"])
    st.caption(f"{request_label} · Updates to the request selected above, newest first.")
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
else:
    st.caption("Select a request above to see its history.")
