from reporting.jira import normalize_jira_csv


def test_duplicate_jira_headers_are_supported():
    source = "Summary,Issue key,Status,Labels,Labels,Created,Priority\nExample,SR-1,Backlog,a,b,06/Jan/26 9:29 AM,High\n"
    result = normalize_jira_csv(source)
    assert len(result) == 1
    assert result.iloc[0]["External Key"] == "SR-1"
    assert result.iloc[0]["Status"] == "to do"
