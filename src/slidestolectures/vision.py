"""Transcribe each slide image with Claude into a Markdown file per deck.

Each slide is rendered to PNG and sent to the Claude API, which reads the text the way a person
would (including text inside images, tables and diagrams). Per-slide results are cached in
<text dir>/.cache/, so re-runs only call the API for slides not yet transcribed; delete a cached
file to redo that slide.

Needs ANTHROPIC_API_KEY (or another credential the Anthropic SDK can find).
"""

import asyncio
import base64
import re

import pymupdf

from .paths import rel

CONCURRENCY = 8
ZOOM = 2  # 720x540pt slides render at 1440x1080px


def render(page):
    pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM))
    return base64.standard_b64encode(pix.tobytes("png")).decode()


async def transcribe(client, sem, model, prompt, image, label):
    async with sem:
        response = await client.beta.messages.create(
            model=model,
            max_tokens=16000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"{label}: stopped with {response.stop_reason}")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    print(f"  {label}")
    return text


async def process(client, sem, plugin, model, deck, text_dir):
    cache = text_dir / ".cache" / deck.name
    cache.mkdir(parents=True, exist_ok=True)
    prompt = plugin.vision_prompt()
    print(f"== {deck.path.name}")

    with pymupdf.open(deck.path) as doc:

        async def slide(i):
            n = deck.first + i
            cached = cache / f"{n}.md"
            if not cached.exists():
                text = await transcribe(client, sem, model, prompt, render(doc[i]), f"slide {n}")
                cached.write_text(text + "\n")
            text = cached.read_text().strip()
            if text.startswith("## (untitled)") and (title := plugin.slide_title(deck, n, None)):
                text = f"## {title}" + text.removeprefix("## (untitled)")
            # Number each slide's heading so it lines up with the PDF bookmarks.
            if text.startswith("## "):
                return re.sub(r"^## ", f"## [{n}] ", text, count=1)
            return f"## [{n}]\n\n{text}"

        slides = await asyncio.gather(*(slide(i) for i in range(doc.page_count)))
    out = text_dir / f"{deck.name}.md"
    out.write_text("\n\n".join([f"# {deck.title} (Slides {deck.first}–{deck.last})", *slides]) + "\n")
    print(f"-> {rel(out)}")


async def _run(plugin, decks, text_dir, model):
    import anthropic

    sem = asyncio.Semaphore(CONCURRENCY)
    async with anthropic.AsyncAnthropic() as client:
        for deck in decks:
            await process(client, sem, plugin, model, deck, text_dir)


def run(plugin, decks, text_dir, model=None):
    asyncio.run(_run(plugin, decks, text_dir, model or plugin.vision_model))
