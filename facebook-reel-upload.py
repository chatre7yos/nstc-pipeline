#!/usr/bin/env python3
"""
Upload generated Shorts to Facebook Reels through the Facebook Graph API.

Usage:
  python3 facebook-reel-upload.py <video.mp4>             # Upload single Reel
  python3 facebook-reel-upload.py --phase 1               # Upload all Phase 1 Reels
  python3 facebook-reel-upload.py --all                   # Upload everything
  python3 facebook-reel-upload.py --dry-run --phase 1     # Preview without uploading

Requires FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN in .env.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple
from urllib import error, parse, request

from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(os.environ.get("NSTC_BASE_DIR", Path(__file__).parent))
SHORTS_DIR = BASE_DIR / "shorts"
SCHEDULE_FILE = BASE_DIR / "shorts-schedule.json"
GRAPH_VERSION = os.environ.get("FACEBOOK_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def slugify(text: str) -> str:
    """Match generate-shorts.py/youtube-upload.py filename slug behavior."""
    return (text.lower()
            .replace(":", "")
            .replace(",", "")
            .replace("'", "")
            .replace(" ", "-"))


def extract_schedule_from_filename(video_path: Path) -> Tuple[str, str, str]:
    """Return date, slot, slug from YYYY-MM-DD_SLOT_slug.mp4."""
    parts = video_path.stem.split("_", 2)
    if len(parts) != 3:
        raise ValueError(f"Expected filename format YYYY-MM-DD_SLOT_slug.mp4: {video_path.name}")
    return parts[0], parts[1], parts[2]


def hashtag(tag: str) -> str:
    return "#" + "".join(ch for ch in tag if ch.isalnum())


def build_reel_description(metadata: Dict) -> str:
    """Build Facebook Reel description from generated Shorts metadata."""
    description = metadata.get("description", "").strip()
    tags = metadata.get("tags", [])
    tag_text = " ".join(dict.fromkeys(hashtag(t) for t in tags if t))
    if tag_text and tag_text not in description:
        description = f"{description}\n\n{tag_text}" if description else tag_text
    return description


def find_reels_for_phase(phase_num: int, schedule: Dict, shorts_dir: Path) -> List[Tuple[Path, Path]]:
    """Find generated video/metadata pairs for a phase."""
    phase_idx = phase_num - 1
    if phase_idx < 0 or phase_idx >= len(schedule["phases"]):
        raise ValueError(f"Invalid phase number. Available phases: 1-{len(schedule['phases'])}")

    pairs = []
    for short_data in schedule["phases"][phase_idx]["shorts"]:
        slug = slugify(short_data["track"])
        date = short_data["date"]
        slot = short_data["slot"]
        video = shorts_dir / f"{date}_{slot}_{slug}.mp4"
        meta = shorts_dir / f"{date}_{slot}_{slug}.json"
        if video.exists() and meta.exists():
            pairs.append((video, meta))
        else:
            print(f"  WARNING: Missing files for {short_data['track']}")
    return pairs


def find_all_reels(schedule: Dict, shorts_dir: Path) -> List[Tuple[Path, Path]]:
    pairs = []
    for idx in range(len(schedule["phases"])):
        pairs.extend(find_reels_for_phase(idx + 1, schedule, shorts_dir))
    return pairs


def graph_post(path: str, params: Dict, token: str) -> Dict:
    data = parse.urlencode({**params, "access_token": token}).encode()
    req = request.Request(f"{GRAPH_BASE}/{path.lstrip('/')}", data=data, method="POST")
    try:
        with request.urlopen(req) as resp:
            return json.loads(resp.read())
    except error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Facebook Graph API error {e.code}: {body}") from e


def upload_binary(upload_url: str, video_path: Path, token: str) -> None:
    """Upload video bytes to Facebook's upload URL."""
    size = video_path.stat().st_size
    with video_path.open("rb") as f:
        req = request.Request(
            upload_url,
            data=f,
            headers={
                "Authorization": f"OAuth {token}",
                "offset": "0",
                "file_size": str(size),
                "Content-Type": "application/octet-stream",
            },
            method="POST",
        )
        try:
            with request.urlopen(req) as resp:
                resp.read()
        except error.HTTPError as e:
            body = e.read().decode()
            raise RuntimeError(f"Facebook binary upload error {e.code}: {body}") from e


