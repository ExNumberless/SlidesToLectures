import base64
import json
from concurrent.futures import Future
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
