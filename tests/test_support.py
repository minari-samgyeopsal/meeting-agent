import sys
import types


def install_dependency_stubs():
    if "anthropic" not in sys.modules:
        anthropic_module = types.ModuleType("anthropic")

        class _Messages:
            def create(self, *args, **kwargs):
                return types.SimpleNamespace(content=[types.SimpleNamespace(text="{}")])

        class Anthropic:
            def __init__(self, *args, **kwargs):
                self.messages = _Messages()

        anthropic_module.Anthropic = Anthropic
        sys.modules["anthropic"] = anthropic_module

    if "trello" not in sys.modules:
        trello_module = types.ModuleType("trello")

        class _DummyBoard:
            name = "Dummy Board"

            def all_cards(self):
                return []

        class TrelloClient:
            def __init__(self, *args, **kwargs):
                pass

            def get_board(self, *args, **kwargs):
                return _DummyBoard()

        trello_module.TrelloClient = TrelloClient
        sys.modules["trello"] = trello_module

        board_module = types.ModuleType("trello.board")
        board_module.Board = type("Board", (), {})
        sys.modules["trello.board"] = board_module

        card_module = types.ModuleType("trello.card")
        card_module.Card = type("Card", (), {})
        sys.modules["trello.card"] = card_module

    if "slack_sdk" not in sys.modules:
        slack_sdk_module = types.ModuleType("slack_sdk")

        class WebClient:
            def __init__(self, *args, **kwargs):
                pass

            def chat_getPermalink(self, *args, **kwargs):
                channel = kwargs.get("channel", "C123")
                ts = kwargs.get("message_ts", "123.456")
                return {"permalink": f"https://slack.test/archives/{channel}/p{str(ts).replace('.', '')}"}

            def conversations_history(self, *args, **kwargs):
                return {"messages": []}

        slack_sdk_module.WebClient = WebClient
        sys.modules["slack_sdk"] = slack_sdk_module

        errors_module = types.ModuleType("slack_sdk.errors")

        class SlackApiError(Exception):
            def __init__(self, message="", response=None):
                super().__init__(message)
                self.response = response or {"error": "stubbed"}

        errors_module.SlackApiError = SlackApiError
        sys.modules["slack_sdk.errors"] = errors_module

    if "slack_bolt" not in sys.modules:
        bolt_module = types.ModuleType("slack_bolt")

        class App:
            def __init__(self, *args, **kwargs):
                pass

            def command(self, *args, **kwargs):
                def decorator(func):
                    return func
                return decorator

            def event(self, *args, **kwargs):
                def decorator(func):
                    return func
                return decorator

            def action(self, *args, **kwargs):
                def decorator(func):
                    return func
                return decorator

        bolt_module.App = App
        sys.modules["slack_bolt"] = bolt_module

        adapter_module = types.ModuleType("slack_bolt.adapter.socket_mode")

        class SocketModeHandler:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                return None

        adapter_module.SocketModeHandler = SocketModeHandler
        sys.modules["slack_bolt.adapter.socket_mode"] = adapter_module

    if "duckduckgo_search" not in sys.modules:
        ddg_module = types.ModuleType("duckduckgo_search")

        class DDGS:
            def text(self, *args, **kwargs):
                return []

        ddg_module.DDGS = DDGS
        sys.modules["duckduckgo_search"] = ddg_module
