import pandas as pd
import pytest

from reporting.sla import breach_rate, classify_sla, elapsed_hours, enrich_tickets, sla_summary, overdue_milestones


def test_elapsed_hours_rejects_negative_duration():
    assert elapsed_hours("2026-01-02", "2026-01-01") is None


def test_completed_ticket_sla_boundary_is_inclusive():
    assert classify_sla("2026-01-01 10:00Z", "2026-01-01 11:00Z", 1) == "Within SLA"


def test_open_ticket_becomes_breached():
    assert classify_sla("2026-01-01 10:00Z", "", 1, now="2026-01-01 12:00Z") == "Breached"


def test_breach_rate_excludes_pending_and_unknown():
    values = pd.Series(["Within SLA", "Breached", "Pending", "Unknown"])
    assert breach_rate(values) == 50.0


def test_empty_database_can_be_enriched():
    empty = pd.DataFrame(columns=["Created", "Diagnosed At", "Resolved At", "Updated At"])
    result = enrich_tickets(empty)
    assert result.empty
    assert pd.api.types.is_datetime64_any_dtype(result["Created_dt"])
    assert sla_summary(result)["On time"].tolist() == ["—", "—", "—"]


@pytest.mark.parametrize("target", [0.5, 2, 48])
def test_targets_do_not_round_away_a_one_second_breach(target):
    start = pd.Timestamp("2026-09-04T10:00:00Z")
    deadline = start + pd.Timedelta(hours=target)
    assert classify_sla(start, deadline, target) == "Within SLA"
    assert classify_sla(start, deadline + pd.Timedelta(seconds=1), target) == "Breached"
    assert classify_sla(start, "", target, now=deadline) == "Pending"
    assert classify_sla(start, "", target, now=deadline + pd.Timedelta(seconds=1)) == "Breached"


def test_closure_clock_continues_after_deployment_and_stops_at_closure():
    base = {"Created": "2026-09-04T10:00:00Z", "Resolved At": "2026-09-05T10:00:00Z"}
    result = enrich_tickets(pd.DataFrame([
        {**base, "Status": "deployed"},
        {**base, "Status": "closed", "Closed At": "2026-09-06T10:00:00Z"},
    ]), now="2026-09-06T11:00:00Z")
    assert result.loc[0, "Closure SLA"] == "Breached"
    assert result.loc[1, "Closure SLA"] == "Within SLA"
    assert result.loc[1, "Closure Hours"] == 48
    assert pd.isna(result.loc[1, "Open Hours"])
    assert result.loc[1, "Response SLA"] == "Not recorded"


def test_missing_history_is_not_treated_as_on_time():
    result = enrich_tickets(pd.DataFrame([
        {"Created": "2026-09-04T10:00:00Z", "Status": "closed"},
    ]))
    summary = sla_summary(result)
    assert summary["On time"].tolist() == ["—", "—", "—"]
    assert summary["Missing / invalid"].tolist() == [1, 1, 1]


def test_late_response_is_measured_but_no_longer_needs_response_attention():
    result = enrich_tickets(pd.DataFrame([
        {"Created": "2026-09-04T10:00:00Z", "Status": "to do", "First Response At": "2026-09-04T13:31:00+03:00"},
    ]), now="2026-09-04T10:45:00Z")
    assert result.loc[0, "Response SLA"] == "Breached"
    assert not overdue_milestones(result).any(axis=None)
    summary = sla_summary(result).iloc[0]
    assert summary["On time"] == "0%"
    assert summary["Completed late"] == 1
    assert summary["Overdue"] == 0


def test_invalid_timestamp_is_not_an_open_pending_milestone():
    assert classify_sla("2026-09-04T10:00:00Z", "bad-date", 0.5) == "Invalid"


def test_delayed_entry_uses_reporting_time_for_all_clocks():
    result = enrich_tickets(pd.DataFrame([{
        "Created": "2026-09-10T10:00:00+03:00", "Reported At": "2026-09-09T21:00:00+03:00",
        "First Response At": "2026-09-09T21:20:00+03:00", "Diagnosed At": "2026-09-09T22:00:00+03:00",
        "Closed At": "2026-09-11T21:00:00+03:00", "Status": "closed",
    }]), now="2026-09-12T00:00:00Z")
    assert result.loc[0, "Response Hours"] == pytest.approx(1 / 3)
    assert result.loc[0, "Diagnosis Hours"] == 1
    assert result.loc[0, "Closure Hours"] == 48
    assert result.loc[0, "Closure SLA"] == "Within SLA"
