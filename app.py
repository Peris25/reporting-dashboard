import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import uuid

st.set_page_config(page_title="Reporting", layout="wide")

# ---- Config ----
STATUSES = ["to do", "pipeline", "stalled", "in progress", "qa testing", "deployed"]

SHEET_NAME = st.secrets["SHEET_NAME"]          
WORKSHEET_NAME = st.secrets["WORKSHEET_NAME"]  

REQUIRED_HEADERS = ["Ticket ID", "Summary", "Status", "Priority", "Created", "Reporter", "Updated At"]

# ---- Google Sheets helpers ----
@st.cache_resource
def get_ws():
    creds_dict = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open(SHEET_NAME)
    ws = sh.worksheet(WORKSHEET_NAME)
    return ws

def ensure_headers(ws):
    values = ws.get_all_values()
    if not values:
        ws.append_row(REQUIRED_HEADERS)
        return
    header = values[0]
    if header != REQUIRED_HEADERS:
        st.error(
            "Your sheet headers don't match what the app expects.\n\n"
            f"Expected: {REQUIRED_HEADERS}\n"
            f"Found:    {header}\n\n"
            "Fix row 1 to match exactly."
        )
        st.stop()

def read_df(ws) -> pd.DataFrame:
    rows = ws.get_all_records()  # uses row1 headers
    df = pd.DataFrame(rows)
    # Ensure columns exist
    for col in REQUIRED_HEADERS:
        if col not in df.columns:
            df[col] = ""
    return df
    


def write_df(ws, df: pd.DataFrame):
    # Rewrite entire sheet (simple + reliable for single-user)
    df = df[REQUIRED_HEADERS].copy()
    ws.clear()
    ws.append_row(REQUIRED_HEADERS)
    if len(df) > 0:
        ws.append_rows(df.values.tolist())

def normalize_text(s):
    return str(s).strip()

