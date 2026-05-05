import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "facebook-reel-upload.py"
spec = importlib.util.spec_from_file_location("facebook_reel_upload", MODULE_PATH)
facebook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(facebook)


def test_slugify_matches_existing_pipeline_naming():
    assert facebook.slugify("Empty Train Home") == "empty-train-home"
    assert facebook.slugify("NSTC: Don't Stop, Now") == "nstc-dont-stop-now"


def test_extract_schedule_from_short_filename():
    date_str, slot, slug = facebook.extract_schedule_from_filename(
        Path("shorts/2026-05-10_AM_empty-train-home.mp4")
    )
    assert date_str == "2026-05-10"
    assert slot == "AM"
    assert slug == "empty-train-home"


def test_build_reel_description_adds_hashtags_and_parent_link():
    metadata = {
        "title": "NSTC — Empty Train Home",
        "description": "Late night lofi.\n\nFull mixtape: https://youtube.com/watch?v=abc\n\n#lofi #chill",
        "tags": ["lofi", "lofi hip hop", "study music"],
    }
    desc = facebook.build_reel_description(metadata)
    assert "Late night lofi." in desc
    assert "https://youtube.com/watch?v=abc" in desc
    assert "#lofi" in desc
    assert "#lofihiphop" in desc
    assert "#studymusic" in desc


def test_find_reels_for_phase_uses_schedule_and_existing_files(tmp_path):
    shorts = tmp_path / "shorts"
    shorts.mkdir()
    (shorts / "2026-05-10_AM_empty-train-home.mp4").write_bytes(b"fake")
    (shorts / "2026-05-10_AM_empty-train-home.json").write_text('{"title":"x","description":"y"}')
    schedule = {
        "phases": [
            {"shorts": [{"track": "Empty Train Home", "date": "2026-05-10", "slot": "AM"}]}
        ]
    }
    pairs = facebook.find_reels_for_phase(1, schedule, shorts)
    assert pairs == [(shorts / "2026-05-10_AM_empty-train-home.mp4", shorts / "2026-05-10_AM_empty-train-home.json")]
