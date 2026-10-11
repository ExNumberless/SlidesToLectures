"""Read slide text from a PDF page's text layer: visual lines, slide numbers, titles and body Markdown."""

import re

BULLET = re.compile(r"^[•▪*\-–]\s*")
NUMBER = re.compile(r"^\(?\d{1,2}[.)]$")


def visual_lines(page, keep_bullets=False):
    """Return [(size, y, x, text)] with spans on the same baseline merged left-to-right.

    Symbol-font bullet glyphs are dropped, or normalized to "•" with keep_bullets.
    """
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                bullet = "•" if keep_bullets else ""
                text = "".join(bullet if 0xE000 <= ord(c) <= 0xF8FF else c for c in s["text"])
                if text.strip():
                    x0, y0, x1, _ = s["bbox"]
                    spans.append((s["size"], y0, x0, x1, text))
    spans.sort(key=lambda s: (round(s[1]), s[2]))
    merged = []  # [size, y, x0, x1, text]
    for size, y, x0, x1, text in spans:
        last = merged[-1] if merged else None
        if last and abs(last[1] - y) < 4 and abs(last[0] - size) < 1:
            # Only insert a space where there is a visible gap, so "Non-Ambulatory" stays intact.
            gap = x0 - last[3]
            sep = " " if gap > 0.15 * size or last[4].endswith(" ") or text.startswith(" ") else ""
            last[3], last[4] = max(last[3], x1), last[4] + sep + text
        else:
            merged.append([size, y, x0, x1, text])
    return [(sz, y, x, " ".join(t.split())) for sz, y, x, _, t in merged]


def slide_number(lines, footer_y):
    """The number printed at the end of a footer line (below footer_y), or None."""
    for _, y, _, text in lines:
        if y > footer_y and (m := re.search(r"(\d+)$", text)):
            return int(m.group(1))
    return None


def slide_title(lines, footer_y, title_min_size, fallback_min_size, fallback_max_y):
    """The slide's title: the topmost run of the largest text, or None for a slide without text.

    Prefers text of at least title_min_size; failing that, text of at least fallback_min_size
    above fallback_max_y; failing that, the topmost text on the slide.
    """
    body = [line for line in lines if line[1] <= footer_y and not line[3].isdigit()]
    candidates = [line for line in body if line[0] >= title_min_size]
    if not candidates:
        candidates = [line for line in body if line[0] >= fallback_min_size and line[1] <= fallback_max_y]
    if not candidates:
        candidates = body
    if not candidates:
        return None
    candidates.sort(key=lambda line: (line[1], line[2]))
    size, prev_y = candidates[0][0], candidates[0][1]
    parts = []
    for sz, y, _, text in candidates:
        if abs(sz - size) >= 1:
            continue
        if parts and y - prev_y > 1.6 * size:
            break
        parts.append(text)
        prev_y = y
    title = " ".join(" ".join(parts).split())
    return re.sub(r"\s+([,.:;)])", r"\1", title)


def is_bullet_only(text):
    """True for a line holding only a list marker: bullet glyphs or a number like "1."."""
    return all(c in "•▪* " for c in text) or bool(NUMBER.match(text))


def _bottom(line):
    return line[1] + line[0]


def slide_body(lines, title, footer_y):
    """Return the slide's body as Markdown, excluding the title and footer.

    Bullets become Markdown list items (nested by indent), and wrapped lines are rejoined.
    """
    body = [line for line in lines if line[1] <= footer_y]
    # Drop the lines that make up the title (same size as the first title line, text within the title).
    title_key = " ".join(title.split()).casefold()
    title_lines = [line for line in body if line[3].casefold() in title_key and not is_bullet_only(line[3])]
    if title_lines:
        size = max(title_lines, key=lambda line: line[0])[0]
        body = [line for line in body if not (abs(line[0] - size) < 1 and line in title_lines)]

    # Standalone bullet glyphs sit on their own slightly offset line; attach each to the text it marks.
    bullets = [line for line in body if is_bullet_only(line[3])]
    texts = [line for line in body if not is_bullet_only(line[3])]
    marked = {}  # text line index -> bullet x
    numbers = {}  # text line index -> "1." etc. for numbered items
    for b in bullets:
        near = [
            (abs(_bottom(t) - _bottom(b)), i)
            for i, t in enumerate(texts)
            if t[2] > b[2] and abs(_bottom(t) - _bottom(b)) < 0.6 * t[0] and i not in marked
        ]
        if near:
            i = min(near)[1]
            marked[i] = b[2]
            if NUMBER.match(b[3]):
                numbers[i] = b[3].strip("()").replace(")", ".")
    # Inline bullets ("• text") mark their own line.
    for i, t in enumerate(texts):
        if BULLET.match(t[3]) and i not in marked:
            marked[i] = t[2]

    levels = sorted({round(x / 10) for x in marked.values()})
    items = []  # [bullet level or None, size, x, last y, text]
    for i, (size, y, x, text) in enumerate(texts):
        text = BULLET.sub("", text) if i in marked else text
        last = items[-1] if items else None
        continues = (
            last
            and i not in marked
            and abs(last[1] - size) < 1
            and abs(last[2] - x) < 6
            and 0 < y - last[3] < 1.6 * size
        )
        if continues:
            sep = "" if last[4].endswith("-") and not last[4].endswith(" -") else " "
            last[3], last[4] = y, last[4] + sep + text
        else:
            level = levels.index(round(marked[i] / 10)) if i in marked else None
            if i in numbers:
                text = f"{numbers[i]} {text}"
            elif i in marked:
                text = f"- {text}"
            items.append([level, size, x, y, text])

    out = []
    for level, _, _, _, text in items:
        text = re.sub(r"\s+([,.:;)])", r"\1", text)
        out.append(("", text) if level is None else ("list", "  " * level + text))
    # Paragraphs are separated by blank lines; consecutive list items stay together.
    md = []
    for kind, text in out:
        if md and not (kind == "list" and md[-1][0] == "list"):
            md.append(("", ""))
        md.append((kind, text))
    return "\n".join(t for _, t in md)
