"""Load slidestolectures.toml and the plugin it names.

    plugin = "my_plugin:MyPlugin"   # module:Class, path/to/file.py[:Class], or omit for the defaults
    input = "slides"                # directory of slideshow PDFs
    output = "out"                  # base directory for everything generated

    [output_dirs]                   # optional: override individual output directories
    pdfs = "out/pdfs"               # bookmarked copies of each deck
    combined = "out/combined"       # all decks in one PDF
    text = "out/text"               # slide text, one Markdown file per deck
    lectures = "out/lectures"       # lecture transcripts
    audio = "out/audio"             # narrated MP3s

    [settings]                      # plugin attributes, e.g.
    course = "the Introduction to Biology course"
    footer = "Example University"

Relative paths are resolved against the directory holding the config file.
"""

import importlib
import importlib.util
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .plugin import Plugin

CONFIG_NAME = "slidestolectures.toml"
OUTPUT_DIRS = {"pdfs": "pdfs", "combined": "combined", "text": "text", "lectures": "lectures", "audio": "audio"}


@dataclass
class Config:
    plugin: Plugin
    input: Path | None
    pdfs: Path
    combined: Path
    text: Path
    lectures: Path
    audio: Path


def load(config_path=None, plugin_spec=None, input_dir=None, output_dir=None):
    """Read the config file (if any), with command-line values taking precedence."""
    if config_path is None and Path(CONFIG_NAME).exists():
        config_path = Path(CONFIG_NAME)
    data, base = {}, Path.cwd()
    if config_path is not None:
        config_path = Path(config_path)
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        base = config_path.resolve().parent
    known = {"plugin", "input", "output", "output_dirs", "settings"}
    if unknown := set(data) - known:
        raise SystemExit(f"{config_path}: unknown key(s) {', '.join(sorted(unknown))}")

    plugin = load_plugin(plugin_spec or data.get("plugin"), base if plugin_spec is None else Path.cwd())
    for key, value in data.get("settings", {}).items():
        if key.startswith("_") or not hasattr(plugin, key) or callable(getattr(plugin, key)):
            raise SystemExit(f"{config_path}: unknown setting {key!r}")
        setattr(plugin, key, value)

    def resolve(value, relative_to):
        return value if value is None else (relative_to / Path(value).expanduser())

    input_dir = resolve(input_dir, Path.cwd()) or resolve(data.get("input"), base)
    output = resolve(output_dir, Path.cwd()) or resolve(data.get("output", "out"), base)
    dirs = data.get("output_dirs", {})
    if unknown := set(dirs) - set(OUTPUT_DIRS):
        raise SystemExit(f"{config_path}: unknown output_dirs key(s) {', '.join(sorted(unknown))}")
    paths = {
        key: (output / default if output_dir is not None or key not in dirs else resolve(dirs[key], base))
        for key, default in OUTPUT_DIRS.items()
    }
    return Config(plugin=plugin, input=input_dir, **paths)


def load_plugin(spec, base):
    """Instantiate the plugin named by spec ("module:Class", "file.py[:Class]"), or the default Plugin."""
    if not spec:
        return Plugin()
    target, _, class_name = spec.partition(":")
    if target.endswith(".py"):
        path = (base / target).resolve()
        if not path.exists():
            raise SystemExit(f"plugin file not found: {path}")
        module_spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[path.stem] = module
        module_spec.loader.exec_module(module)
    else:
        sys.path.insert(0, str(base))
        try:
            module = importlib.import_module(target)
        finally:
            sys.path.remove(str(base))

    if class_name:
        cls = getattr(module, class_name, None)
        if cls is None:
            raise SystemExit(f"plugin {spec!r}: no class {class_name!r} in {module.__name__}")
    else:
        found = [
            obj
            for obj in vars(module).values()
            if isinstance(obj, type)
            and issubclass(obj, Plugin)
            and obj is not Plugin
            and obj.__module__ == module.__name__
        ]
        if len(found) != 1:
            raise SystemExit(f"plugin {spec!r}: expected one Plugin subclass in {module.__name__}, found {len(found)}")
        cls = found[0]
    if not (isinstance(cls, type) and issubclass(cls, Plugin)):
        raise SystemExit(f"plugin {spec!r}: {cls!r} is not a subclass of slidestolectures.Plugin")
    return cls()
