import unittest
from asyncio import run
from datetime import datetime
from unittest.mock import patch

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.agents.channel_monitor_agent import ChannelMonitorAgent
from src.utils.config import Config


class ChannelMonitorAgentUnitTest(unittest.TestCase):
    def setUp(self):
        self.original_realtime = Config.ENABLE_CHANNEL_MONITOR_REALTIME
        Config.ENABLE_CHANNEL_MONITOR_REALTIME = True
        self.agent = ChannelMonitorAgent()

    def tearDown(self):
        Config.ENABLE_CHANNEL_MONITOR_REALTIME = self.original_realtime

    def test_should_process_event_rejects_channel_message_in_realtime_mode(self):
        event = {
            "channel_type": "channel",
            "text": "외부 미팅 정리입니다. 다음 단계와 법률 검토 요청이 있습니다.",
            "ts": "123.456",
        }
        self.assertFalse(self.agent.should_process_event(event))

    def test_should_process_event_accepts_dm_and_rejects_thread_and_short_message(self):
        self.assertTrue(
            self.agent.should_process_event(
                {"channel_type": "im", "text": "미래에셋 미팅 정리와 후속 요청입니다.", "ts": "1"}
            )
        )
        self.assertFalse(
            self.agent.should_process_event(
                {"channel_type": "channel", "text": "회의 정리", "ts": "1", "thread_ts": "0.9"}
            )
        )
        self.assertFalse(self.agent.should_process_event({"channel_type": "channel", "text": "짧다", "ts": "1"}))

    def test_build_daily_collection_window_uses_last_completed_window(self):
        start, end = self.agent.build_daily_collection_window(reference=datetime.fromisoformat("2026-04-05T16:00:00+09:00"))
        self.assertEqual(start.isoformat(), "2026-04-03T17:00:00+09:00")
        self.assertEqual(end.isoformat(), "2026-04-04T17:00:00+09:00")
        start2, end2 = self.agent.build_daily_collection_window(reference=datetime.fromisoformat("2026-04-05T18:00:00+09:00"))
        self.assertEqual(start2.isoformat(), "2026-04-04T17:00:00+09:00")
        self.assertEqual(end2.isoformat(), "2026-04-05T17:00:00+09:00")

    def test_handle_channel_message_supports_im_archive_flow(self):
        payload = run(
            self.agent.handle_channel_message(
                {
                    "channel_type": "im",
                    "channel": "D123",
                    "user": "U123",
                    "user_profile": {"real_name": "김우성"},
                    "text": "외부 미팅 정리\n- 법률 검토 요청 이번 주\n- 다음 단계 제안서 발송 필요",
                    "ts": "555.111",
                }
            )
        )
        self.assertIsInstance(payload, dict)
        self.assertIn("개인 DM", payload["text"])

    def test_should_archive_rule_based(self):
        eval_result = self.agent.evaluate_archive_candidate(
            "미래에셋 미팅 정리\n- legal 검토 요청\n- 다음 단계 확정 필요\n- 거래처 반응 긍정적"
        )
        self.assertGreaterEqual(eval_result["score"], 3)
        archived = run(
            self.agent.should_archive(
                "미래에셋 미팅 정리\n- legal 검토 요청\n- 다음 단계 확정 필요\n- 거래처 반응 긍정적"
            )
        )
        self.assertTrue(archived)
        not_archived = run(self.agent.should_archive("점심 먹고 들어오겠습니다"))
        self.assertFalse(not_archived)

    def test_extract_action_items_rule_based(self):
        items = run(
            self.agent.extract_action_items(
                "미래에셋 미팅 정리\n- UI/UX 추가 제작 필요\n- 법률 검토 요청 이번 주\n- 금 토큰 방안 조사 다음 주"
            )
        )
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["task"], "전용 dApp UI/UX 추가 제작")
        self.assertEqual(items[0]["deadline"], "담당자 지정 필요")
        self.assertEqual(items[1]["task"], "법률 검토 요청")
        self.assertEqual(items[1]["deadline"], "이번 주 내")
        self.assertEqual(items[2]["task"], "금토큰 발행 연계 방안 조사")
        self.assertEqual(items[2]["deadline"], "다음 주 내")

    def test_extract_action_items_summarizes_long_meeting_notes(self):
        items = run(
            self.agent.extract_action_items(
                "미래에셋증권(전략) 미팅 정리 - 테마틱 볼트 사업\n"
                "Supercycl thematic vault defi에 running profit 형태의 제휴 서비스를 붙이는 컨셉으로 준비하자고 합의\n"
                "미래에셋(코빗) 특화 dApp ui/ux를 한 벌 더 만들어 줘야함\n"
                "프로젝트의 각 Phase 상에서의 리스크(ex. VASP 우회 방안, 상품의 증권성 여부 판단, KYC 정보 전송 내용 허용범위 등)에 대해 법률 검토 요청\n"
                "PAXG 같은 금토큰 발행 방안도 같이 검토 필요"
            )
        )
        self.assertIn("미래에셋 전용 dApp UI/UX 추가 제작", [item["task"] for item in items])
        self.assertIn("VASP·증권성·KYC 관련 법률 검토 요청", [item["task"] for item in items])
        self.assertIn("금토큰 발행 연계 방안 조사", [item["task"] for item in items])

    def test_handle_channel_message_builds_confirmation_payload(self):
        payload = run(
            self.agent.handle_batch_message(
                {
                    "channel_type": "channel",
                    "channel": "C123",
                    "user": "U123",
                    "user_profile": {"real_name": "김우성"},
                    "text": "미래에셋 미팅 정리\n- 법률 검토 요청 이번 주\n- 다음 미팅 전 UI/UX 추가 제작 필요",
                    "ts": "123.456",
                }
            )
        )
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["thread_ts"], "123.456")
        self.assertIn("Meetagain 아카이빙 제안", payload["text"])
        self.assertEqual(payload["blocks"][-1]["type"], "actions")

    def test_run_daily_collection_collects_archive_candidates(self):
        with patch(
            "src.services.slack_service.SlackService.fetch_conversation_history",
            return_value=[
                {"user": "U1", "text": "점심 먹고 올게요", "ts": "1.1"},
                {"user": "U1", "text": "미래에셋 미팅 정리\n- 법률 검토 요청 이번 주", "ts": "1.2"},
            ],
        ):
            report = run(self.agent.run_daily_collection(["C_BIZ"], reference=datetime.fromisoformat("2026-04-05T18:00:00+09:00")))
        self.assertEqual(report["scanned_count"], 2)
        self.assertEqual(report["proposal_count"], 1)
        self.assertEqual(report["review_candidate_count"], 1)
        self.assertGreaterEqual(report["review_candidates"][0]["score"], 1)
        self.assertIn("blocks", report["proposals"][0])

    def test_handle_channel_message_populates_permalink(self):
        payload = run(
            self.agent.handle_batch_message(
                {
                    "channel_type": "channel",
                    "channel": "C777",
                    "user": "U123",
                    "text": "고객 미팅 정리\n- 법률 검토 요청 이번 주\n- 후속 공유 필요",
                    "ts": "321.654",
                }
            )
        )
        register_value = payload["blocks"][-1]["elements"][0]["value"]
        self.assertIn("https://slack.test/archives/C777/p321654", register_value)

    def test_handle_archive_action_register_returns_preview(self):
        response = run(
            self.agent.handle_archive_action(
                ack=lambda: None,
                body={
                    "actions": [
                        {
                            "action_id": "archive_register",
                            "value": (
                                '{"recommendation":{"board":"세일즈 파이프라인","card_name":"미래에셋증권"},'
                                '"preview":{"action_items":[1,2],"card_url":"dry-run://trello-card"}}'
                            ),
                        }
                    ]
                },
                client=None,
            )
        )
        self.assertIn("Trello 등록 완료", response["text"])
        self.assertEqual(response["response_type"], "ephemeral")

    def test_handle_archive_action_change_card_returns_candidate_blocks(self):
        response = run(
            self.agent.handle_archive_action(
                ack=lambda: None,
                body={
                    "actions": [
                        {
                            "action_id": "archive_change_card",
                            "value": (
                                '{"recommendation":{"board":"세일즈 파이프라인","card_name":"미래에셋증권"},'
                                '"preview":{"candidate_cards":[{"board":"세일즈 파이프라인","card_name":"미래에셋증권"},'
                                '{"board":"프로젝트 모니터","card_name":"Web3 인증 프로젝트"}]}}'
                            ),
                        }
                    ]
                },
                client=None,
            )
        )
        self.assertEqual(response["blocks"][0]["type"], "section")
        self.assertEqual(response["blocks"][-1]["type"], "section")
        self.assertEqual(response["blocks"][-1]["accessory"]["type"], "static_select")

    def test_handle_archive_action_select_card_uses_selected_option(self):
        response = run(
            self.agent.handle_archive_action(
                ack=lambda: None,
                body={
                    "actions": [
                        {
                            "action_id": "archive_select_card",
                            "selected_option": {
                                "value": (
                                    '{"recommendation":{"board":"세일즈 파이프라인","card_name":"카카오","card_id":"dry-kakao","url":"dry-run://kakao"},'
                                    '"preview":{"action_items":[{"task":"후속 메일 발송","deadline":"이번 주 내"}],"card_url":"dry-run://kakao"},'
                                    '"event_meta":{"channel_name":"#biz","author":"김우성","event_ts":"123.456"}}'
                                )
                            },
                        }
                    ]
                },
                client=None,
            )
        )
        self.assertIn("카카오", response["text"])
