"""Narrate each lecture transcript with Speechify text-to-speech into an MP3.

Each slide section is split into requests of at most MAX_CHARS characters (at paragraph, then
sentence, breaks). Requests for all lectures share one thread pool, with progress logged as each
finishes. Requests are spaced to stay under the plan's rate limit, and the spacing widens when
the API returns 429 and narrows again after successes. Rate limits and server errors are retried
with exponential backoff, honoring Retry-After; running out of credit stops the run. Audio is
joined with short pauses into one MP3 per lecture, with a chapter per slide. The chapters are
also written to <name>.chapters.json beside the MP3.

Audio for each request is cached in <audio dir>/.cache/, keyed by its text and voice, so re-runs
only synthesize what's missing and editing a transcript only redoes the changed parts. Existing
MP3s are skipped unless force is set, or their chapters.json is missing.

Needs SPEECHIFY_API_KEY and ffmpeg.
"""

import base64
import hashlib
import json
import random
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from speechify import Speechify
from speechify.core.api_error import ApiError
from speechify.core.request_options import RequestOptions

from .paths import rel
from .report import PrintReporter

MODEL = "simba-3.2"
RPS, CONCURRENCY = 20, 15  # Starter plan limits; Free allows 1 req/s and 3 concurrent
MAX_CHARS = 1900  # the speech endpoint accepts 2,000 characters per request
MAX_ATTEMPTS = 8
RATE = 24000  # pcm_24000: 24 kHz mono 16-bit little-endian
CHUNK_GAP, PAUSE_GAP, SLIDE_GAP = 0.4, 2.5, 1.2  # seconds of silence

SECTION = re.compile(r"^## (\[\d+\].*)$", re.MULTILINE)
NUMBERED = re.compile(r"\[(\d+)\]\s*(.*)")  # a SECTION title: "[N] Title"
PAUSE = "\x00"  # marks a [pause ...] cue: becomes silence between requests


class Fatal(Exception):
    """An error that retrying won't fix, such as running out of credit."""


def speakable(text):
    """Turn transcript Markdown into plain text to read aloud."""
    text = re.sub(r"\[pause[^\]]*\]", PAUSE, text, flags=re.IGNORECASE)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [link](url) -> link
    text = re.sub(r"\[[^\]]*\]", "", text)  # any other bracketed stage cue
    text = re.sub(r"(\*\*|__|\*|_)(\S.*?\S|\S)\1", r"\2", text)  # bold / italics
    return text.strip()


def split_long(para):
    """Split a paragraph longer than MAX_CHARS at sentence ends."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", para):
        if current and len(current) + 1 + len(sentence) > MAX_CHARS:
            pieces.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    return pieces + [current] if current else pieces


def segments(body):
    """Split a slide's text into [(text, gap after)] requests of at most MAX_CHARS characters."""
    out = []
    for part in speakable(body).split(PAUSE):
        paras = [p for raw in part.split("\n\n") if (p := " ".join(raw.split()))]
        current = ""
        for para in (piece for p in paras for piece in split_long(p)):
            if current and len(current) + 2 + len(para) > MAX_CHARS:
                out.append([current, CHUNK_GAP])
                current = ""
            current = f"{current}\n\n{para}".strip()
        if current:
            out.append([current, CHUNK_GAP])
        if out:
            out[-1][1] = PAUSE_GAP
    if out:
        out[-1][1] = SLIDE_GAP
    return [tuple(s) for s in out]


class Progress:
    """Counts finished requests and passes output to a reporter, one thread at a time."""

    def __init__(self, total, reporter):
        self.total, self.done, self.reporter = total, 0, reporter
        self.lock = threading.Lock()
        reporter.step("speechify", 0, total)

    def log(self, msg):
        with self.lock:
            self.reporter.log(msg)

    def step(self, msg):
        with self.lock:
            self.done += 1
            self.reporter.step(msg, self.done, self.total)

    def usage(self, voice, characters):
        with self.lock:
            self.reporter.usage("speechify", voice, characters=characters)


class Limiter:
    """Spaces requests to a target rate, slowing down on 429s and speeding back up on success."""

    def __init__(self, rps):
        self.base = self.interval = 1 / rps
        self.next = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next)
            self.next = at + self.interval
        time.sleep(at - now)

    def throttled(self):
        with self.lock:
            self.interval = min(self.interval * 2, 10.0)

    def succeeded(self):
        with self.lock:
            self.interval = max(self.base, self.interval * 0.9)


def retry_delay(err, attempt):
    """Seconds to wait before retrying: exponential backoff with jitter, at least Retry-After."""
    headers = {k.lower(): v for k, v in (err.headers or {}).items()} if isinstance(err, ApiError) else {}
    try:
        retry_after = float(headers["retry-after"])
    except (KeyError, ValueError):
        retry_after = 0.0
    return max(retry_after, min(60, 2**attempt)) + random.uniform(0, 1)


