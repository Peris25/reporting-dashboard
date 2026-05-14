import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import uuid

st.set_page_config(page_title="Reporting", layout="wide")

# ---- Config ----
STATUSES = ["to do", "diagnosed", "in progress", "qa testing", "deployed"]
DIAGNOSIS_SLA_HOURS = 1
RESOLUTION_SLA_HOURS = 24

SHEET_NAME = st.secrets["SHEET_NAME"]
WORKSHEET_NAME = st.secrets["WORKSHEET_NAME"]
ACTIVITY_WORKSHEET_NAME = st.secrets.get("ACTIVITY_WORKSHEET_NAME", "ticket_activity_log")

REQUIRED_HEADERS = [
    "Ticket ID",
    "Summary",
    "Status",
    "Priority",
    "Created",
    "Diagnosed At",
    "Resolved At",
    "Updated At",
]

ACTIVITY_HEADERS = [
    "Activity ID",
    "Ticket ID",
    "Action",
    "Field",
    "Old Value",
    "New Value",
    "Note",
    "Timestamp",
]


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


def write_df(ws, df: pd.DataFrame, required_headers):
    df = df[required_headers].copy()
    ws.clear()
    ws.append_row(required_headers)
    if len(df) > 0:
        ws.append_rows(df.values.tolist())


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
    ])


def normalize_text(value):
    return str(value).strip()


def parse_dt(series_or_value):
    return pd.to_datetime(series_or_value, errors="coerce")


