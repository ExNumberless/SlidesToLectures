import base64
from types import SimpleNamespace

import pytest

tts = pytest.importorskip("slidestolectures.tts")


def test_speakable_strips_markdown_and_cues():
    assert tts.speakable("**Bold** and _it_ [link](http://x) [smiles]") == "Bold and it link"


def test_segments_split_at_pauses_and_limit():
    body = "First paragraph.\n\n[pause for answers]\n\nSecond paragraph."
    assert tts.segments(body) == [("First paragraph.", tts.PAUSE_GAP), ("Second paragraph.", tts.SLIDE_GAP)]

    long = " ".join(["A sentence that goes on."] * 200)
    segs = tts.segments(long)
    assert len(segs) > 1
    assert all(len(text) <= tts.MAX_CHARS for text, _ in segs)
    assert " ".join(text for text, _ in segs) == long


class FakeSpeechify:
    def __init__(self):
        self.audio = self

    def speech(self, input, voice_id, **kw):
        return SimpleNamespace(audio_data=base64.b64encode(b"\x00\x00" * len(input)).decode())


def fake_encode(path, slides, futures, out, cache_dir):
    for fs in futures.values():
        for f in fs:
            f.result()
    out.write_bytes(b"mp3")
    return 1.0


def test_run_reports_progress_and_characters(tmp_path, monkeypatch, reporter):
    monkeypatch.setattr(tts, "Speechify", FakeSpeechify)
    monkeypatch.setattr(tts, "encode", fake_encode)
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "Cells.md"
    src.write_text("# Lecture: Cells\n\n## [1] Cells\n\nHello there.\n\n## [2] More\n\nGoodbye.\n")

    tts.run([src], tmp_path / "audio", "henry", reporter=reporter)

    assert sorted(reporter.of("usage"), key=lambda u: u[2]["characters"]) == [
        ("speechify", "henry", {"characters": 8}),
        ("speechify", "henry", {"characters": 12}),
    ]
    steps = reporter.of("step")
    assert steps[0] == ("speechify", 0, 2)
    assert [(done, total) for _, done, total in steps[1:]] == [(1, 2), (2, 2)]
    assert reporter.of("log") == [
        ("1 lecture(s), 2 requests, 20 characters, voice henry",),
        ("-> audio/Cells.mp3 (1.0 min)",),
    ]

    # Cached audio is reported as progress but not as usage.
    reporter.calls.clear()
    tts.run([src], tmp_path / "audio", "henry", force=True, reporter=reporter)
    assert reporter.of("usage") == []
    assert all(name.endswith("(cached)") for name, done, _ in reporter.of("step") if done)
