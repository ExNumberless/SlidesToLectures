import pymupdf
import pytest

from slidestolectures import Plugin, cli, config
from slidestolectures.decks import load_decks, select


def test_numbering_uses_printed_numbers_then_continues(slides_dir):
    decks = load_decks(Plugin(), slides_dir)
    assert [(d.first, d.last) for d in decks] == [(5, 7), (8, 9)]
    assert [d.name for d in decks] == ["Week 1 - Cells_5-7", "Week 2 - Genetics_8-9"]
    assert decks[0].title == "Week 1 - Cells"


def test_per_deck_numbering(slides_dir):
    plugin = Plugin()
    plugin.numbering = "per-deck"
    assert [(d.first, d.last) for d in load_decks(plugin, slides_dir)] == [(5, 7), (1, 2)]


def test_select(slides_dir):
    decks = load_decks(Plugin(), slides_dir)
    assert select(decks, ["Week 2 - Genetics.pdf"]) == decks[1:]
    assert select(decks, []) == decks
    with pytest.raises(SystemExit):
        select(decks, ["missing"])


def test_toc_writes_bookmarks_and_combined_pdf(slides_dir, tmp_path):
    out = tmp_path / "out"
    cli.main(["toc", "--input", str(slides_dir), "--out", str(out)])

    with pymupdf.open(out / "pdfs" / "Week 1 - Cells_5-7.pdf") as doc:
        # The continuation slide gets no bookmark of its own.
        assert doc.get_toc() == [[1, "[5] Cells", 1], [1, "[7] Organelles", 3]]
    with pymupdf.open(out / "combined" / "slides_5-9.pdf") as doc:
        assert doc.page_count == 5
        assert doc.get_toc() == [
            [1, "[5-7] Week 1 - Cells", 1],
            [2, "[5] Cells", 1],
            [2, "[7] Organelles", 3],
            [1, "[8-9] Week 2 - Genetics", 4],
            [2, "[8] Genetics", 4],
            [2, "[9] Inheritance", 5],
        ]
    assert (slides_dir / "Week 1 - Cells.pdf").exists()  # sources are left alone


def test_toc_dry_run_writes_nothing(slides_dir, tmp_path, capsys):
    cli.main(["toc", "--dry-run", "--input", str(slides_dir), "--out", str(tmp_path / "out")])
    assert "[7] Organelles" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_text_extracts_markdown(slides_dir, tmp_path):
    out = tmp_path / "out"
    cli.main(["text", "--input", str(slides_dir), "--out", str(out)])
    md = (out / "text" / "Week 1 - Cells_5-7.md").read_text()
    assert md.startswith("# Week 1 - Cells (Slides 5–7)\n\n## [5] Cells\n\n- The basic unit of life\n")
    assert "## [7] Organelles\n\n- Nucleus\n- Mitochondria\n" in md


def test_plugin_hooks_from_config(slides_dir, tmp_path, monkeypatch):
    (tmp_path / "my_plugin.py").write_text(
        "from slidestolectures import Plugin\n"
        "class MyPlugin(Plugin):\n"
        "    def deck_title(self, path, doc):\n"
        "        return path.stem.split(' - ')[1]\n"
        "    def slide_title(self, deck, number, detected):\n"
        "        return 'Overridden' if number == 8 else detected\n"
    )
    (tmp_path / "slidestolectures.toml").write_text(
        'plugin = "my_plugin.py"\ninput = "slides"\n[settings]\nfooter = "Example University"\n'
    )
    monkeypatch.chdir(tmp_path)
    cli.main(["toc"])
    with pymupdf.open(tmp_path / "out" / "combined" / "slides_5-9.pdf") as doc:
        toc = doc.get_toc()
    assert [1, "[5-7] Cells", 1] in toc
    assert [2, "[8] Overridden", 4] in toc


def test_config_rejects_unknown_setting(tmp_path):
    path = tmp_path / "slidestolectures.toml"
    path.write_text("[settings]\nnot_a_setting = 1\n")
    with pytest.raises(SystemExit, match="unknown setting"):
        config.load(path)


def test_prompts_use_settings():
    plugin = Plugin()
    assert "Leave out footers and the slide number." in plugin.vision_prompt()
    assert plugin.lecture_system().startswith("You are an experienced instructor. ")
    plugin.footer, plugin.course = "Example University", "BIO 101"
    assert 'Leave out the footer ("Example University")' in plugin.vision_prompt()
    assert plugin.lecture_system().startswith("You are an experienced instructor teaching BIO 101. ")
    assert "<slides>\nSLIDES\n</slides>" in plugin.lecture_prompt("Title", "SLIDES")
