"""The Plugin base class: every way a slideshow set can differ, as an overridable hook or setting.

Subclass Plugin and override what your slides need; call super() to wrap a default. Plain
attributes (course, footer, models, layout thresholds, ...) can also be set from the [settings]
table of slidestolectures.toml without writing a plugin at all.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import layout

# Titles marking a slide as a continuation of the previous one; these get no bookmark.
CONTINUED = re.compile(r"\bcont(?:[’'`]?d\b|\.|inued\b)", re.IGNORECASE)

# Layout thresholds are in points for a slide 540pt tall (both 4:3 and 16:9 PowerPoint exports),
# and are scaled to each page's actual height.
REFERENCE_HEIGHT = 540


@dataclass
class Deck:
    """One slideshow PDF, with its slides numbered within the whole set."""

    path: Path  # the source PDF
    index: int  # position in the set, from 0
    first: int  # number of the first slide
    last: int  # number of the last slide
    title: str = ""
    name: str = ""  # stem for output files, from Plugin.output_name
    lines: list = field(default_factory=list, repr=False)  # visual_lines() per page


class Plugin:
    """Default behavior: works on any directory of slide PDFs."""

    # --- Settings (also settable from [settings] in slidestolectures.toml) ---

    course = None  # what the lectures teach, e.g. "the Introduction to Biology course"
    audience = "a class"  # who the lecture is presented to
    relevance = "in practice"  # the lecture explains why each point matters <relevance>
    footer = None  # footer text on every slide, which transcription leaves out

    vision_model = "claude-opus-5-5"
    lecture_model = "claude-opus-5-5"
    tts_voice = "henry"

    footer_y = 480  # slide numbers sit in a footer below this
    title_min_size = 36  # titles are at least this large...
    fallback_min_size = 24  # ...or, failing that, at least this large and above fallback_max_y
    fallback_max_y = 150
    numbering = "continuous"  # for decks without printed slide numbers: "continuous" or "per-deck"

    # --- Which decks, in what order, and what they're called ---

    def decks(self, paths):
        """Choose and order the slideshow PDFs to process from those in the input directory."""
        return sorted(paths)

    def deck_title(self, path, doc):
        """A short title for the deck, used in headings and bookmarks."""
        return path.stem.replace("_", " ")

    def output_name(self, deck):
        """The stem of every file made from this deck."""
        return f"{deck.path.stem}_{deck.first}-{deck.last}"

    def combined_name(self, decks):
        """The stem of the combined PDF of every deck."""
        return f"{decks[0].path.parent.name}_{decks[0].first}-{decks[-1].last}"

    def should_combine(self, decks):
        """Whether to write a combined PDF after bookmarking every deck."""
        return len(decks) > 1

    # --- Reading slides ---

    def scale(self, page):
        return page.rect.height / REFERENCE_HEIGHT

    def find_slide_number(self, lines, page):
        """The slide number printed on the page, or None."""
        return layout.slide_number(lines, self.footer_y * self.scale(page))

    def detect_title(self, lines, page):
        """The slide's title from its text layer, or None."""
        s = self.scale(page)
        return layout.slide_title(
            lines,
            self.footer_y * s,
            self.title_min_size * s,
            self.fallback_min_size * s,
            self.fallback_max_y * s,
        )

    def slide_body(self, lines, title, page):
        """The slide's body as Markdown, without its title and footer."""
        return layout.slide_body(lines, title, self.footer_y * self.scale(page))

    def slide_title(self, deck, number, detected):
        """The title to use for slide number in deck, given the detected one (None if none was found).

        Override to fix slides whose title is an image or missing.
        """
        return detected

    def is_continuation(self, title):
        """Whether a slide continues the previous one, so it gets no bookmark of its own."""
        return bool(CONTINUED.search(title))

    # --- Prompts ---

    def vision_prompt(self):
        """The prompt sent with each slide image for transcription."""
        if self.footer:
            leave_out = f'Leave out the footer ("{self.footer}") and the slide number.'
        else:
            leave_out = "Leave out footers and the slide number."
        return f"""\
Transcribe all of the text on this presentation slide into Markdown.

- Start with the slide title as a level-2 heading ("## Title"). If the slide has no title, \
start with "## (untitled)".
- Keep the slide's structure: bulleted and numbered lists (nested where indented), tables \
as Markdown tables, and paragraphs as plain text. Rejoin lines that only wrapped because of \
the slide width.
- Include text that appears inside pictures, charts and diagrams.
- {leave_out}
- Transcribe the words exactly; don't summarize, correct, or describe the images.

Reply with the Markdown only."""

    def lecture_system(self):
        """The system prompt for writing a lecture."""
        teaching = f"an experienced instructor teaching {self.course}" if self.course else "an experienced instructor"
        return (
            f"You are {teaching}. You write the word-for-word transcript of what you say aloud "
            f"while presenting a slideshow to {self.audience}."
        )

    def lecture_prompt(self, title, slides):
        """The prompt for writing the lecture for one deck, given its title and slide Markdown."""
        return f"""\
Here is the text of the slideshow "{title}", one "## [N] Title" section per slide:

<slides>
{slides}
</slides>

Write the full lecture transcript for this slideshow.

Structure:
- Go through the slides in order. For every slide, start a section with the slide's heading \
exactly as given (for example "## [12] Key Terms (cont'd)"), followed by what you say while \
that slide is showing. Every slide gets a section, including title, quiz and closing slides.

Coverage:
- Address every item on each slide: each bullet, numbered or lettered point, table row, \
question and list entry. Don't skip or lump together items to save time; for long lists of \
ideas, you can move faster, but still name each one.
- Explain why each point matters {self.relevance}, with brief practical examples where \
they help.

Accuracy:
- Stay faithful to the slides. Don't introduce regulatory requirements, numbers, section \
citations or deadlines that aren't on the slides.
- For quiz questions, read the question and choices, give the class a moment, then give the \
answer and explain it.
- For group exercises, set up the exercise as you would in class and describe what a good \
answer would include.

Style:
- Write natural, spoken prose addressed to the class: warm, clear and conversational, the way a \
good instructor talks. Use paragraphs rather than bullet points. No stage directions other than \
brief cues in square brackets when needed, such as [pause for answers].
- Connect slides with short transitions so the lecture flows as one talk.

Reply with the transcript only, starting with the first slide's heading."""
