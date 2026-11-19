"""Read the publisher's indented contents and optional page map."""
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from struct import iter_unpack

from .library import named_child


@dataclass(frozen=True)
class Entry:
    index: int
    title: str
    record: int | None


def record_map(data: bytes, size: int, count: int) -> list[int] | None:
    # The documented flat table is a monotone, one-based run excluding the root.
    # Section-specific runs can also appear, so require an unambiguous full run.
    if size == 1:
        return [0]
    candidates = set()
    for alignment in range(4):
        end = alignment + (len(data) - alignment) // 4 * 4
        run = []
        for (value,) in iter_unpack("<I", memoryview(data)[alignment:end]):
            if not 1 <= value <= count or (run and value < run[-1]):
                if len(run) == size - 1:
                    candidates.add(tuple(run))
                run.clear()
            if 1 <= value <= count:
                run.append(value)
        if len(run) == size - 1:
            candidates.add(tuple(run))
    if len(candidates) == 1:
        return [0, *(value - 1 for value in candidates.pop())]
    return None


def load_contents(folder: Path, count: int) -> tuple[dict, bool]:
    tree = named_child(folder, "tree.dki")
    if tree is None:
        return {}, False
    lines = [
        line for line in tree.read_text(encoding="cp1252", errors="replace").splitlines()
        if line.strip()
    ]
    if not lines:
        return {}, False
    map_file = named_child(folder, "tree.dka")
    records = record_map(map_file.read_bytes(), len(lines), count) if map_file else None
    parents = []
    groups = defaultdict(list)
    for index, line in enumerate(lines):
        depth = len(line) - len(line.lstrip(" "))
        while parents and parents[-1][0] >= depth:
            parents.pop()
        parent = parents[-1][1] if parents else None
        groups[parent].append(Entry(index, line.strip(), records[index] if records else None))
        parents.append((depth, index))
    return dict(groups), records is not None
