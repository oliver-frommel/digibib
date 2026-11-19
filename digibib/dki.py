"""Random-access Digitale Bibliothek text decoding."""
import mmap
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from struct import unpack_from

MAGIC = 0x001924CC

# Opcode widths from the Digibib5 line scanner, documented by directmedia-mcp.
WIDTHS = (
    (2, 1, 1, 1, 1, 1, 1, 1, 2, 1, 5, 1, 1, 2, 1, 3,
     3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 3, 1, 1, 1)
    + (1,) * 32 + (2,) * 64
    + (5, 2, 2, 1, 1, 2, 5, 1, 2, 2, 5, 1, 1, 1, 1, 1,
       1, 1, 1, 1, 3, 9, 1, 1, 1, 1, 1, 1, 3, 1, 5, 1)
    + (2, 4, 1, 1, 1, 5, 1, 1, 1, 1, 1, 1, 1, 1, 1, 5, 1, 1, 3, 5, 1)
)
LENGTH_POSITIONS = {
    **dict.fromkeys((0x01, 0xAA, 0xAB, 0x87, 0x0B, 0x0E, 0x13, 0x14, 0x96, 0xA2), 1),
    **dict.fromkeys((0x0A, 0x86, 0x80, 0xB3), 5),
    0xA0: 2,
    0xA5: 6,
}
WORDS = {0x01, 0xAA}
AUTHOR_SIGNATURE = -1  # Internal marker emitted for a verified 04/05 run.

# Inline pronunciation glyphs observed in DB018. The contents spell the same
# headwords with plain vowels, which also makes them usable as link targets.
PRONUNCIATION_VOWELS = dict(zip(
    (0xA9, 0xAA, 0xC1, 0xC2, 0xD3, 0xD4, 0xD5, 0xD6, 0xED, 0xEE, 0xFD, 0xFE),
    b"AaEeIiOoUuYy",
))
INLINE_PRONUNCIATION = re.compile(rb"\x08([\xa9\xaa\xc1\xc2\xd3-\xd6\xed\xee\xfd\xfe])")


class FormatError(ValueError):
    """A file or page does not match the documented DKI layout."""


@dataclass(frozen=True)
class Page:
    text: str
    source: str
    edition: str
    numbers: tuple[int, ...]
    illustrations: tuple[str, ...] = ()
    prose: str = ""
    starts_paragraph: bool = False
    ends_paragraph: bool = False
    text_slices: tuple[tuple[int, int], ...] = ()
    prose_slices: tuple[tuple[int, int], ...] = ()


