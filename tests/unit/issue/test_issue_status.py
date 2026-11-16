from offline_rag.issue.domain.issue_status import IssueStatus


def test_statuses_follow_the_spec_list_when_read_in_order():
    assert [status.value for status in IssueStatus] == [
        "new",
        "analyzing",
        "knowledge_identified",
        "executor_identified",
        "solution_proposed",
        "in_execution",
        "awaiting_decision",
        "resolved",
        "unresolved",
        "archived",
    ]
