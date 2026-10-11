"""Command-line interface: slides-to-lectures <command> [options]."""

import argparse
from pathlib import Path

from . import __version__, config
from .decks import load_decks, select

COMMANDS = {
    "toc": "add slide-title bookmarks to a copy of each deck, and combine all decks into one PDF",
    "text": "extract each deck's text layer into Markdown, one section per slide",
    "vision": "transcribe each slide image into Markdown with Claude (instead of text)",
    "lecture": "write a spoken lecture transcript for each deck's Markdown with Claude",
    "tts": "narrate each lecture transcript into an MP3 with Speechify",
}


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, help=f"config file (default: ./{config.CONFIG_NAME} if present)")
    common.add_argument("--plugin", help="plugin as module:Class or path/to/file.py[:Class]")
    common.add_argument("--input", type=Path, help="directory of slideshow PDFs")
    common.add_argument("--out", type=Path, help="base directory for generated files (default: out)")

    p = argparse.ArgumentParser(
        prog="slides-to-lectures",
        description="Turn slideshow PDFs into bookmarked PDFs, slide text, lecture transcripts and narrated audio.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="command")
    cmd = {name: sub.add_parser(name, parents=[common], help=text, description=text) for name, text in COMMANDS.items()}

    for name in ("toc", "text", "vision"):
        cmd[name].add_argument("decks", nargs="*", help="only these decks (source filename or stem)")
    cmd["toc"].add_argument("--dry-run", action="store_true", help="print the bookmarks without writing PDFs")
    cmd["vision"].add_argument("--model", help="Claude model (default: the plugin's vision_model)")

    cmd["lecture"].add_argument(
        "files", nargs="*", type=Path, help="slide Markdown files (default: all in the text dir)"
    )
    cmd["lecture"].add_argument("--model", help="Claude model (default: the plugin's lecture_model)")
    cmd["lecture"].add_argument("--force", action="store_true", help="regenerate existing transcripts")

    cmd["tts"].add_argument(
        "files", nargs="*", type=Path, help="lecture transcripts (default: all in the lectures dir)"
    )
    cmd["tts"].add_argument("--voice", help="Speechify voice (default: the plugin's tts_voice)")
    cmd["tts"].add_argument("--rps", type=float, help="requests per second (default: 20, the Starter plan; Free: 1)")
    cmd["tts"].add_argument("--concurrency", type=int, help="concurrent requests (default: 15; Free: 3)")
    cmd["tts"].add_argument("--force", action="store_true", help="regenerate existing MP3s")
    return p


def markdown_files(names, directory):
    """The named Markdown files (paths, or names within directory), or every one in directory."""
    if not names:
        files = sorted(directory.glob("*.md"))
        if not files:
            raise SystemExit(f"no Markdown files in {directory}")
        return files
    files = []
    for name in names:
        path = name if name.exists() else directory / name.with_suffix(".md").name
        if not path.exists():
            raise SystemExit(f"not found: {name}")
        files.append(path)
    return files


def main(argv=None):
    args = parser().parse_args(argv)
    cfg = config.load(args.config, args.plugin, args.input, args.out)
    plugin = cfg.plugin

    if args.command in ("toc", "text", "vision"):
        if cfg.input is None:
            raise SystemExit(f"no input directory: pass --input or set input in {config.CONFIG_NAME}")
        decks = load_decks(plugin, cfg.input)
        chosen = select(decks, args.decks)
        if args.command == "toc":
            from . import toc

            # Only combine when every deck was bookmarked in this run.
            toc.run(plugin, chosen, cfg.pdfs, cfg.combined, args.dry_run, combine=len(chosen) == len(decks))
        elif args.command == "text":
            from . import text

            text.run(plugin, chosen, cfg.text)
        else:
            from . import vision

            vision.run(plugin, chosen, cfg.text, args.model)
    elif args.command == "lecture":
        from . import lecture

        lecture.run(plugin, markdown_files(args.files, cfg.text), cfg.lectures, args.model, args.force)
    else:
        try:
            from . import tts
        except ImportError:
            raise SystemExit("tts needs the Speechify SDK: install slidestolectures[tts]") from None

        options = {k: v for k, v in (("rps", args.rps), ("concurrency", args.concurrency)) if v is not None}
        tts.run(
            markdown_files(args.files, cfg.lectures), cfg.audio, args.voice or plugin.tts_voice, args.force, **options
        )