def created_month(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce", dayfirst=True)
    return dt.dt.to_period("M").astype(str)

# ---- App ----
st.title("Reporting Dashboard")

ws = get_ws()
ensure_headers(ws)

df = read_df(ws)

ENABLE_CSV_IMPORT = False  # set True only if you want to re-import

if ENABLE_CSV_IMPORT and df.empty:
    st.warning("Google Sheet is empty. Import your Jira CSV to populate it.")

    csv_file = st.file_uploader("Upload Jira.csv to import into Google Sheets", type=["csv"])
    if csv_file is not None:
        csv_df = pd.read_csv(csv_file)

        required = ["Summary", "Status", "Priority", "Created", "Reporter"]
        missing = [c for c in required if c not in csv_df.columns]
        if missing:
            st.error(f"CSV missing columns: {missing}")
            st.stop()

        STATUS_MAP = {
            "todo": "to do",
            "to do": "to do",
            "deployed": "deployed",
            "backlog": "stalled",
            "in progress": "in progress",
            "staging": "qa testing",
            "verified by solvit": "qa testing",
            "testing": "qa testing",
        }

        csv_df["Status"] = (
            csv_df["Status"].astype(str).str.strip().str.lower().map(STATUS_MAP).fillna("pipeline")
        )
        
        imported = pd.DataFrame({
            "Ticket ID": [str(uuid.uuid4()) for _ in range(len(csv_df))],
            "Summary": csv_df["Summary"].astype(str).str.strip(),
            "Status": csv_df["Status"],
            "Priority": csv_df["Priority"].astype(str).str.strip(),
            "Created": csv_df["Created"].astype(str).str.strip(),
            "Reporter": csv_df["Reporter"].astype(str).str.strip(),
            "Updated At": datetime.now().isoformat(timespec="seconds"),
        })

        if st.button(f"Import {len(imported)} tickets into Google Sheets"):
            write_df(ws, imported)
            st.success(f"Imported {len(imported)} tickets.")
            st.rerun()

df["Status"] = df["Status"].astype(str).str.strip().str.lower()
df["Reporter"] = df["Reporter"].astype(str).str.strip()


# Parse Created once (keep original string in df["Created"] to avoid data loss)
df["Created_dt"] = pd.to_datetime(df["Created"], errors="coerce")

# Display-only: Month + Year (e.g., "Jan 2026")
df["Created (Month)"] = df["Created_dt"].dt.strftime("%b %Y")

df["Priority"] = df["Priority"].astype(str).str.strip()
df["Summary"] = df["Summary"].astype(str).str.strip()
df["Created"] = df["Created"].astype(str).str.strip()



# Add derived month
df["Created Month"] = created_month(df["Created"])


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

# ---- Metrics ----
pending = int((view["Status"] != "deployed").sum())
total = int(len(view))
deployed = int((view["Status"] == "deployed").sum())

c1, c2, c3 = st.columns(3)
c1.metric("Total tickets (filtered)", total)
c2.metric("Pending tickets", pending)
c3.metric("Deployed tickets", deployed)

st.divider()

# Tickets per month
st.subheader("Tickets per month (Created month)")
tpm = view.groupby("Created Month").size().sort_index()
if len(tpm) > 0:
    st.line_chart(tpm)
else:
    st.caption("No data for current filters.")

# Priorities
st.subheader("Current ticket priorities (count)")
pc = view["Priority"].value_counts()
if len(pc) > 0:
    st.bar_chart(pc)
else:
    st.caption("No priority data for current filters.")

st.divider()

# ---- Add ticket ----
st.subheader("Add ticket")
with st.form("add_ticket", clear_on_submit=True):
    summary = st.text_input("Summary")
    status = st.selectbox("Status", STATUSES, index=0)
    priority = st.text_input("Priority", placeholder="e.g. High / Medium / Low")
    created = st.text_input("Created (date)", value=datetime.now().strftime("%Y-%m-%d"))
    

    add = st.form_submit_button("Add")
    if add:
        if not summary.strip():
            st.warning("Summary is required.")
        else:
            new = {
                "Ticket ID": str(uuid.uuid4()),
                "Summary": summary.strip(),
                "Status": status,
                "Priority": priority.strip(),
                "Created": created.strip(),
                "Reporter": "",
                "Updated At": datetime.now().isoformat(timespec="seconds"),
            }
            base = read_df(ws)
            base = pd.concat([base, pd.DataFrame([new])], ignore_index=True)
            write_df(ws, base)
            st.success("Added.")
            st.rerun()

st.divider()

# ---- Edit + Delete ----
st.subheader("Edit tickets (inline)")
editable_cols = ["Ticket ID", "Summary", "Status", "Priority", "Created (Month)", "Updated At"]
editor_df = view[editable_cols].copy()

# Oldest -> newest; NaT goes last so it doesn't mess up ordering
view = view.sort_values(by="Created_dt", ascending=True, na_position="last")

edited = st.data_editor(
    editor_df,
    width='stretch',
    hide_index=True,
    column_config={
        "Ticket ID": st.column_config.TextColumn("Ticket ID", disabled=True),
        "Status": st.column_config.SelectboxColumn("Status", options=STATUSES),
        "Created (Month)": st.column_config.TextColumn("Created", disabled=True),
        "Updated At": st.column_config.TextColumn("Updated At", disabled=True),
    },
    key="editor",
)

colA, colB = st.columns([1, 1])

with colA:
    if st.button("Save edits"):
        base = read_df(ws)
        base = pd.DataFrame(base)

        # Ensure columns
        for col in REQUIRED_HEADERS:
            if col not in base.columns:
                base[col] = ""

        base_idx = base.set_index("Ticket ID")
        upd = edited.set_index("Ticket ID")

        # Apply updates
        for tid in upd.index:
            base_idx.loc[tid, "Summary"] = normalize_text(upd.loc[tid, "Summary"])
            base_idx.loc[tid, "Status"] = normalize_text(upd.loc[tid, "Status"]).lower()
            base_idx.loc[tid, "Priority"] = normalize_text(upd.loc[tid, "Priority"])
            base_idx.loc[tid, "Updated At"] = datetime.now().isoformat(timespec="seconds")

        base2 = base_idx.reset_index()
        write_df(ws, base2)
        st.success("Saved edits.")
        st.rerun()

with colB:
    delete_ids = st.multiselect(
        "Delete tickets (select by Summary)",
        options=edited["Ticket ID"].tolist(),
        format_func=lambda tid: edited.loc[edited["Ticket ID"] == tid, "Summary"].values[0],
    )
    if st.button("Delete selected"):
        base = read_df(ws)
        base = pd.DataFrame(base)
        base = base[~base["Ticket ID"].isin(delete_ids)].copy()
        write_df(ws, base)
        st.success(f"Deleted {len(delete_ids)} ticket(s).")
        st.rerun()