def upload_reel(page_id: str, token: str, video_path: Path, metadata_path: Path, dry_run: bool = False) -> bool:
    """Upload a single generated Short to Facebook Reels."""
    with metadata_path.open() as f:
        metadata = json.load(f)

    title = metadata.get("title", video_path.stem)
    description = build_reel_description(metadata)
    date_str, slot, _ = extract_schedule_from_filename(video_path)

    print(f"\n  Title: {title}")
    print(f"  File: {video_path.name}")
    print(f"  Source schedule: {date_str} {slot}")
    print(f"  Description: {description[:120]}{'...' if len(description) > 120 else ''}")

    if dry_run:
        print(f"  [DRY RUN] Would upload {video_path.name} to Facebook Page {page_id} as Reel")
        return True

    start = graph_post(
        f"{page_id}/video_reels",
        {"upload_phase": "start"},
        token,
    )
    video_id = start["video_id"]
    upload_url = start["upload_url"]

    upload_binary(upload_url, video_path, token)

    finish = graph_post(
        f"{page_id}/video_reels",
        {
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": description,
        },
        token,
    )

    metadata["facebook_reel_id"] = video_id
    metadata["facebook_uploaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if "post_id" in finish:
        metadata["facebook_post_id"] = finish["post_id"]
    with metadata_path.open("w") as f:
        json.dump(metadata, f, indent=2)

    print(f"  Uploaded Facebook Reel: {video_id}")
    return True


def load_schedule() -> Dict:
    with SCHEDULE_FILE.open() as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Upload generated Shorts to Facebook Reels")
    parser.add_argument("video", nargs="?", help="Single video file to upload")
    parser.add_argument("--phase", type=int, help="Upload all generated Shorts from a phase")
    parser.add_argument("--all", action="store_true", help="Upload all generated Shorts")
    parser.add_argument("--dry-run", action="store_true", help="Preview without uploading")
    args = parser.parse_args()

    if not args.video and not args.phase and not args.all:
        parser.print_help()
        sys.exit(1)

    pairs: List[Tuple[Path, Path]] = []
    if args.video:
        video = Path(args.video)
        meta = video.with_suffix(".json")
        if not video.exists():
            print(f"ERROR: Video not found: {video}")
            sys.exit(1)
        if not meta.exists():
            print(f"ERROR: Metadata not found: {meta}")
            sys.exit(1)
        pairs.append((video, meta))
    else:
        schedule = load_schedule()
        pairs = find_all_reels(schedule, SHORTS_DIR) if args.all else find_reels_for_phase(args.phase, schedule, SHORTS_DIR)

    if not pairs:
        print("No generated Shorts/Reels found to upload.")
        sys.exit(1)

    page_id = os.environ.get("FACEBOOK_PAGE_ID")
    token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")
    if not args.dry_run and (not page_id or not token):
        print("ERROR: Set FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN in .env")
        sys.exit(1)
    page_id = page_id or "DRY_RUN_PAGE_ID"

    print(f"{'=' * 60}")
    print(f"Facebook Reels Upload {'(DRY RUN)' if args.dry_run else ''}")
    print(f"{'=' * 60}")
    print(f"Reels to upload: {len(pairs)}")

    success = 0
    for i, (video, meta) in enumerate(pairs, 1):
        print(f"\n[{i}/{len(pairs)}]")
        try:
            if upload_reel(page_id, token or "", video, meta, args.dry_run):
                success += 1
                if not args.dry_run and i < len(pairs):
                    print("  Waiting 5s before next upload...")
                    time.sleep(5)
        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\n{'=' * 60}")
    print(f"Done. {success}/{len(pairs)} uploaded to Facebook Reels.")


if __name__ == "__main__":
    main()
