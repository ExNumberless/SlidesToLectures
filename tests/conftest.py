import pymupdf
import pytest


def make_deck(path, slides, numbers=None, footer="Example University"):
    """Write a 720x540 slide PDF: slides is [(title, [bullet, ...])], numbers the printed slide numbers."""
    doc = pymupdf.open()
    for i, (title, bullets) in enumerate(slides):
        page = doc.new_page(width=720, height=540)
        page.insert_text((40, 70), title, fontsize=40)
        for j, bullet in enumerate(bullets):
            page.insert_text((60, 160 + 40 * j), f"- {bullet}", fontsize=24)
        if numbers is not None:
            page.insert_text((40, 520), f"{footer}   {numbers[i]}", fontsize=12)
    doc.save(path)
    return path


@pytest.fixture
def slides_dir(tmp_path):
    """Two decks: the first with printed numbers 5-7, the second without numbers."""
    d = tmp_path / "slides"
    d.mkdir()
    make_deck(
        d / "Week 1 - Cells.pdf",
        [
            ("Cells", ["The basic unit of life"]),
            ("Cells (cont'd)", ["Prokaryotes", "Eukaryotes"]),
            ("Organelles", ["Nucleus", "Mitochondria"]),
        ],
        numbers=[5, 6, 7],
    )
    make_deck(d / "Week 2 - Genetics.pdf", [("Genetics", ["DNA"]), ("Inheritance", ["Dominant", "Recessive"])])
    return d
