from src.agents.after_agent import AfterAgent


class DummySlackService:
    def __init__(self, user_id=None):
        self.user_id = user_id

    def get_user_id(self, email):
        return self.user_id


def test_infer_company_name_prefers_topic():
    agent = AfterAgent.__new__(AfterAgent)
    parsed_data = {
        "topic": "kakao follow-up meeting",
        "attendees": ["user@kakao.com"],
    }

    assert agent._infer_company_name(parsed_data) == "kakao"


def test_infer_company_name_falls_back_to_external_domain():
    agent = AfterAgent.__new__(AfterAgent)
    parsed_data = {
        "topic": "",
        "attendees": ["internal@parametacorp.com", "user@kakao.com"],
    }

    assert agent._infer_company_name(parsed_data) == "kakao"


def test_build_assignee_reference_returns_slack_mention_when_found():
    agent = AfterAgent.__new__(AfterAgent)
    agent.slack_svc = DummySlackService(user_id="U123")

    reference = agent._build_assignee_reference(
        {
            "assignee": "홍길동",
            "assignee_email": "hong@parametacorp.com",
        }
    )

    assert reference == "<@U123>"


def test_build_assignee_reference_returns_name_when_user_not_found():
    agent = AfterAgent.__new__(AfterAgent)
    agent.slack_svc = DummySlackService(user_id=None)

    reference = agent._build_assignee_reference(
        {
            "assignee": "홍길동",
            "assignee_email": "hong@parametacorp.com",
        }
    )

    assert reference == "홍길동"
