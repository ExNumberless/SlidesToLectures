"""Progress and usage reporting for lecture.run and tts.run.

Pass any object with these three methods as `reporter` to send progress, messages and API usage
somewhere other than stdout. The pipeline calls a reporter from one thread at a time, so it
doesn't need its own locking.
"""

import time
from typing import Protocol


class Reporter(Protocol):
    def step(self, name: str, done: int, total: int) -> None:
        """Progress within a step: name is the item just finished, done of total.

        A step starts with a call where done is 0.
        """

    def log(self, message: str) -> None:
        """A line of output for the user."""

    def usage(
        self,
        vendor: str,
        model: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        characters: int = 0,
        requests: int = 1,
    ) -> None:
        """Billable usage: vendor is "anthropic" (model is the Claude model) or "speechify"
        (model is the voice). Called once per Claude call and once per Speechify request."""


class PrintReporter:
    """The CLI's reporter: prints messages and progress with an ETA, and ignores usage."""

    def __init__(self):
        self.start = time.time()

    def step(self, name, done, total):
        if done == 0:
            self.start = time.time()
            return
        eta = (time.time() - self.start) / done * (total - done)
        print(f"[{done}/{total}] {name}  (ETA {eta / 60:.0f} min)", flush=True)

    def log(self, message):
        print(message, flush=True)

    def usage(
        self,
        vendor,
        model,
        *,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        characters=0,
        requests=1,
    ):
        pass
