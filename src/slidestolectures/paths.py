from pathlib import Path


def rel(path):
    """path relative to the working directory when it's inside it, for messages."""
    try:
        return path.resolve().relative_to(Path.cwd())
    except ValueError:
        return path
