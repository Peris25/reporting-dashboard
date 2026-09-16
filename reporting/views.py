import streamlit as st
import altair as alt
from datetime import timedelta

from reporting.sla import sla_summary, overdue_milestones
from reporting.analytics import department_breakdown, milestone_deadlines, weekly_report
from reporting.departments import DEPARTMENTS


def performance_charts(view, summary):
    outcomes = ["On time", "Completed late", "Waiting", "Overdue", "Missing / invalid"]
    values = []
    for row in summary.to_dict("records"):
        counts = {name: int(row[name]) for name in outcomes if name != "On time"}
        counts["On time"] = int(row["Recorded"] - row["Completed late"])
        for outcome in outcomes:
            values.append({
                "Milestone": f"{row['Milestone']} ({row['Target']})",
                "Outcome": outcome, "Requests": counts[outcome], "Order": outcomes.index(outcome),
            })
    # Inline values avoid an unnecessary dataframe/Arrow conversion for small charts.
    bars = alt.Chart(alt.Data(values=values)).mark_bar().encode(
        x=alt.X("Requests:Q", title="Requests", axis=alt.Axis(tickMinStep=1)),
        y=alt.Y("Milestone:N", title=None, sort=[f"{r['Milestone']} ({r['Target']})" for r in summary.to_dict("records")]),
        color=alt.Color("Outcome:N", scale=alt.Scale(
            domain=outcomes, range=["#10B981", "#F97316", "#3B82F6", "#ff353e", "#94A3B8"]
        ), legend=alt.Legend(title=None, orient="bottom", columns=2)),
        order=alt.Order("Order:Q"),
        tooltip=["Milestone:N", "Outcome:N", "Requests:Q"],
    ).properties(height=240).configure_view(strokeWidth=0)
    closed = int(view["Status"].eq("closed").sum())
    statuses = [
        {"Status": "Open", "Requests": len(view) - closed},
        {"Status": "Closed", "Requests": closed},
    ]
    pie = alt.Chart(alt.Data(values=statuses)).mark_arc(innerRadius=60).encode(
        theta=alt.Theta("Requests:Q"),
        color=alt.Color("Status:N", scale=alt.Scale(domain=["Open", "Closed"], range=["#3B82F6", "#10B981"]),
                        legend=alt.Legend(title=None, orient="bottom")),
        tooltip=["Status:N", "Requests:Q"],
    ).properties(height=240).configure_view(strokeWidth=0)
    return bars, pie


def render_reporting_views(view):
    st.subheader("SLA and turnaround time")
    st.caption(
        "All three targets start when the request was reported, including nights and weekends. "
        "Turnaround time (TAT) is reported to closed. Times are shown in Nairobi time."
    )
    summary = sla_summary(view)
    if view.empty:
        st.info("Charts will appear when requests match your filters.")
    else:
        bars, pie = performance_charts(view, summary)
        sla_column, status_column = st.columns([1.6, 1])
        with sla_column:
            st.markdown("#### SLA performance")
            st.caption("Each bar measures the same requests against one target. Hover for counts.")
            st.altair_chart(bars, width="stretch")
        with status_column:
            st.markdown("#### Open vs closed")
            st.caption(f"{len(view)} requests in the current filters. Open includes deployed requests awaiting closure.")
            st.altair_chart(pie, width="stretch")
    st.dataframe(summary, width="stretch", hide_index=True)
    st.caption(
        "On time and average time use recorded milestones only. Waiting means still within target; "
        "overdue means the milestone has not been recorded and its deadline has passed. "
        "Missing historical timestamps are not counted as successful outcomes."
    )
    st.subheader("Requests needing attention")
    open_requests = view.loc[view["Status"].ne("closed")].copy()
    open_requests["Assignee"] = open_requests["Assignee"].fillna("").astype(str).str.strip().replace("", "Unassigned")
    late = overdue_milestones(open_requests)
    unassigned = open_requests["Assignee"].eq("Unassigned")
    st.caption(f"{int(unassigned.sum())} open requests are unassigned. Use the Assigned agent filter to find an owner's workload.")
    with st.expander("Open requests and owners"):
        ownership = open_requests[["Support Request Number", "Summary", "Reg No", "Assignee", "Status"]]
        st.dataframe(ownership, width="stretch", hide_index=True)
    queue = open_requests.loc[late.any(axis=1) | unassigned].copy()
    if queue.empty:
        st.info("All open requests are assigned and none are overdue in the current filters.")
        return
    queue["Needs attention"] = late.loc[queue.index].apply(
        lambda row: ", ".join(name.replace(" SLA", "").lower() for name, overdue in row.items() if overdue), axis=1
    )
    queue["Hours open"] = queue["Open Hours"].round(1)
    for index in queue.index:
        if queue.at[index, "Assignee"] == "Unassigned":
            queue.at[index, "Needs attention"] = ", ".join(filter(None, [queue.at[index, "Needs attention"], "assign an agent"]))
    queue["Next action"] = queue.apply(
        lambda row: next((item["text"] for item in milestone_deadlines(row) if item["tone"] == "error"), "Assign an agent"), axis=1
    )
    queue["Request"] = queue["Support Request Number"].where(queue["Support Request Number"].ne(""), queue["Summary"])
    st.dataframe(
        queue.sort_values("Open Hours", ascending=False)[
            ["Request", "Summary", "Assignee", "Status", "Hours open", "Needs attention", "Next action"]
        ], width="stretch", hide_index=True,
    )


def render_department_breakdown(df):
    """Company-wide view for admins: how each department and Ops sub-team is doing."""
    st.subheader("Company-wide by department")
    st.caption(
        "Every request across the company, grouped by the department that owns it, "
        "with Operations broken down by sub-team. Independent of the filters above so "
        "departments stay comparable. Breach percentages use recorded and overdue milestones."
    )
    breakdown = department_breakdown(df, DEPARTMENTS)
    if breakdown.empty:
        st.info("No requests to summarise yet.")
        return
    st.dataframe(breakdown, width="stretch", hide_index=True)
    st.caption(
        "Needs attention counts each open request once if it is overdue or unassigned. "
        "Indented rows are Operations sub-teams. Unrouted rows have no recognised department."
    )


def render_weekly_report(df, now):
    with st.expander("Weekly comparison and download"):
        st.caption(
            "All requests, independent of the filters above. Last 7 days versus the preceding 7 days. "
            "Logged counts use logging dates; closed counts and TAT use closure dates. "
            "Each SLA percentage uses milestones recorded in that period; missing times are excluded. "
            "Reopened requests count as closed only after they are closed again."
        )
        start = now - timedelta(days=7)
        st.caption(f"Current period: {start.tz_convert('Africa/Nairobi'):%d %b %H:%M} to {now.tz_convert('Africa/Nairobi'):%d %b %H:%M} (Nairobi).")
        summary = weekly_report(df, now)
        st.dataframe(summary, width="stretch", hide_index=True)
        st.caption("pp = percentage points. Lower TAT is better; higher on-time percentages are better.")
        st.download_button("Download weekly report", summary.to_csv(index=False).encode("utf-8"),
                           file_name=f"weekly-report-{now:%Y-%m-%d}.csv", mime="text/csv")
