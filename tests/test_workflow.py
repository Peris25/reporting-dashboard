from reporting.workflow import can_transition, normalize_status


def test_jira_status_aliases_are_normalized():
    assert normalize_status("Backlog") == "to do"
    assert normalize_status("Staging") == "qa testing"


def test_invalid_transition_is_rejected():
    assert not can_transition("to do", "deployed")
    assert can_transition("to do", "diagnosed")


def test_all_open_statuses_can_close_directly():
    for status in ["to do", "diagnosed", "in progress", "qa testing", "deployed"]:
        assert can_transition(status, "closed")
