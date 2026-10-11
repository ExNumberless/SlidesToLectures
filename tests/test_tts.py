import json
from concurrent.futures import Future

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


def test_encode_writes_chapters_json(tmp_path, monkeypatch):
    def done(pcm):
        f = Future()
        f.set_result(pcm)
        return f

    second = b"\x00\x00" * tts.RATE
    slides = [
        ("[5] Cells", [("a", tts.CHUNK_GAP), ("b", tts.SLIDE_GAP)]),
        ("[7] Organelles", [("c", tts.SLIDE_GAP)]),
    ]
    futures = {"[5] Cells": [done(second), done(second)], "[7] Organelles": [done(second)]}
    calls = []
    monkeypatch.setattr(tts.subprocess, "run", lambda args, **kw: calls.append(args))

    out = tmp_path / "Week 1.mp3"
    tts.encode(tmp_path / "Week 1.md", slides, futures, out, tmp_path)

    assert calls and calls[0][-1] == str(out)
    assert json.loads((tmp_path / "Week 1.chapters.json").read_text()) == [
        {"n": 5, "title": "Cells", "start_ms": 0, "end_ms": 3600},
        {"n": 7, "title": "Organelles", "start_ms": 3600, "end_ms": 5800},
    ]


def test_run_encodes_when_mp3_or_chapters_missing(tmp_path, monkeypatch):
    transcript = tmp_path / "Week 1.md"
    transcript.write_text("# Week 1\n\n## [1] Intro\n\nHello there.\n")
    audio = tmp_path / "audio"
    encoded = []
    monkeypatch.setattr(tts, "Speechify", lambda: None)
    monkeypatch.setattr(tts, "synthesize", lambda *a: b"\x00\x00")
    monkeypatch.setattr(tts, "encode", lambda path, slides, futures, out, cache: encoded.append(out) or 0.0)

    tts.run([transcript], audio, "henry")
    assert encoded == [audio / "Week 1.mp3"]

    (audio / "Week 1.mp3").touch()  # MP3 without chapters.json, as from 0.1.0: encode again
    tts.run([transcript], audio, "henry")
    assert encoded == [audio / "Week 1.mp3"] * 2

    (audio / "Week 1.chapters.json").touch()  # both exist: skip
    tts.run([transcript], audio, "henry")
    assert encoded == [audio / "Week 1.mp3"] * 2
