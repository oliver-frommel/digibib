"""Locate loose illustrations and read the version 270 IMAGES.LIB directory."""
from io import BytesIO
from pathlib import Path, PureWindowsPath
from struct import unpack_from

from .dki import MAGIC
from .library import named_child

SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}


def to_ppm(image, width: int, height: int) -> bytes:
    """Convert a Pillow image to the binary PPM format built into Tk."""
    image.thumbnail((width, height))
    rgb = image.convert("RGB")
    header = f"P6\n{rgb.width} {rgb.height}\n255\n".encode("ascii")
    return header + rgb.tobytes()


def image_name(reference: str) -> PureWindowsPath:
    return PureWindowsPath(reference.strip("\x00 "))


class Illustrations:
    def __init__(self, folder: Path):
        self.loose = {}
        self.packed = {}
        self.archive = None
        directories = (folder, folder.parent) if folder.name.casefold() == "data" else (folder,)
        for directory in directories:
            images = named_child(directory, "images")
            if images is None or not images.is_dir():
                continue
            for entry in images.iterdir():
                if entry.is_dir() and entry.name in ("1", "2", "3", "4"):
                    self.index_files(entry.iterdir(), int(entry.name))
                elif entry.is_file():
                    self.index_files((entry,), 0)
            if not self.packed:
                archive = named_child(images, "images.lib")
                if archive and archive.is_file():
                    self.packed = read_archive(archive)
                    self.archive = archive

    def index_files(self, entries, level):
        for entry in entries:
            if entry.suffix.casefold() not in SUFFIXES or not entry.is_file():
                continue
            for key in (entry.name.casefold(), entry.stem.casefold()):
                if key not in self.loose or level > self.loose[key][0]:
                    self.loose[key] = level, entry

    def read(self, reference: str) -> Path | BytesIO | None:
        name = image_name(reference)
        file = self.loose.get(name.name.casefold()) or self.loose.get(name.stem.casefold())
        if file:
            return file[1]
        packed = self.packed.get(name.stem.casefold())
        if packed:
            offset, length = packed
            with self.archive.open("rb") as file:
                file.seek(offset)
                return BytesIO(file.read(length))
        return None


def read_archive(path: Path) -> dict[str, tuple[int, int]]:
    # Observed on DB016. Each entry has a name and five 13-byte rendition slots.
    with path.open("rb") as file:
        header = file.read(32)
        if len(header) != 32:
            return {}
        magic, version, count = unpack_from("<III", header)
        file_size = path.stat().st_size
        table_end = 32 + count * 95
        if magic != MAGIC or version != 270 or table_end > file_size:
            return {}
        index = {}
        for _ in range(count):
            entry = file.read(95)
            if len(entry) != 95 or not 1 <= entry[0] < 10:
                return {}
            stem = entry[1:1 + entry[0]].decode("cp1252", errors="replace").casefold()
            variants = []
            for slot in range(30, 95, 13):
                width, height, offset, length, kind = unpack_from("<HHIIB", entry, slot)
                if (kind in (1, 2) and width and height and table_end <= offset
                        and 0 < length <= 32 * 1024 * 1024 and offset + length <= file_size):
                    variants.append((width * height, offset, length))
            if variants:
                _, offset, length = max(variants)
                index[stem] = offset, length
    return index
