"""Extract each deck's text layer into a Markdown file, one "## [N] Title" section per slide."""

import pymupdf

from .layout import is_bullet_only, visual_lines
from .paths import rel


def run(plugin, decks, text_dir):
    text_dir.mkdir(parents=True, exist_ok=True)
    for deck in decks:
        sections = [f"# {deck.title} (Slides {deck.first}–{deck.last})"]
        with pymupdf.open(deck.path) as doc:
            for i, page in enumerate(doc):
                n = deck.first + i
                lines = visual_lines(page, keep_bullets=True)
                plain = [line for line in lines if not is_bullet_only(line[3])]
                title = plugin.slide_title(deck, n, plugin.detect_title(plain, page)) or "(untitled)"
                body = plugin.slide_body(lines, title, page)
                sections.append(f"## [{n}] {title}" + (f"\n\n{body}" if body else ""))
        out = text_dir / f"{deck.name}.md"
        out.write_text("\n\n".join(sections) + "\n")
        print(f"{deck.path.name} -> {rel(out)}")
