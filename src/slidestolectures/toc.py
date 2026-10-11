"""Write a copy of each deck with "[N] Slide title" bookmarks, plus a combined PDF of every deck.

Continuation slides ("(cont'd)", "continued", ...) and repeats of the previous title get no
bookmark. The combined PDF has deck titles as top-level bookmarks with slide titles nested beneath.
Source PDFs are never modified.
"""

import re

import pymupdf

from .paths import rel


def bookmarks(plugin, deck):
    """[[1, "[N] Title", page]] for every slide that starts a new topic."""
    toc, prev_key = [], None
    with pymupdf.open(deck.path) as doc:
        for i, (lines, page) in enumerate(zip(deck.lines, doc)):
            n = deck.first + i
            title = plugin.slide_title(deck, n, plugin.detect_title(lines, page)) or "(untitled)"
            if i > 0 and plugin.is_continuation(title):
                continue
            # Only the first slide of a run with the same title gets a bookmark.
            key = re.sub(r"[\s\-–—]+", " ", title).strip().casefold()
            if key == prev_key:
                continue
            prev_key = key
            toc.append([1, f"[{n}] {title}", i + 1])
    return toc


def save(doc, out, toc):
    doc.set_toc(toc)
    doc.set_pagemode("UseOutlines")  # open with the bookmarks panel showing
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.pdf")
    doc.save(tmp, garbage=3, deflate=True)
    tmp.replace(out)


def run(plugin, decks, pdf_dir, combined_dir, dry_run=False, combine=True):
    written = []
    for deck in decks:
        toc = bookmarks(plugin, deck)
        out = pdf_dir / f"{deck.name}.pdf"
        print(f"== {deck.path.name} -> {out.name}")
        for _, entry, _ in toc:
            print("  ", entry)
        if not dry_run:
            with pymupdf.open(deck.path) as doc:
                save(doc, out, toc)
        written.append((deck, out, toc))
    if combine and not dry_run and plugin.should_combine(decks):
        write_combined(plugin, written, combined_dir)


def write_combined(plugin, written, combined_dir):
    """Merge every deck into one PDF: deck titles at the top level, slide titles nested beneath."""
    out = combined_dir / f"{plugin.combined_name([deck for deck, _, _ in written])}.pdf"
    print(f"== combined -> {rel(out)}")
    combined = pymupdf.open()
    toc = []
    for deck, path, deck_toc in written:
        start = combined.page_count
        with pymupdf.open(path) as src:
            combined.insert_pdf(src)
        toc.append([1, f"[{deck.first}-{deck.last}] {deck.title}", start + 1])
        toc += [[2, entry, start + page] for _, entry, page in deck_toc]
    save(combined, out, toc)
    combined.close()
