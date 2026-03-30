from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / "cache" / "dry_run_drive"
MEETING_DIRS = {
    "MeetingState": ".json",
    "MeetingNotes": "",
    "MeetingTranscripts": "",
    "GeneratedDrafts": "",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive stale meeting-scoped artifacts.")
    parser.add_argument(
        "--keep",
        action="append",
        default=[],
        help="Meeting ID to keep. Can be provided multiple times.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which files would be archived without moving them.",
    )
    return parser.parse_args()


def should_archive(path: Path, keep_ids: set[str]) -> bool:
    name = path.name

    for meeting_id in keep_ids:
        if meeting_id in name:
            return False

    if name.startswith("dry-run-") or name == "dry-run-meeting.json":
        return True

    for keep in keep_ids:
        if keep and keep in name:
            return False

    if path.parent.name == "GeneratedDrafts" and name.startswith("reminders_"):
        return True

    return path.parent.name in MEETING_DIRS


def main() -> int:
    args = parse_args()
    keep_ids = {item.strip() for item in args.keep if item.strip()}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_root = ROOT / "cache" / "archive" / f"meeting_cleanup_{timestamp}"
    moves: list[tuple[Path, Path]] = []

    for dirname in MEETING_DIRS:
        source_dir = CACHE_ROOT / dirname
        if not source_dir.exists():
            continue
        for path in sorted(source_dir.glob("*")):
            if not path.is_file():
                continue
            if should_archive(path, keep_ids):
                target = archive_root / dirname / path.name
                moves.append((path, target))

    if args.dry_run:
        for src, dst in moves:
            print(f"DRY-RUN {src} -> {dst}")
        print(f"Would archive {len(moves)} files")
        return 0

    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        print(f"ARCHIVED {src} -> {dst}")

    print(f"Archived {len(moves)} files into {archive_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