class TextVolume:
    def __init__(self, path: Path):
        self.author_signatures = set()
        with path.open("rb") as file:
            if len(file.read(4)) != 4:
                raise FormatError("Missing TEXT.DKI header.")
            self.data = mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            marker, = unpack_from("<I", self.data)
            self.modern = marker == MAGIC
            self.table = 12 if self.modern else 4
            self.header = 6 if self.modern else 2
            if len(self.data) < self.table:
                raise FormatError("Incomplete TEXT.DKI header.")
            self.count = unpack_from("<I", self.data, self.table - 4)[0]
            self.table_end = self.table + self.count * 4
            if not self.count or self.table_end > len(self.data):
                raise FormatError("Invalid TEXT.DKI offset table.")
            if not self.table_end <= self.offset(0) <= self.offset(self.count - 1) < len(self.data):
                raise FormatError("Invalid TEXT.DKI record positions.")
        except Exception:
            self.close()
            raise

    def close(self):
        self.data.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def offset(self, index: int) -> int:
        return unpack_from("<I", self.data, self.table + index * 4)[0]

    def fingerprint(self) -> str:
        digest = sha256()
        digest.update(len(self.data).to_bytes(8, "little"))
        for offset in (0, self.offset(0), self.offset(self.count // 2), self.offset(self.count - 1)):
            digest.update(self.data[offset:offset + 8192])
        return digest.hexdigest()

    def page(self, index: int) -> Page:
        if not 0 <= index < self.count:
            raise IndexError(index)
        start = self.offset(index)
        end = self.offset(index + 1) if index + 1 < self.count else len(self.data)
        if not self.table_end <= start < start + self.header < end <= len(self.data):
            raise FormatError("Invalid page bounds.")
        if end - start > 65535 + self.header:
            raise FormatError("Page exceeds the DKI record size limit.")
        return decode(self.data[start + self.header:end], self.modern, self.author_signatures)

    def span(self, start: int, stop: int) -> Page:
        first = previous = self.page(start)
        text = [first.text]
        prose = [first.prose]
        text_slices = [(0, len(first.text))]
        prose_slices = [(0, len(first.prose))]
        numbers = list(first.numbers)
        illustrations = list(first.illustrations)
        for index in range(start + 1, stop):
            try:
                page = self.page(index)
            except FormatError:
                warning = f"[Reader page {index + 1:,} could not be decoded.]"
                page = Page(warning, "", "", (), prose=warning, starts_paragraph=True, ends_paragraph=True)
            paragraph = previous.ends_paragraph or page.starts_paragraph
            text_start = text_slices[-1][1]
            prose_start = prose_slices[-1][1]
            if page.text:
                text_break = "\n\n" if paragraph else "\n"
                prose_break = "\n\n" if paragraph else " "
                text.extend((text_break, page.text))
                prose.extend((prose_break, page.prose))
                text_start += len(text_break)
                prose_start += len(prose_break)
            text_slices.append((text_start, text_start + len(page.text)))
            prose_slices.append((prose_start, prose_start + len(page.prose)))
            numbers.extend(page.numbers)
            illustrations.extend(page.illustrations)
            previous = page
        return Page(
            "".join(text), first.source, first.edition, tuple(dict.fromkeys(numbers)),
            tuple(dict.fromkeys(illustrations)), "".join(prose),
            text_slices=tuple(text_slices), prose_slices=tuple(prose_slices),
        )


def tokens(body: bytes):
    position = 0
    while position < len(body):
        opcode = body[position]
        if opcode >= len(WIDTHS):
            raise FormatError(f"Unknown token 0x{opcode:02X} at byte {position}.")
        width = WIDTHS[opcode]
        length_position = LENGTH_POSITIONS.get(opcode)
        if length_position is not None:
            if position + length_position >= len(body):
                raise FormatError("Incomplete token length.")
            length = body[position + length_position]
            width += (length & 0x7F if opcode in WORDS else length) + 1
        end = position + width
        if end > len(body):
            raise FormatError("Incomplete page token.")
        if opcode == 3:
            if end != len(body):
                raise FormatError("Unexpected bytes after the page terminator.")
            return
        yield opcode, body[position + 1:end]
        position = end
    raise FormatError("Missing page terminator.")


def marked_tokens(body, author_signatures):
    if not author_signatures:
        yield from tokens(body)
        return

    stream = list(tokens(body))
    index = 0
    while index < len(stream):
        opcode, payload = stream[index]
        if opcode == 0x04:
            word = index + 1
            while word < len(stream) and stream[word][0] in (0x00, 0x1B, 0x8B):
                word += 1
            end = word + 1
            # Print-page changes can appear inside the signature's format run.
            while end < len(stream) and stream[end][0] == 0x0F:
                end += 1
            if end < len(stream) and stream[word][0] in WORDS and stream[end][0] == 0x05:
                spelling = stream[word][1][1:]
                if spelling.decode("cp1252", errors="replace") in author_signatures:
                    yield AUTHOR_SIGNATURE, spelling
                    yield from stream[word + 1:end]
                    index = end + 1
                    continue
        yield opcode, payload
        index += 1


def decode(body: bytes, modern: bool, author_signatures=()) -> Page:
    parts = []
    print_pages = []
    illustrations = []
    source = edition = ""
    character_set = 0
    space = joining = False
    legacy_paragraph_candidate = False
    for opcode, payload in marked_tokens(body, author_signatures):
        if opcode == AUTHOR_SIGNATURE:
            parts.extend(("\n\n— ", payload.decode("cp1252"), "\n\n"))
            space = joining = False
        elif opcode in WORDS:
            if space and not joining:
                parts.append(" ")
            word = payload[1:]
            if b"\x08" in word:
                word = INLINE_PRONUNCIATION.sub(
                    lambda match: bytes((PRONUNCIATION_VOWELS[match[1][0]],)), word,
                )
            # The bibliography marker is a book glyph in character set 1.
            if character_set == 1 and word == b"&":
                parts.append("\U0001f56e")
            else:
                parts.append(word.decode("cp1252", errors="replace"))
            space = modern and bool(payload[0] & 0x80)
            joining = False
        elif opcode in (0x00, 0x1B):
            if opcode == 0x00 and payload[0] and legacy_paragraph_candidate and parts[-1:] == ["\r"]:
                parts[-1] = "\n"
            space = bool(parts and not parts[-1].endswith(("\n", "\r")) and not joining)
        elif opcode in (0x02, 0x8B):
            if not joining:
                # Legacy records use 02 for both physical lines and paragraphs.
                # A break without a trailing space followed by an indent starts
                # a paragraph. Consecutive breaks also preserve paragraph spacing.
                legacy_paragraph_candidate = not modern and opcode == 0x02 and not space
                parts.append("\n" if modern and opcode == 0x02 else "\r")
            space = False
        elif opcode in (0x15, 0xAC):
            if parts and parts[-1].endswith("-"):
                parts[-1] = parts[-1][:-1]
                joining = True
            space = False
        elif opcode == 0x0F:
            print_pages.append(int.from_bytes(payload, "little"))
        elif opcode == 0x0D:
            character_set = payload[0]
        elif opcode == 0x0E and not source:
            source = payload[1:].decode("cp1252", errors="replace")
        elif opcode in (0x0B, 0x80):
            raw = payload[1:] if opcode == 0x0B else payload[5:]
            name = raw.rstrip(b"\x00").decode("cp1252", errors="replace")
            if name and (opcode == 0x0B or re.search(r"\.(bmp|gif|jpe?g|png|tiff?)$", name, re.I)):
                illustrations.append(name)
        elif opcode == 0x13 and not edition:
            edition = payload[1:].decode("cp1252", errors="replace")

    layout = "".join(parts)
    text = re.sub(r"\n{3,}", "\n\n", layout.replace("\r", "\n")).strip("\n")
    # A single in-paragraph break can be reflowed for prose. Preserve paragraph
    # breaks and blank lines, and keep the original lineation available for verse.
    prose = re.sub(r"[\r\n]{2,}", "\n\n", layout.strip("\r\n")).replace("\r", " ")
    prose = re.sub(r"(?<!\n)\n(?!\n)", "\n\n", prose)
    return Page(
        text, source, edition, tuple(print_pages), tuple(dict.fromkeys(illustrations)), prose,
        layout.startswith(("\n", "\r\r", "\r\n")),
        layout.endswith(("\n", "\r\r", "\n\r")),
    )
