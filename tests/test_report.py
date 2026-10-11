from types import SimpleNamespace

import anthropic

from slidestolectures import Plugin, PrintReporter, lecture


def test_print_reporter_prints_like_the_cli(capsys):
    r = PrintReporter()
    r.step("speechify", 0, 2)
    r.step("lecture 1 [1]: 10 chars, 1s audio", 1, 2)
    r.log("-> audio/a.mp3 (0.1 min)")
    r.usage("speechify", "henry", characters=10)
    assert capsys.readouterr().out == (
        "[1/2] lecture 1 [1]: 10 chars, 1s audio  (ETA 0 min)\n-> audio/a.mp3 (0.1 min)\n"
    )


class FakeStream:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return SimpleNamespace(
            model="claude-test",
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=self.text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=None),
        )


class FakeAnthropic:
    def __init__(self):
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: FakeStream("## [1] Cells\n\nHello.")))


def test_lecture_reports_logs_and_usage(tmp_path, monkeypatch, reporter):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "Cells.md"
    src.write_text("# Cells\n\n## [1] Cells\n\n- Life\n\n## [2] More\n\n- Stuff\n")

    lecture.run(Plugin(), [src], tmp_path / "lectures", model="claude-test", reporter=reporter)

    assert reporter.of("usage") == [
        ("anthropic", "claude-test", {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 0})
    ]
    assert reporter.of("log") == [
        ("== Cells.md",),
        ("  warning: no section for slide(s) 2",),
        ("  100 input / 20 output tokens",),
        ("-> lectures/Cells.md",),
    ]

    lecture.run(Plugin(), [src], tmp_path / "lectures", reporter=reporter)
    assert reporter.of("log")[-1] == ("skip lectures/Cells.md (exists; use --force to regenerate)",)
    assert len(reporter.of("usage")) == 1
