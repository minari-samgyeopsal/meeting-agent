import unittest
from unittest.mock import patch

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.services.gmail_service import GmailService


class GmailServiceUnitTest(unittest.TestCase):
    def test_search_emails_uses_users_messages_list_params(self):
        service = GmailService()

        class Completed:
            returncode = 0
            stderr = ""
            stdout = '{"messages":[{"id":"m1","threadId":"t1"}]}'

        with patch("src.services.gmail_service.subprocess.run", return_value=Completed()) as mocked_run:
            emails = service.search_emails("from:user@kakao.com", max_results=3)

        self.assertEqual(len(emails), 1)
        args, kwargs = mocked_run.call_args
        cmd = args[0]
        self.assertIn("users", cmd)
        self.assertIn("messages", cmd)
        self.assertIn("list", cmd)
        self.assertIn("--params", cmd)
        self.assertIn('"userId": "me"', cmd[-1])
        self.assertIn('"q": "from:user@kakao.com"', cmd[-1])


if __name__ == "__main__":
    unittest.main()
