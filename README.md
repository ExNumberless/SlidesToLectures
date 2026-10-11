# SlidesToLectures

Turn a directory of slideshow PDFs into:

- **Bookmarked PDFs**: a copy of each deck with a `[N] Slide title` bookmark per topic, plus one combined PDF of every deck.
- **Slide text**: a Markdown file per deck with one `## [N] Title` section per slide, from the PDF's text layer or transcribed from slide images by Claude.
- **Lecture transcripts**: a spoken, word-for-word lecture per deck, written by Claude to cover every point on every slide.
- **Narrated audio**: an MP3 per lecture with a chapter per slide, using Speechify text-to-speech.

Slides are numbered across the whole set (from the numbers printed on them when present), so bookmarks, text, lectures and audio chapters all line up.

## Install

```bash
uv tool install "slidestolectures[tts]"
```

or `pip install "slidestolectures[tts]"`. Leave off `[tts]` if you don't need audio. Requires Python 3.11+.

- The `vision` and `lecture` steps call the Claude API: set `ANTHROPIC_API_KEY`.
- The `tts` step needs `SPEECHIFY_API_KEY` and [ffmpeg](https://ffmpeg.org/) on your `PATH`.

## Quick start

```bash
slides-to-lectures toc --input slides       # out/pdfs/ and out/combined/
slides-to-lectures text --input slides      # out/text/   (or: vision, to transcribe slide images with Claude)
slides-to-lectures lecture                  # out/lectures/
slides-to-lectures tts                      # out/audio/
```

Every command takes `--input DIR` (the slideshow PDFs), `--out DIR` (default `out`), `--plugin` and `--config`. Source PDFs are never modified. Run `slides-to-lectures <command> --help` for each command's options:

| Command | What it does | Notable options |
|---|---|---|
| `toc` | Bookmarked copy of each deck, plus a combined PDF | `--dry-run` prints the bookmarks |
| `text` | Slide text from the PDF text layer | |
| `vision` | Slide text transcribed from slide images by Claude; cached per slide | `--model` |
| `lecture` | Lecture transcript per deck from its slide text | `--model`, `--force` |
| `tts` | Narrated MP3 per lecture; audio cached per request | `--voice`, `--rps`, `--concurrency`, `--force` |

`toc`, `text` and `vision` accept deck names to process only some decks; `lecture` and `tts` accept Markdown files.

### Chapters

Next to each `<name>.mp3`, `tts` writes `<name>.chapters.json` with the same chapters as the MP3, one per `## [N] Title` section of the transcript, so other tools don't have to read them back from the audio:

```json
[
  {"n": 5, "title": "Cells", "start_ms": 0, "end_ms": 41230},
  {"n": 6, "title": "Organelles", "start_ms": 41230, "end_ms": 98770}
]
```

`n` is the slide number `N`, `title` the rest of the heading, and `start_ms` and `end_ms` the chapter's span in milliseconds, including the pause after it. It's written whenever the MP3 is, including when all its audio comes from the cache. If an MP3 exists without its `chapters.json`, such as one made by 0.1.0, `tts` encodes it again, taking its audio from the cache rather than Speechify.

## Configuration

Put a `slidestolectures.toml` in the directory you run from (or pass `--config`), so you don't have to repeat options:

```toml
plugin = "my_plugin.py"   # optional, see below
input = "slides"
output = "out"

[output_dirs]             # optional: put individual outputs elsewhere
pdfs = "bookmarked"

[settings]                # plugin settings
course = "Introduction to Biology (BIO 101)"
audience = "a class of first-year undergraduates"
footer = "Example University"
```

Settings:

| Setting | Default | Used for |
|---|---|---|
| `course` | none | What the lectures teach, in the lecture prompt |
| `audience` | `"a class"` | Who the lecture is presented to |
| `relevance` | `"in practice"` | The lecture explains why each point matters *relevance* |
| `footer` | none | Footer text on every slide, which `vision` leaves out |
| `vision_model`, `lecture_model` | `claude-opus-5-5` | Claude models |
| `tts_voice` | `henry` | Speechify voice |
| `numbering` | `"continuous"` | For decks without printed slide numbers: `"continuous"` across decks, or `"per-deck"` |
| `footer_y`, `title_min_size`, `fallback_min_size`, `fallback_max_y` | 480, 36, 24, 150 | Layout thresholds in points for a 540pt-tall slide, scaled to each page |

## Plugins

When your slides need more than settings, such as particular filenames, deck titles, or fixes for slides whose title is an image, write a plugin: a subclass of `slidestolectures.Plugin` that overrides the hooks you need. Call `super()` to wrap the default behavior.

```python
from slidestolectures import Plugin


class BiologyPlugin(Plugin):
    course = "Introduction to Biology (BIO 101)"

    def deck_title(self, path, doc):
        return path.stem.split(" - ", 1)[-1]  # "Week 3 - Cell Division" -> "Cell Division"

    def slide_title(self, deck, number, detected):
        if number == 42:
            return "The Krebs Cycle"  # this slide's title is an image
        return super().slide_title(deck, number, detected)
```

Use it with `--plugin my_plugin.py`, `--plugin my_plugin.py:BiologyPlugin`, `--plugin package.module:BiologyPlugin`, or `plugin = ...` in the config. See [examples/example_plugin.py](examples/example_plugin.py).

| Hook | Default |
|---|---|
| `decks(paths)` | Every PDF in the input directory, sorted by name |
| `deck_title(path, doc)` | The filename, with `_` as spaces |
| `output_name(deck)` | `<filename>_<first>-<last>` |
| `combined_name(decks)` / `should_combine(decks)` | `<input dir>_<first>-<last>`; combine when there's more than one deck |
| `find_slide_number(lines, page)` | The number at the end of the footer |
| `detect_title(lines, page)` / `slide_body(lines, title, page)` | Largest text near the top / the rest as Markdown |
| `slide_title(deck, number, detected)` | The detected title |
| `is_continuation(title)` | Titles with "cont'd" or "continued" get no bookmark |
| `vision_prompt()`, `lecture_system()`, `lecture_prompt(title, slides)` | Built from the settings |

## Progress and usage

`vision.run`, `lecture.run` and `tts.run` take an optional `reporter` that receives their output instead of stdout. It implements `slidestolectures.Reporter`:

- `step(name, done, total)`: progress, where `name` is the item just finished. A step starts with `done` 0.
- `log(message)`: a line the CLI would print.
- `usage(vendor, model, *, input_tokens, output_tokens, cache_read_tokens, characters, requests)`: called once per Claude call (`"anthropic"`, the model, token counts) and once per Speechify request (`"speechify"`, the voice, characters sent).

`vision.transcribe` also takes one, for usage. `vision.run` reports a step per page (`slide N`, or `slide N (cached)`), one deck at a time.

Calls come from one thread at a time. The default, `slidestolectures.PrintReporter`, prints what the CLI shows; `vision.run` defaults to `vision.SlidePrinter`, which prints each slide transcribed the way the CLI always has.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
```

With [mise](https://mise.jdx.dev/), `mise run install`, `mise run test`, `mise run lint` and `mise run build` do the same.

### Releasing

Bump `version` in `pyproject.toml`, then publish a GitHub release tagged `v<version>`. The Release workflow builds the package and publishes it to PyPI with trusted publishing.

## License

[MIT](LICENSE)
