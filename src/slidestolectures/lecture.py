"""Write a spoken lecture transcript for each deck's slide text with Claude.

The lecture follows the slides in order, one "## [N] Title" section per slide, and covers every
item on each slide. After generating, every slide is checked for a section, with a warning for any
that are missing. Existing transcripts are skipped unless force is set.

Needs ANTHROPIC_API_KEY (or another credential the Anthropic SDK can find).
"""

import re

from .paths import rel

SLIDE_HEADING = re.compile(r"^## \[(\d+)\]", re.MULTILINE)


def generate(client, plugin, model, path):
    text = path.read_text()
    m = re.match(r"# (.+)\n", text)
    title = m.group(1) if m else path.stem
    slides = SLIDE_HEADING.findall(text)

    with client.beta.messages.stream(
        model=model,
        max_tokens=128000,
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=plugin.lecture_system(),
        messages=[{"role": "user", "content": plugin.lecture_prompt(title, text)}],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason != "end_turn":
        raise SystemExit(f"{path.name}: stopped with {response.stop_reason}")
    lecture = "".join(b.text for b in response.content if b.type == "text").strip()

    missing = sorted(set(slides) - set(SLIDE_HEADING.findall(lecture)), key=int)
    if missing:
        print(f"  warning: no section for slide(s) {', '.join(missing)}")
    u = response.usage
    print(f"  {u.input_tokens} input / {u.output_tokens} output tokens")
    return f"# Lecture: {title}\n\n{lecture}\n"


def run(plugin, files, lecture_dir, model=None, force=False):
    """Write lecture_dir/<name>.md for each slide-text Markdown file in files."""
    import anthropic

    lecture_dir.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic()
    for f in files:
        out = lecture_dir / f.name
        if out.exists() and not force:
            print(f"skip {rel(out)} (exists; use --force to regenerate)")
            continue
        print(f"== {f.name}")
        out.write_text(generate(client, plugin, model or plugin.lecture_model, f))
        print(f"-> {rel(out)}")
