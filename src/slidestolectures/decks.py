"""Find the slideshow PDFs in a directory and number their slides across the whole set."""

import sys

import pymupdf

from .layout import visual_lines
from .plugin import Deck


def load_decks(plugin, input_dir):
    """Return a Deck for every slideshow in input_dir, in the plugin's order.

    Slides are numbered from the numbers printed on them when those are consistent within a deck.
    Otherwise numbering continues from the previous deck (or restarts at 1 with
    numbering = "per-deck").
    """
    paths = plugin.decks(list(input_dir.glob("*.pdf")))
    if not paths:
        raise SystemExit(f"no slideshow PDFs in {input_dir}")
    decks, next_number = [], 1
    for index, path in enumerate(paths):
        with pymupdf.open(path) as doc:
            lines = [visual_lines(page) for page in doc]
            numbers = [plugin.find_slide_number(page_lines, page) for page_lines, page in zip(lines, doc)]
            offsets = {n - i for i, n in enumerate(numbers) if n is not None}
            if len(offsets) == 1:
                first = offsets.pop()
            else:
                if offsets:
                    print(f"{path.name}: inconsistent slide numbering; numbering by page", file=sys.stderr)
                first = next_number if plugin.numbering == "continuous" else 1
            deck = Deck(path=path, index=index, first=first, last=first + doc.page_count - 1, lines=lines)
            deck.title = plugin.deck_title(path, doc)
        deck.name = plugin.output_name(deck)
        decks.append(deck)
        next_number = deck.last + 1
    return decks


def select(decks, names):
    """The decks matching names (source filenames or output stems), or all decks if none are given."""
    if not names:
        return decks
    chosen = []
    for name in names:
        matches = [d for d in decks if name in (d.path.name, d.path.stem, d.name)]
        if not matches:
            raise SystemExit(f"no deck named {name!r}")
        chosen += matches
    return chosen
