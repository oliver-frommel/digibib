"""Persistent passage highlights and their positions in rendered text."""
import re
import sqlite3
from bisect import bisect_left
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

COLORS = {
    "Yellow": "#ffe18a",
    "Green": "#bce8b2",
    "Blue": "#b9ddfa",
    "Rose": "#f7c4d0",
}
VISIBLE = re.compile(r"\S")


@dataclass(frozen=True)
class Mark:
    id: int
    first: int
    start: int
    last: int
    stop: int
    color: str
    excerpt: str


class Marks:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS marks (
                    id INTEGER PRIMARY KEY,
                    volume TEXT NOT NULL,
                    first INTEGER NOT NULL,
                    start INTEGER NOT NULL,
                    last INTEGER NOT NULL,
                    stop INTEGER NOT NULL,
                    color TEXT NOT NULL,
                    excerpt TEXT NOT NULL
                )
            """)
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    def list(self, volume):
        if not self.path.exists():
            return []
        with closing(self.connect()) as database:
            return [Mark(*row) for row in database.execute("""
                SELECT id, first, start, last, stop, color, excerpt
                FROM marks WHERE volume = ? ORDER BY first, start, id
            """, (volume,))]

    def add(self, volume, bounds, color, excerpt):
        with closing(self.connect()) as database, database:
            database.execute("""
                INSERT INTO marks (volume, first, start, last, stop, color, excerpt)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (volume, *bounds, color, excerpt))

    def remove(self, volume, mark_id):
        with closing(self.connect()) as database, database:
            database.execute("DELETE FROM marks WHERE volume = ? AND id = ?", (volume, mark_id))


class Passage:
    """Index non-whitespace characters per disc record across line wrap modes."""

    def __init__(self, text, first, slices):
        self.first = first
        self.positions = [
            [match.start() for match in VISIBLE.finditer(text, start, stop)]
            for start, stop in slices
        ]

    def anchor(self, start, stop):
        first = last = None
        for record, positions in enumerate(self.positions, self.first):
            left = bisect_left(positions, start)
            right = bisect_left(positions, stop)
            if left < right:
                if first is None:
                    first = (record, left)
                last = (record, right)
        return (*first, *last) if first is not None else None

    def locate(self, mark):
        left = right = None
        for record, positions in enumerate(self.positions, self.first):
            if record < mark.first or record > mark.last:
                continue
            start = mark.start if record == mark.first else 0
            stop = mark.stop if record == mark.last else len(positions)
            if 0 <= start < stop <= len(positions):
                if left is None:
                    left = positions[start]
                right = positions[stop - 1] + 1
        return (left, right) if left is not None else None
