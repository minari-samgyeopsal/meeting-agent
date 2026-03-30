import unittest
import json
import shutil
import tempfile
from pathlib import Path

from tests.test_support import install_dependency_stubs

install_dependency_stubs()

from src.services.drive_service import DriveService
from src.utils.config import Config


class DriveServiceUnitTest(unittest.TestCase):
    def test_list_meeting_states_returns_sorted_entries_in_dry_run(self):
        original_dry_run = Config.DRY_RUN
        original_cache_dir = Config.CACHE_DIR
        temp_dir = tempfile.mkdtemp(prefix="meetagain-drive-list-")

        try:
            Config.DRY_RUN = True
            Config.CACHE_DIR = temp_dir

            service = DriveService()
            state_dir = Path(temp_dir) / "dry_run_drive" / "MeetingState"
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "m1.json").write_text(
                json.dumps({"meeting_id": "m1", "updated_at": "2026-03-25T10:00:00"}),
                encoding="utf-8",
            )
            (state_dir / "m2.json").write_text(
                json.dumps({"meeting_id": "m2", "updated_at": "2026-03-25T11:00:00"}),
                encoding="utf-8",
            )

            result = service.list_meeting_states()

            self.assertEqual([item["meeting_id"] for item in result], ["m2", "m1"])

        finally:
            Config.DRY_RUN = original_dry_run
            Config.CACHE_DIR = original_cache_dir
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_load_generated_draft_uses_expected_path(self):
        service = DriveService.__new__(DriveService)
        service.generated_drafts_folder = "GeneratedDrafts"
        captured = {}

        def fake_read(filepath):
            captured["filepath"] = filepath
            return "draft content"

        service._read_text_file = fake_read

        result = service.load_generated_draft("m1", "proposal")

        self.assertEqual(result, "draft content")
        self.assertEqual(captured["filepath"], "GeneratedDrafts/m1_proposal.md")

    def test_update_meeting_state_merges_existing_data(self):
        service = DriveService.__new__(DriveService)
        stored = {}

        service.load_meeting_state = lambda meeting_id: {"meeting_id": meeting_id, "phase": "before"}

        def fake_save(meeting_id, data):
            stored["meeting_id"] = meeting_id
            stored["data"] = data
            return True

        service.save_meeting_state = fake_save

        result = service.update_meeting_state("m1", {"notes_generated": True})

        self.assertTrue(result)
        self.assertEqual(stored["meeting_id"], "m1")
        self.assertEqual(stored["data"]["phase"], "before")
        self.assertTrue(stored["data"]["notes_generated"])
        self.assertIn("updated_at", stored["data"])

    def test_append_meeting_artifact_adds_unique_entry(self):
        service = DriveService.__new__(DriveService)
        stored = {}

        service.load_meeting_state = lambda meeting_id: {"meeting_id": meeting_id, "artifacts": []}

        def fake_save(meeting_id, data):
            stored["meeting_id"] = meeting_id
            stored["data"] = data
            return True

        service.save_meeting_state = fake_save

        result = service.append_meeting_artifact("m1", "proposal", "GeneratedDrafts/m1_proposal.md")

        self.assertTrue(result)
        self.assertEqual(stored["meeting_id"], "m1")
        self.assertEqual(len(stored["data"]["artifacts"]), 1)
        self.assertEqual(stored["data"]["artifacts"][0]["type"], "proposal")

    def test_load_text_file_delegates_to_reader(self):
        service = DriveService.__new__(DriveService)
        service._read_text_file = lambda filepath: f"loaded:{filepath}"

        self.assertEqual(
            service.load_text_file("MeetingNotes/m1_internal.md"),
            "loaded:MeetingNotes/m1_internal.md",
        )


if __name__ == "__main__":
    unittest.main()
