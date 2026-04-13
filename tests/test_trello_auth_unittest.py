import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.auth.token_store import TokenStore
from src.auth.trello_auth_service import TrelloAuthService
from src.services.trello_service import TrelloService
from src.utils.config import Config


class TrelloAuthUnitTest(unittest.TestCase):
    def test_trello_auth_service_builds_authorize_url(self):
        original_key = Config.TRELLO_OAUTH_APP_KEY
        original_name = Config.TRELLO_OAUTH_APP_NAME
        original_scope = Config.TRELLO_OAUTH_SCOPE
        original_expiration = Config.TRELLO_OAUTH_EXPIRATION
        original_return = Config.TRELLO_OAUTH_RETURN_URL
        try:
            Config.TRELLO_OAUTH_APP_KEY = "app-key"
            Config.TRELLO_OAUTH_APP_NAME = "Meetagain"
            Config.TRELLO_OAUTH_SCOPE = "read,write"
            Config.TRELLO_OAUTH_EXPIRATION = "never"
            Config.TRELLO_OAUTH_RETURN_URL = "https://localhost/trello/oauth"
            url = TrelloAuthService().build_authorization_url()
        finally:
            Config.TRELLO_OAUTH_APP_KEY = original_key
            Config.TRELLO_OAUTH_APP_NAME = original_name
            Config.TRELLO_OAUTH_SCOPE = original_scope
            Config.TRELLO_OAUTH_EXPIRATION = original_expiration
            Config.TRELLO_OAUTH_RETURN_URL = original_return

        self.assertIn("app-key", url)
        self.assertIn("response_type=token", url)
        self.assertIn("read%2Cwrite", url)

    def test_trello_auth_service_connect_token_saves_member_info(self):
        with tempfile.TemporaryDirectory(prefix="meetagain-trello-oauth-") as temp_dir:
            original_store = Config.OAUTH_TOKEN_STORE_PATH
            original_key = Config.TRELLO_OAUTH_APP_KEY
            try:
                Config.OAUTH_TOKEN_STORE_PATH = str(Path(temp_dir) / "tokens.json")
                Config.TRELLO_OAUTH_APP_KEY = "app-key"
                auth = TrelloAuthService(token_store=TokenStore(Config.OAUTH_TOKEN_STORE_PATH))

                class Response:
                    def raise_for_status(self):
                        return None

                    def json(self):
                        return {"id": "m1", "username": "mincircle", "fullName": "PARA_김민환", "url": "https://trello.com/mincircle"}

                with patch("src.auth.trello_auth_service.requests.get", return_value=Response()):
                    record = auth.connect_token("user-token")
            finally:
                Config.OAUTH_TOKEN_STORE_PATH = original_store
                Config.TRELLO_OAUTH_APP_KEY = original_key

        self.assertEqual(record["token"], "user-token")
        self.assertEqual(record["member_username"], "mincircle")

    def test_trello_service_uses_oauth_token_for_card_listing(self):
        with tempfile.TemporaryDirectory(prefix="meetagain-trello-oauth-") as temp_dir:
            original_store = Config.OAUTH_TOKEN_STORE_PATH
            original_enabled = Config.ENABLE_TRELLO_OAUTH
            original_key = Config.TRELLO_OAUTH_APP_KEY
            original_board = Config.TRELLO_BOARD_ID
            original_token = Config.TRELLO_API_TOKEN
            try:
                Config.OAUTH_TOKEN_STORE_PATH = str(Path(temp_dir) / "tokens.json")
                Config.ENABLE_TRELLO_OAUTH = True
                Config.TRELLO_OAUTH_APP_KEY = "app-key"
                Config.TRELLO_BOARD_ID = "board-1"
                Config.TRELLO_API_TOKEN = ""
                TokenStore(Config.OAUTH_TOKEN_STORE_PATH).save_token("trello", Config.TRELLO_OAUTH_OWNER, {"token": "oauth-token"})

                class Response:
                    def __init__(self, payload):
                        self._payload = payload
                        self.text = "payload"

                    def raise_for_status(self):
                        return None

                    def json(self):
                        return self._payload

                def fake_request(method, url, params=None, timeout=20):
                    if url.endswith("/boards/board-1"):
                        return Response({"id": "board-1", "name": "OAuth Board", "url": "https://trello.com/b/board-1"})
                    if url.endswith("/boards/board-1/cards"):
                        return Response([{"id": "card-1", "name": "미래에셋증권", "url": "https://trello.com/c/card-1"}])
                    raise AssertionError(url)

                with patch("src.services.trello_service.requests.request", side_effect=fake_request):
                    service = TrelloService()
                    cards = service.list_cards_by_board_scope("미래에셋 미팅 정리")
            finally:
                Config.OAUTH_TOKEN_STORE_PATH = original_store
                Config.ENABLE_TRELLO_OAUTH = original_enabled
                Config.TRELLO_OAUTH_APP_KEY = original_key
                Config.TRELLO_BOARD_ID = original_board
                Config.TRELLO_API_TOKEN = original_token

        self.assertEqual(cards[0]["card_name"], "미래에셋증권")


if __name__ == "__main__":
    unittest.main()
