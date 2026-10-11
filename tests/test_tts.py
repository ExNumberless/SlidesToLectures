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
