"""Per-user startup state for the desktop reader."""
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


def state_file() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", ""))
        if not base.is_absolute():
            base = Path.home() / ".local" / "state"
    return base / "digibib" / "session.json"


@dataclass(frozen=True)
class Session:
    location: Path
    volume: Path

    @classmethod
    def read(cls, path: Path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            location, volume = Path(data["location"]), Path(data["volume"])
            if location.is_absolute() and volume.is_absolute():
                return cls(location, volume)
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return None

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump({"location": str(self.location), "volume": str(self.volume)}, file)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
