"""Locate volumes on mounted discs and in local folders."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Volume:
    text: Path
    title: str


def discover(root: Path) -> list[Volume]:
    if root.is_file():
        return [describe(root)] if root.name.casefold() == "text.dki" else []
    # A disc itself or a library of volumes, with an optional Data directory.
    children = list(root.iterdir())
    text_files = set(text_paths(children))
    for directory in children:
        if not directory.is_dir():
            continue
        try:
            entries = list(directory.iterdir())
        except PermissionError:
            # Drive roots can contain system directories unavailable to the reader.
            continue
        text_files.update(text_paths(entries))
    return sorted(
        (describe(path) for path in text_files),
        key=lambda volume: (volume.title.casefold(), volume.text),
    )


def text_paths(entries):
    for entry in entries:
        name = entry.name.casefold()
        if name == "text.dki" and entry.is_file():
            yield entry
        elif name == "data" and entry.is_dir():
            try:
                yield from (
                    child for child in entry.iterdir()
                    if child.name.casefold() == "text.dki" and child.is_file()
                )
            except PermissionError:
                continue


def describe(text: Path) -> Volume:
    folder = text.parent
    base = folder.parent if folder.name.casefold() == "data" else folder
    fallback = base.name or str(base)
    for directory in dict.fromkeys((folder, base)):
        for entry in directory.iterdir():
            if entry.name.casefold() != "digibib.txt" or not entry.is_file():
                continue
            try:
                with entry.open("rb") as file:
                    metadata = file.read(65536).decode("cp1252", errors="replace")
            except OSError:
                continue
            for line in metadata.splitlines():
                key, _, value = line.partition("=")
                if key.strip().casefold() == "caption" and value.strip():
                    return Volume(text, value.strip())
    return Volume(text, fallback)


def named_child(directory: Path, name: str) -> Path | None:
    """Find a disc entry without relying on the host's case sensitivity."""
    return next((entry for entry in directory.iterdir() if entry.name.casefold() == name), None)
