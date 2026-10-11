"""Turn slideshow PDFs into bookmarked PDFs, slide text, lecture transcripts and narrated audio."""

from importlib.metadata import version

from .plugin import Deck, Plugin

__version__ = version("slidestolectures")
__all__ = ["Deck", "Plugin", "__version__"]
