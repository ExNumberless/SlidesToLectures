"""An example SlidesToLectures plugin.

Use it with `slides-to-lectures toc --input slides --plugin examples/example_plugin.py`, or name
it in slidestolectures.toml:

    plugin = "example_plugin.py"
    input = "slides"
"""

import re

from slidestolectures import Plugin


class ExamplePlugin(Plugin):
    # Context for the lecture and transcription prompts.
    course = "Introduction to Biology (BIO 101)"
    audience = "a class of first-year undergraduates"
    relevance = "for understanding living systems"
    footer = "Example University"

    def decks(self, paths):
        # Only "Week N - Topic.pdf" files, in week order (so Week 10 comes after Week 9).
        weeks = [p for p in paths if re.match(r"Week \d+", p.stem)]
        return sorted(weeks, key=lambda p: int(re.match(r"Week (\d+)", p.stem).group(1)))

    def deck_title(self, path, doc):
        # "Week 3 - Cell Division" -> "Cell Division"
        return path.stem.split(" - ", 1)[-1]

    def slide_title(self, deck, number, detected):
        # Fix a slide whose title is an image; otherwise keep the detected title.
        if number == 42:
            return "The Krebs Cycle"
        return super().slide_title(deck, number, detected)