def created_month(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce")
    return dt.dt.to_period("M").astype(str)


def diff_hours(start_val, end_val):
    start_dt = parse_dt(start_val)
    end_dt = parse_dt(end_val)
    if pd.isna(start_dt) or pd.isna(end_dt):
        return None
    return round((end_dt - start_dt).total_seconds() / 3600, 2)


def diagnosis_hours(row):
    return diff_hours(row.get("Created"), row.get("Diagnosed At"))


def resolution_hours(row):
    return diff_hours(row.get("Created"), row.get("Resolved At"))


def diagnosis_sla(row):
    created_dt = parse_dt(row.get("Created"))
    diagnosed_dt = parse_dt(row.get("Diagnosed At"))
    if pd.isna(created_dt):
        return "Unknown"
    if pd.isna(diagnosed_dt):
        hours_open = (pd.Timestamp.now() - created_dt).total_seconds() / 3600
        return "Pending" if hours_open <= DIAGNOSIS_SLA_HOURS else "Breached"
    return "Within SLA" if diff_hours(row.get("Created"), row.get("Diagnosed At")) <= DIAGNOSIS_SLA_HOURS else "Breached"


def resolution_sla(row):
    created_dt = parse_dt(row.get("Created"))
    resolved_dt = parse_dt(row.get("Resolved At"))
    if pd.isna(created_dt):
        return "Unknown"
    if pd.isna(resolved_dt):
        hours_open = (pd.Timestamp.now() - created_dt).total_seconds() / 3600
        return "Pending" if hours_open <= RESOLUTION_SLA_HOURS else "Breached"
    return "Within SLA" if diff_hours(row.get("Created"), row.get("Resolved At")) <= RESOLUTION_SLA_HOURS else "Breached"


def fmt_hours(val):
    if pd.isna(val) or val is None:
        return "—"
    return f"{float(val):.2f} hours"


# ---- App ----
st.title("Reporting Dashboard")

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

df["Created_dt"] = parse_dt(df["Created"])
df["Created Month"] = created_month(df["Created"])
df["Diagnosis Hours"] = df.apply(diagnosis_hours, axis=1)
df["Resolution Hours"] = df.apply(resolution_hours, axis=1)
df["Diagnosis SLA"] = df.apply(diagnosis_sla, axis=1)
df["Resolution SLA"] = df.apply(resolution_sla, axis=1)

# ---- Sidebar filters ----
st.sidebar.header("Filters")
picked_statuses = st.sidebar.multiselect("Status", STATUSES, default=STATUSES)

priorities = sorted([p for p in df["Priority"].dropna().unique() if str(p).strip() != ""])
picked_priorities = st.sidebar.multiselect("Priority", priorities, default=priorities) if priorities else []

months = sorted([m for m in df["Created Month"].dropna().unique() if m != "NaT"])
picked_months = st.sidebar.multiselect("Created month", months, default=months) if months else []

view = df[df["Status"].isin(picked_statuses)].copy()
if picked_priorities:
    view = view[view["Priority"].isin(picked_priorities)]
if picked_months:
    view = view[view["Created Month"].isin(picked_months)]

view = view.sort_values("Created_dt", ascending=True, na_position="last")

# ---- Summary metrics ----
total = int(len(view))
diagnosed_within = int((view["Diagnosis SLA"] == "Within SLA").sum())
resolved_within = int((view["Resolution SLA"] == "Within SLA").sum())
diagnosis_breach_rate = round(((view["Diagnosis SLA"] == "Breached").sum() / total) * 100, 1) if total else 0
diagnosis_done = view["Diagnosis Hours"].dropna()
avg_diagnosis = diagnosis_done.mean() if len(diagnosis_done) else None

resolution_done = view["Resolution Hours"].dropna()
resolution_breach_rate = round(((view["Resolution SLA"] == "Breached").sum() / total) * 100, 1) if total else 0
avg_resolution = resolution_done.mean() if len(resolution_done) else None

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total tickets", total)
c2.metric("Diagnosed within 1 hour", diagnosed_within)
c3.metric("Resolved within 24 hours", resolved_within)
c4.metric("Diagnosis breach rate", f"{diagnosis_breach_rate}%")

c5, c6, c7 = st.columns(3)
c5.metric("Resolution breach rate", f"{resolution_breach_rate}%")
c6.metric("Average diagnosis time", fmt_hours(avg_diagnosis))
c7.metric("Average resolution time", fmt_hours(avg_resolution))

st.divider()

# ---- Dashboard charts ----
left, right = st.columns([1.4, 1])

with left:
    st.subheader("Performance overview")
    summary_df = pd.DataFrame(
        {
            "Metric": [
                "Total tickets",
                "Diagnosed within 1-hour SLA",
                "Resolved within 24-hour SLA",
                "Diagnosis breach rate",
                "Resolution breach rate",
                "Average diagnosis time",
                "Average resolution time",
            ],
            "Value": [
                total,
                diagnosed_within,
                resolved_within,
                f"{diagnosis_breach_rate}%",
                f"{resolution_breach_rate}%",
                fmt_hours(avg_diagnosis),
                fmt_hours(avg_resolution),
            ],
        }
    )
    st.dataframe(summary_df, width="stretch", hide_index=True)

with right:
    st.subheader("Top ticket priorities")
    pc = view["Priority"].value_counts()
    if len(pc) > 0:
        st.bar_chart(pc)
    else:
        st.caption("No priority data for current filters.")

st.subheader("Tickets per month")
tpm = view.groupby("Created Month").size().sort_index()
if len(tpm) > 0:
    st.line_chart(tpm)
else:
    st.caption("No data for current filters.")

st.divider()

# ---- Add ticket ----
st.subheader("Add ticket")
with st.form("add_ticket", clear_on_submit=True):
    summary = st.text_input("Summary")
    status = st.selectbox("Status", STATUSES, index=0)
    priority = st.text_input("Priority", placeholder="e.g. High / Medium / Low")
    created = st.text_input("Created (date)", value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    note = st.text_area("Initial note (optional)")

    add = st.form_submit_button("Add")
    if add:
        if not summary.strip():
            st.warning("Summary is required.")
        else:
            ticket_id = str(uuid.uuid4())
            now_stamp = datetime.now().isoformat(timespec="seconds")
            diagnosed_at = now_stamp if status == "diagnosed" else ""
            resolved_at = now_stamp if status == "deployed" else ""
            new = {
                "Ticket ID": ticket_id,
                "Summary": summary.strip(),
                "Status": status,
                "Priority": priority.strip(),
                "Created": created.strip(),
                "Diagnosed At": diagnosed_at,
                "Resolved At": resolved_at,
                "Updated At": now_stamp,
            }
            base = read_df(ws, REQUIRED_HEADERS)
            base = pd.concat([base, pd.DataFrame([new])], ignore_index=True)
            write_df(ws, base, REQUIRED_HEADERS)

            append_activity(activity_ws, ticket_id=ticket_id, action="ticket_created", field="Status", old_value="", new_value=status, note=note.strip())
            if status == "diagnosed":
                append_activity(activity_ws, ticket_id=ticket_id, action="diagnosed", field="Status", old_value="to do", new_value="diagnosed", note=note.strip())
            if status == "deployed":
                append_activity(activity_ws, ticket_id=ticket_id, action="resolved", field="Status", old_value="", new_value="deployed", note=note.strip())
            if note.strip():
                append_activity(activity_ws, ticket_id=ticket_id, action="note_added", field="Note", old_value="", new_value=note.strip(), note=note.strip())

            st.success("Added.")
            st.rerun()

st.divider()

# ---- Edit + Delete ----
st.subheader("Edit tickets")
st.caption("Use status updates to drive diagnosis and resolution SLA tracking.")
editable_cols = [
    "Ticket ID",
    "Summary",
    "Status",
    "Priority",
    "Created",
    "Diagnosed At",
    "Resolved At",
    "Updated At",
    "Diagnosis SLA",
    "Resolution SLA",
]
editor_df = view[editable_cols].copy()

edited = st.data_editor(
    editor_df,
    width="stretch",
    hide_index=True,
    column_config={
        "Ticket ID": st.column_config.TextColumn("Ticket ID", disabled=True),
        "Status": st.column_config.SelectboxColumn("Status", options=STATUSES),
        "Created": st.column_config.TextColumn("Created", help="Format: YYYY-MM-DD HH:MM:SS"),
        "Diagnosed At": st.column_config.TextColumn("Diagnosed At", help="Format: YYYY-MM-DD HH:MM:SS"),
        "Resolved At": st.column_config.TextColumn("Resolved At", help="Format: YYYY-MM-DD HH:MM:SS"),
        "Updated At": st.column_config.TextColumn("Updated At", help="Format: YYYY-MM-DD HH:MM:SS"),
        "Diagnosis SLA": st.column_config.TextColumn("Diagnosis SLA", disabled=True),
        "Resolution SLA": st.column_config.TextColumn("Resolution SLA", disabled=True),
    },
    key="editor",
)

with st.form("save_edits_form"):
    update_note = st.text_area("Update note (optional)", placeholder="Add context for this change")
    save_edits = st.form_submit_button("Save edits")

    if save_edits:
        base = read_df(ws, REQUIRED_HEADERS)
        base = pd.DataFrame(base)
        for col in REQUIRED_HEADERS:
            if col not in base.columns:
                base[col] = ""

        base_idx = base.set_index("Ticket ID")
        upd = edited.set_index("Ticket ID")

        for tid in upd.index:
            if tid not in base_idx.index:
                continue

            old_summary = normalize_text(base_idx.loc[tid, "Summary"])
            new_summary = normalize_text(upd.loc[tid, "Summary"])
            old_priority = normalize_text(base_idx.loc[tid, "Priority"])
            new_priority = normalize_text(upd.loc[tid, "Priority"])
            old_status = normalize_text(base_idx.loc[tid, "Status"]).lower()
            new_status = normalize_text(upd.loc[tid, "Status"]).lower()
            now_stamp = datetime.now().isoformat(timespec="seconds")

            new_created = normalize_text(upd.loc[tid, "Created"])
            old_created = normalize_text(base_idx.loc[tid, "Created"])
            new_diagnosed_at = normalize_text(upd.loc[tid, "Diagnosed At"])
            old_diagnosed_at = normalize_text(base_idx.loc[tid, "Diagnosed At"])
            new_resolved_at = normalize_text(upd.loc[tid, "Resolved At"])
            old_resolved_at = normalize_text(base_idx.loc[tid, "Resolved At"])
            new_updated_at = normalize_text(upd.loc[tid, "Updated At"])
            old_updated_at = normalize_text(base_idx.loc[tid, "Updated At"])

            if old_summary != new_summary:
                base_idx.loc[tid, "Summary"] = new_summary

            if old_priority != new_priority:
                base_idx.loc[tid, "Priority"] = new_priority

            if new_created and new_created != old_created:
                base_idx.loc[tid, "Created"] = new_created
                append_activity(activity_ws, ticket_id=tid, action="field_edited", field="Created", old_value=old_created, new_value=new_created, note=update_note.strip())

            if new_diagnosed_at != old_diagnosed_at:
                base_idx.loc[tid, "Diagnosed At"] = new_diagnosed_at
                append_activity(activity_ws, ticket_id=tid, action="field_edited", field="Diagnosed At", old_value=old_diagnosed_at, new_value=new_diagnosed_at, note=update_note.strip())

            if new_resolved_at != old_resolved_at:
                base_idx.loc[tid, "Resolved At"] = new_resolved_at
                append_activity(activity_ws, ticket_id=tid, action="field_edited", field="Resolved At", old_value=old_resolved_at, new_value=new_resolved_at, note=update_note.strip())

            if old_status != new_status:
                append_activity(activity_ws, ticket_id=tid, action="status_changed", field="Status", old_value=old_status, new_value=new_status, note=update_note.strip())
                base_idx.loc[tid, "Status"] = new_status

                if new_status == "diagnosed" and not normalize_text(base_idx.loc[tid, "Diagnosed At"]):
                    base_idx.loc[tid, "Diagnosed At"] = now_stamp
                    append_activity(activity_ws, ticket_id=tid, action="diagnosed", field="Status", old_value=old_status, new_value="diagnosed", note=update_note.strip())

                if new_status == "deployed" and not normalize_text(base_idx.loc[tid, "Resolved At"]):
                    base_idx.loc[tid, "Resolved At"] = now_stamp
                    if not normalize_text(base_idx.loc[tid, "Diagnosed At"]):
                        base_idx.loc[tid, "Diagnosed At"] = now_stamp
                    append_activity(activity_ws, ticket_id=tid, action="resolved", field="Status", old_value=old_status, new_value="deployed", note=update_note.strip())

            if update_note.strip():
                append_activity(activity_ws, ticket_id=tid, action="note_added", field="Note", old_value="", new_value=update_note.strip(), note=update_note.strip())

            if new_updated_at != old_updated_at and new_updated_at:
                base_idx.loc[tid, "Updated At"] = new_updated_at
                append_activity(activity_ws, ticket_id=tid, action="field_edited", field="Updated At", old_value=old_updated_at, new_value=new_updated_at, note=update_note.strip())
            else:
                base_idx.loc[tid, "Updated At"] = now_stamp

        base2 = base_idx.reset_index()
        write_df(ws, base2, REQUIRED_HEADERS)
        st.success("Saved edits.")
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
    base = base[~base["Ticket ID"].isin(delete_ids)].copy()
    write_df(ws, base, REQUIRED_HEADERS)
    st.success(f"Deleted {len(delete_ids)} ticket(s).")
    st.rerun()

st.divider()

# ---- Activity log ----
st.subheader("Activity log")
activity_df = read_df(activity_ws, ACTIVITY_HEADERS)
if not activity_df.empty:
    activity_df["Timestamp_dt"] = pd.to_datetime(activity_df["Timestamp"], errors="coerce")
    activity_view = activity_df.sort_values("Timestamp_dt", ascending=False, na_position="last")

    ticket_choices = sorted([t for t in activity_view["Ticket ID"].astype(str).unique() if t.strip()])
    picked_ticket = st.selectbox("Filter activity by Ticket ID", options=["All"] + ticket_choices)
    if picked_ticket != "All":
        activity_view = activity_view[activity_view["Ticket ID"] == picked_ticket]

    display_cols = [
        "Timestamp",
        "Ticket ID",
        "Action",
        "Field",
        "Old Value",
        "New Value",
        "Note",
    ]
    st.dataframe(activity_view[display_cols], width="stretch", hide_index=True)
else:
    st.caption("No activity logged yet.")
