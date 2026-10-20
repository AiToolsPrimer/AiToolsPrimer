from pathlib import Path

from agency.media.audio import chunk_text, srt_from_script
from agency.media.video import Scene, VideoPlan


def test_chunk_text_respects_sentences():
    text = "One sentence. " * 80
    chunks = chunk_text(text, max_chars=200)
    assert all(len(c) <= 200 for c in chunks)
    assert all(c.endswith(".") for c in chunks)
    assert " ".join(chunks).count("One sentence.") == 80


def test_plan_clamps_to_four_minutes():
    data = {"title": "t", "scenes": [{"narration": "word " * 30, "visual_prompt": "x", "seconds": 12} for _ in range(40)]}
    plan = VideoPlan.from_json(data, 240)
    assert plan.total() <= 240
    assert len(plan.scenes) == 20


def test_estimate_from_words():
    assert Scene("one two three four five six seven eight nine ten", "x").estimate() == 4.4


def test_mixed_mode_alternates():
    data = {"title": "t", "scenes": [{"narration": "a b c", "visual_prompt": "x"} for _ in range(6)]}
    plan = VideoPlan.from_json(data, 240, default_mode="mixed")
    assert [s.mode for s in plan.scenes] == ["generated", "image_motion", "image_motion"] * 2


def test_srt_from_script(tmp_path: Path):
    srt = srt_from_script([{"narration": "hello there friends of the channel", "seconds": 8.0}], tmp_path / "a.srt")
    text = srt.read_text()
    assert "00:00:00,000 -->" in text and "friends" in text