def synthesize(client, limiter, cache_dir, text, voice, label, progress, stop):
    """Return raw PCM for text, from the cache when possible."""
    key = hashlib.sha256(f"speechify|{MODEL}|{voice}|{text}".encode()).hexdigest()[:16]
    cached = cache_dir / f"{key}.pcm"
    if cached.exists():
        progress.step(f"{label} (cached)")
        return cached.read_bytes()
    for attempt in range(MAX_ATTEMPTS):
        if stop.is_set():
            raise Fatal("stopped")
        limiter.wait()
        try:
            r = client.audio.speech(
                input=text,
                voice_id=voice,
                model=MODEL,
                output_format="pcm_24000",
                request_options=RequestOptions(max_retries=0, timeout_in_seconds=120),
            )
            progress.usage(voice, len(text))
            pcm = base64.b64decode(r.audio_data)
            limiter.succeeded()
            break
        except Exception as e:
            status = e.status_code if isinstance(e, ApiError) else None
            if status in (401, 402, 403):
                stop.set()
                raise Fatal(f"{label}: HTTP {status}: {getattr(e, 'body', e)}") from e
            if status is not None and status < 500 and status not in (408, 409, 429):
                raise
            if attempt == MAX_ATTEMPTS - 1:
                raise
            if status == 429:
                limiter.throttled()
            wait = retry_delay(e, attempt)
            progress.log(
                f"  {label}: {status or type(e).__name__}, retry {attempt + 1}/{MAX_ATTEMPTS - 1} in {wait:.0f}s"
            )
            time.sleep(wait)
    cached.write_bytes(pcm)
    progress.step(f"{label}: {len(text)} chars, {len(pcm) / (2 * RATE):.0f}s audio")
    return pcm


def silence(seconds):
    return b"\x00\x00" * int(RATE * seconds)


def encode(path, slides, futures, out, cache_dir):
    """Join a lecture's audio into an MP3 with one chapter per slide, and write its chapters.json."""
    pcm, chapters = bytearray(), []
    for title, segs in slides:
        start = len(pcm)
        for (_, gap), future in zip(segs, futures[title]):
            pcm += future.result() + silence(gap)
        chapters.append((title, start, len(pcm)))

    ms = lambda n: n * 1000 // (2 * RATE)  # byte offset -> milliseconds
    meta = [";FFMETADATA1", f"title=Lecture: {path.stem}"]
    for title, start, end in chapters:
        title = re.sub(r"([=;#\\])", r"\\\1", title)
        meta += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={ms(start)}",
            f"END={ms(end)}",
            f"title={title}",
        ]
    meta_file = cache_dir / f"{path.stem}.ffmeta"
    meta_file.write_text("\n".join(meta) + "\n")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "s16le",
            "-ar",
            str(RATE),
            "-ac",
            "1",
            "-i",
            "-",
            "-i",
            str(meta_file),
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-b:a",
            "64k",
            str(out),
        ],
        input=bytes(pcm),
        check=True,
    )
    chapters_json = []
    for title, start, end in chapters:
        n, name = NUMBERED.match(title).groups()
        chapters_json.append({"n": int(n), "title": name.strip(), "start_ms": ms(start), "end_ms": ms(end)})
    out.with_suffix(".chapters.json").write_text(json.dumps(chapters_json, indent=2) + "\n")
    return ms(len(pcm)) / 60000


def run(files, audio_dir, voice, force=False, rps=RPS, concurrency=CONCURRENCY, reporter=None):
    """Write audio_dir/<name>.mp3 for each lecture transcript in files.

    reporter (a report.Reporter) receives output, progress and character usage; by default it prints.
    """
    reporter = reporter or PrintReporter()
    cache_dir = audio_dir / ".cache"
    lectures = []  # (path, out, [(title, [(text, gap)])])
    for f in files:
        out = audio_dir / f"{f.stem}.mp3"
        if out.exists() and out.with_suffix(".chapters.json").exists() and not force:
            reporter.log(f"skip {rel(out)} (exists; use --force to regenerate)")
            continue
        parts = SECTION.split(f.read_text())[1:]  # [title, body, title, body, ...]
        lectures.append((f, out, [(t, segments(b)) for t, b in zip(parts[::2], parts[1::2])]))
    if not lectures:
        return

    total = sum(len(segs) for *_, slides in lectures for _, segs in slides)
    chars = sum(len(text) for *_, slides in lectures for _, segs in slides for text, _ in segs)
    reporter.log(f"{len(lectures)} lecture(s), {total} requests, {chars:,} characters, voice {voice}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    client, limiter = Speechify(), Limiter(rps)
    progress, stop = Progress(total, reporter), threading.Event()
    with ThreadPoolExecutor(concurrency) as pool:
        # Queue every request up front so the pool stays busy across lecture boundaries.
        queued = []
        for number, (path, out, slides) in enumerate(lectures, 1):
            futures = {
                title: [
                    pool.submit(
                        synthesize,
                        client,
                        limiter,
                        cache_dir,
                        text,
                        voice,
                        f"lecture {number} {title.split()[0]}",
                        progress,
                        stop,
                    )
                    for text, _ in segs
                ]
                for title, segs in slides
            }
            queued.append((path, out, slides, futures))
        try:
            for path, out, slides, futures in queued:
                minutes = encode(path, slides, futures, out, cache_dir)
                progress.log(f"-> {rel(out)} ({minutes:.1f} min)")
        except Exception as e:
            stop.set()
            pool.shutdown(cancel_futures=True)
            progress.log(f"stopped: {e}\nFinished audio is cached; re-run to continue.")
            raise
