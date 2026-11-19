"""Reading structure and inferred references for decoded pages."""
import re
from bisect import bisect_right
from collections import defaultdict

from .dki import FormatError

FIRST_WORD = re.compile(r"\b\w+")
PARAGRAPH_START = re.compile(r"(?:\A|\n\n)[ \t]*")


class ContentsIndex:
    def __init__(self, groups):
        self.sections = sorted(
            (entry for entries in groups.values() for entry in entries if entry.record is not None),
            key=lambda entry: (entry.record, entry.index),
        )
        self.starts = [entry.record for entry in self.sections]
        self.branches = set(groups)
        titles = defaultdict(set)
        spellings = {}
        for entry in self.sections:
            if entry.index not in groups and len(entry.title) >= 4 and FIRST_WORD.match(entry.title):
                title = " ".join(entry.title.split())
                titles[title.casefold()].add(entry.record)
                spellings[title.casefold()] = title
        self.by_word = defaultdict(list)
        for title, records in titles.items():
            if len(records) == 1:
                self.by_word[FIRST_WORD.match(title)[0]].append((spellings[title], next(iter(records))))
        self.patterns = {}

    def section(self, record):
        position = bisect_right(self.starts, record) - 1
        return self.sections[position] if position >= 0 else None

    def entry_span(self, record, count):
        position = bisect_right(self.starts, record)
        if not position or self.sections[position - 1].index in self.branches:
            return record, record + 1
        start = self.starts[position - 1]
        stop = self.starts[position] if position < len(self.starts) else count
        # Bound the number of records rendered at once for unusually long entries.
        limit = 64
        start += (record - start) // limit * limit
        return start, min(start + limit, stop)

    def read_author_signatures(self, volume):
        for entry in self.sections:
            if entry.title.casefold() != "autorsignaturen und autoren":
                continue
            start, stop = self.entry_span(entry.record, volume.count)
            signatures = set()
            for number in range(start, stop):
                try:
                    text = volume.page(number).text
                except FormatError:
                    continue
                signatures.update(re.findall(r"^([^\W\d_]{1,5})[ \t]{2,}\S", text, re.MULTILINE))
            return signatures
        return set()

    def references(self, text, current_section):
        end = 0
        for match in FIRST_WORD.finditer(text):
            word = match[0].casefold()
            if match.start() < end or word not in self.by_word:
                continue
            if word not in self.patterns:
                self.patterns[word] = [
                    (title, target, title_pattern(title))
                    for title, target in sorted(self.by_word[word], key=lambda item: -len(item[0]))
                ]
            for title, target, pattern in self.patterns[word]:
                phrase = pattern.match(text, match.start())
                if phrase:
                    end = phrase.end()
                    if current_section is None or title.casefold() != current_section.title.casefold():
                        yield phrase.start(), end, target
                    break


def title_pattern(title):
    words = [re.escape(word) for word in title.split()]
    return re.compile(r"(?:[ \t]+|[ \t]*\n[ \t]*)".join(words) + r"(?!\w)", re.IGNORECASE)


def lead_ranges(text, section, record):
    if section is None or section.record != record:
        return
    pattern = title_pattern(section.title)
    for paragraph in PARAGRAPH_START.finditer(text):
        match = pattern.match(text, paragraph.end())
        if match:
            yield match.span()
            return
