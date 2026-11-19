"""Desktop entry point for the Digitale Bibliothek reader."""
import argparse
import queue
import re
import sqlite3
import sys
import threading
from pathlib import Path, PureWindowsPath

from .dki import FormatError, TextVolume
from .images import Illustrations, to_ppm
from .library import discover
from .marks import COLORS, Marks, Passage
from .presentation import ContentsIndex, lead_ranges
from .state import Session, state_file
from .toc import load_contents


def main():
    parser = argparse.ArgumentParser(description="Read Digitale Bibliothek discs.")
    parser.add_argument("path", nargs="?", type=Path, help="Mounted disc, folder or TEXT.DKI")
    args = parser.parse_args()
    try:
        import tkinter as tk
        from tkinter import filedialog, font, messagebox, ttk
    except ImportError:
        sys.exit("Tkinter is required. On Linux, install your distribution's Python Tk package.")
    try:
        from PIL import Image
    except ImportError:
        Image = None

    class Reader:
        def __init__(self, root):
            self.root = root
            self.volume = None
            self.index = 0
            self.view_end = 0
            self.whole_entry = False
            self.paths = []
            self.state_path = state_file()
            self.session = Session.read(self.state_path)
            self.mark_store = Marks(self.state_path.with_name("marks.sqlite3"))
            self.marks = {}
            self.showing_marks = False
            self.passage = None
            self.targets = {}
            self.contents = {}
            self.contents_index = ContentsIndex({})
            self.mapped_contents = False
            self.history = []
            self.link_targets = {}
            self.highlight = ""
            self.page_text = ""
            self.illustrations = None
            self.photos = []
            self.job = None
            self.events = queue.Queue()
            self.root.title("Digitale Bibliothek")
            self.root.geometry("1120x750")
            self.root.minsize(680, 440)
            self.root.protocol("WM_DELETE_WINDOW", self.close)

            bar = ttk.Frame(root, padding=(14, 12))
            bar.pack(fill="x")
            ttk.Button(bar, text="Open folder…", command=self.open_folder).pack(side="left")
            self.volumes = ttk.Combobox(bar, state="readonly")
            self.volumes.pack(side="left", fill="x", expand=True, padx=(6, 0))
            self.volumes.bind("<<ComboboxSelected>>", self.select_volume)

            pane = ttk.Panedwindow(root, orient="horizontal")
            pane.pack(fill="both", expand=True, padx=14)
            sidebar = ttk.Frame(pane, padding=(0, 4, 10, 0), width=285)
            reading = ttk.Frame(pane, padding=(10, 4, 0, 0))
            pane.add(sidebar, weight=0)
            pane.add(reading, weight=1)

            self.query = ttk.Entry(sidebar, width=25)
            self.query.pack(fill="x")
            self.query.bind("<Return>", lambda event: self.scan("search"))
            actions = ttk.Frame(sidebar)
            actions.pack(fill="x", pady=6)
            ttk.Button(actions, text="Find text", command=lambda: self.scan("search")).pack(side="left")
            ttk.Button(actions, text="Contents", command=self.show_contents).pack(side="left", padx=4)
            self.cancel_button = ttk.Button(actions, text="Stop", command=self.cancel, state="disabled")
            self.cancel_button.pack(side="left")
            mark_actions = ttk.Frame(sidebar)
            mark_actions.pack(fill="x", pady=(0, 6))
            ttk.Button(mark_actions, text="Marks", command=self.show_marks).pack(side="left")
            self.remove_mark_button = ttk.Button(
                mark_actions, text="Remove mark", command=self.remove_mark, state="disabled",
            )
            self.remove_mark_button.pack(side="left", padx=4)
            result_panel = ttk.Frame(sidebar)
            result_panel.pack(fill="both", expand=True)
            self.results = ttk.Treeview(result_panel, show="tree", selectmode="browse")
            horizontal = ttk.Scrollbar(result_panel, orient="horizontal", command=self.results.xview)
            horizontal.pack(side="bottom", fill="x")
            result_scroll = ttk.Scrollbar(result_panel, command=self.results.yview)
            self.results.configure(yscrollcommand=result_scroll.set, xscrollcommand=horizontal.set)
            result_scroll.pack(side="right", fill="y")
            self.results.column("#0", width=245, minwidth=100, stretch=False)
            self.results.pack(fill="both", expand=True)
            self.results.bind("<<TreeviewSelect>>", self.select_result)
            self.results.bind("<<TreeviewOpen>>", self.expand_contents)

            nav = ttk.Frame(reading)
            nav.pack(fill="x", pady=(0, 8))
            self.previous = ttk.Button(nav, text="← Previous", command=lambda: self.step(-1))
            self.previous.pack(side="left")
            self.page_field = ttk.Entry(nav, width=8, justify="center")
            self.page_field.pack(side="left", padx=(8, 4))
            self.page_field.bind("<Return>", self.jump)
            self.total = ttk.Label(nav, text="/ 0")
            self.total.pack(side="left", padx=(0, 8))
            self.next = ttk.Button(nav, text="Next →", command=lambda: self.step(1))
            self.next.pack(side="left")
            for label, amount in (("A+", 1), ("A−", -1)):
                ttk.Button(nav, text=label, width=4, command=lambda n=amount: self.zoom(n)).pack(side="right", padx=2)
            self.copy_button = ttk.Button(nav, text="Copy text", command=self.copy_text, state="disabled")
            self.copy_button.pack(side="right", padx=4)
            chapter = ttk.Frame(reading, padding=(0, 0, 0, 8))
            chapter.pack(fill="x")
            self.back = ttk.Button(chapter, text="← Back", command=self.go_back, state="disabled")
            self.back.pack(side="left", padx=(0, 8))
            self.full_entry = ttk.Button(
                chapter, text="Read full entry",
                command=lambda: self.show_page(self.index, self.highlight, whole_entry=True),
            )
            self.heading = ttk.Label(chapter, anchor="w")
            self.heading.pack(side="left", fill="x", expand=True)
            tools = ttk.Frame(reading)
            tools.pack(fill="x", pady=(0, 8))
            self.mark_color = next(iter(COLORS))
            self.mark_swatches = {}
            self.mark_palette = ttk.Menubutton(tools, direction="below", takefocus=True)
            palette_menu = tk.Menu(self.mark_palette, tearoff=False)
            for color, background in COLORS.items():
                swatch = tk.PhotoImage(master=tools, width=18, height=14)
                swatch.put("#605950", to=(0, 0, 18, 14))
                swatch.put(background, to=(1, 1, 17, 13))
                self.mark_swatches[color] = swatch
                palette_menu.add_command(
                    label=color, image=swatch, compound="none",
                    command=lambda chosen=color: self.select_mark_color(chosen),
                )
            self.mark_palette.configure(menu=palette_menu)
            self.select_mark_color(self.mark_color)
            self.mark_palette.pack(side="left", padx=(0, 6))
            self.mark_button = ttk.Button(tools, text="Highlight", command=self.add_mark, state="disabled")
            self.mark_button.pack(side="left")
            self.image_button = ttk.Button(
                tools, command=lambda: self.paper.yview("illustrations"),
            )
            self.book_font = font.nametofont("TkTextFont").copy()
            self.book_font.configure(family="Georgia", size=15)
            self.lead_font = self.book_font.copy()
            self.lead_font.configure(weight="bold")
            self.paper = tk.Text(
                reading, width=48, wrap="word", font=self.book_font, padx=28, pady=22,
                background="#fbf8ef", foreground="#24221f", selectbackground="#c5dbec",
                relief="flat", spacing1=2, spacing3=2, cursor="xterm", exportselection=False,
            )
            page_scroll = ttk.Scrollbar(reading, command=self.paper.yview)
            self.paper.configure(yscrollcommand=page_scroll.set)
            page_scroll.pack(side="right", fill="y")
            self.paper.pack(fill="both", expand=True)
            self.paper.bind("<Prior>", lambda event: self.step(-1))
            self.paper.bind("<Next>", lambda event: self.step(1))
            self.paper.bind("<<Copy>>", self.copy_text)
            shortcut = "<Command-c>" if self.root.tk.call("tk", "windowingsystem") == "aqua" else "<Control-c>"
            self.paper.bind(shortcut, self.copy_text)
            self.paper.bind("<<Selection>>", self.mark_selection_changed)
            self.paper.tag_configure("match", background="#f2daa1")
            self.paper.tag_configure("lead", font=self.lead_font)
            self.paper.tag_configure("reference", foreground="#205d95", underline=True)
            self.paper.tag_bind("reference", "<Enter>", lambda event: self.paper.configure(cursor="hand2"))
            self.paper.tag_bind("reference", "<Leave>", lambda event: self.paper.configure(cursor="xterm"))
            self.paper.tag_bind("reference", "<ButtonRelease-1>", self.follow_reference)
            for color, background in COLORS.items():
                self.paper.tag_configure(f"mark-{color}", background=background)
                self.results.tag_configure(f"mark-{color}", background=background)
            self.paper.tag_raise("sel")
            self.metadata = ttk.Label(root, padding=(14, 8), anchor="w", wraplength=650)
            self.metadata.pack(fill="x")
            self.status = ttk.Label(root, padding=(14, 0, 14, 8), anchor="w")
            self.status.pack(fill="x")
            self.root.bind("<Control-o>", lambda event: self.open_folder())
            self.root.bind("<Control-f>", lambda event: self.query.focus_set())
            self.show_text("Open a mounted disc or a library folder.")
            self.update_navigation()
            self.root.after(70, self.poll)

        def show_text(self, text, *, page_text=""):
            self.passage = None
            self.mark_button.configure(state="disabled")
            self.page_text = page_text
            self.copy_button.configure(state="normal" if page_text else "disabled")
            self.image_button.pack_forget()
            self.paper.configure(state="normal")
            self.paper.delete("1.0", "end")
            for tag in self.link_targets:
                self.paper.tag_delete(tag)
            self.link_targets.clear()
            self.paper.configure(cursor="xterm")
            self.photos.clear()
            self.paper.insert("1.0", text)
            self.paper.configure(state="disabled")
            self.paper.yview_moveto(0)

        def copy_text(self, event=None):
            selection = self.paper.tag_ranges("sel")
            if selection:
                text = self.paper.get(selection[0], selection[-1])
            else:
                text = self.page_text if event is None else ""
            if text:
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(text)
                except tk.TclError:
                    self.status.configure(text="Could not copy text to the clipboard.")
            return "break"

        def mark_selection_changed(self, event):
            enabled = self.passage is not None and bool(self.paper.tag_ranges("sel"))
            self.mark_button.configure(state="normal" if enabled else "disabled")

        def select_mark_color(self, color):
            self.mark_color = color
            self.mark_palette.configure(image=self.mark_swatches[color])

        def refresh_marks(self):
            self.marks = {f"mark-{mark.id}": mark for mark in self.mark_store.list(self.volume_key)}

        def add_mark(self):
            selection = self.paper.tag_ranges("sel")
            if not selection or self.passage is None:
                return
            start, stop = (len(self.paper.get("1.0", edge)) for edge in (selection[0], selection[-1]))
            bounds = self.passage.anchor(start, stop)
            if bounds is None:
                return
            excerpt = " ".join(self.page_text[start:stop].split())
            if len(excerpt) > 96:
                excerpt = excerpt[:95] + "…"
            try:
                self.mark_store.add(self.volume_key, bounds, self.mark_color, excerpt)
                self.refresh_marks()
            except (OSError, sqlite3.Error) as error:
                self.status.configure(text=f"Could not save highlight: {error}")
                return
            self.paper.tag_remove("sel", "1.0", "end")
            self.draw_marks()
            if self.showing_marks:
                self.render_mark_list()
            self.status.configure(text="Highlight saved.")

        def draw_marks(self):
            for color in COLORS:
                self.paper.tag_remove(f"mark-{color}", "1.0", "end")
            if self.passage is not None:
                for mark in self.marks.values():
                    marks_range = self.passage.locate(mark)
                    if marks_range is not None and mark.color in COLORS:
                        start, stop = marks_range
                        self.paper.tag_add(f"mark-{mark.color}", f"1.0+{start}c", f"1.0+{stop}c")

        def render_mark_list(self):
            self.clear_results()
            self.showing_marks = True
            self.results.column("#0", width=420)
            for row, mark in self.marks.items():
                section = self.contents_index.section(mark.first)
                location = section.title if section else f"Page {mark.first + 1}"
                self.results.insert(
                    "", "end", iid=row, text=f"{location} · {mark.excerpt}", tags=(f"mark-{mark.color}",),
                )

        def show_marks(self):
            if self.volume is None:
                self.status.configure(text="Open a volume first.")
                return
            self.cancel()
            try:
                self.refresh_marks()
            except (OSError, sqlite3.Error) as error:
                self.status.configure(text=f"Could not load highlights: {error}")
                return
            self.draw_marks()
            self.render_mark_list()
            self.status.configure(text="" if self.marks else "No highlights saved for this volume.")

        def remove_mark(self):
            selection = self.results.selection()
            if not self.showing_marks or not selection or selection[0] not in self.marks:
                return
            try:
                self.mark_store.remove(self.volume_key, self.marks[selection[0]].id)
                self.refresh_marks()
            except (OSError, sqlite3.Error) as error:
                self.status.configure(text=f"Could not remove highlight: {error}")
                return
            self.draw_marks()
            self.render_mark_list()
            self.status.configure(text="Highlight removed.")

        def open_folder(self):
            options = {}
            if self.session is not None:
                location = self.session.location
                for folder in (location, location.parent):
                    if folder.is_dir():
                        options["initialdir"] = str(folder)
                        break
            path = filedialog.askdirectory(
                parent=self.root, title="Select a disc or library folder", **options,
            )
            if path:
                self.load(Path(path))

        def restore_session(self):
            if self.session is not None:
                self.load(self.session.location, preferred=self.session.volume, restoring=True)

        def load(self, path, preferred=None, restoring=False):
            try:
                path = path.absolute()
                volumes = discover(path)
                if not volumes:
                    raise FormatError("No TEXT.DKI found in this location.")
                selected = next((i for i, volume in enumerate(volumes) if volume.text == preferred), 0)
                opened = TextVolume(volumes[selected].text)
            except (OSError, ValueError) as error:
                if restoring:
                    self.status.configure(text="Last disc unavailable. Mount it or open a folder.")
                else:
                    messagebox.showerror("Could not open library", str(error), parent=self.root)
                return
            self.paths = volumes
            self.location = path
            self.volumes.configure(values=[volume.title for volume in volumes])
            self.volumes.current(selected)
            self.activate(opened, selected)

        def select_volume(self, event):
            selected = self.volumes.current()
            try:
                opened = TextVolume(self.paths[selected].text)
            except (OSError, ValueError) as error:
                self.volumes.current(self.selected)
                messagebox.showerror("Could not open volume", str(error), parent=self.root)
                return
            self.activate(opened, selected)

        def activate(self, opened, selected):
            self.cancel()
            if self.volume is not None:
                self.volume.close()
            self.volume = opened
            self.volume_key = opened.fingerprint()
            self.marks = {}
            try:
                self.refresh_marks()
            except (OSError, sqlite3.Error):
                pass
            self.selected = selected
            folder = self.paths[selected].text.parent
            self.contents, self.mapped_contents = {}, False
            self.illustrations = None
            try:
                self.contents, self.mapped_contents = load_contents(folder, opened.count)
            except OSError:
                pass
            self.contents_index = ContentsIndex(self.contents)
            try:
                opened.author_signatures = self.contents_index.read_author_signatures(opened)
            except OSError:
                pass
            try:
                self.illustrations = Illustrations(folder)
            except OSError:
                pass
            title = self.paths[selected].title
            self.history.clear()
            self.root.title(title + " · Digitale Bibliothek")
            self.clear_results()
            self.status.configure(text="")
            self.show_page(0)
            if self.contents:
                self.show_contents()
            session = Session(self.location, self.paths[selected].text)
            if session != self.session:
                try:
                    session.save(self.state_path)
                except OSError:
                    self.status.configure(text="Could not save the last opened disc.")
                else:
                    self.session = session

        def update_navigation(self):
            count = self.volume.count if self.volume is not None else 0
            self.back.configure(state="normal" if self.history else "disabled")
            self.previous.configure(state="normal" if self.index > 0 else "disabled")
            self.next.configure(state="normal" if self.view_end < count else "disabled")
            self.page_field.configure(state="normal")
            self.page_field.delete(0, "end")
            if count:
                self.page_field.insert(0, str(self.index + 1))
            else:
                self.page_field.configure(state="disabled")
            self.total.configure(text=f"/ {count:,}")

        def show_page(self, index, highlight="", whole_entry=False):
            start, stop = index, index + 1
            entry_start, entry_stop = self.contents_index.entry_span(index, self.volume.count)
            if whole_entry:
                start, stop = entry_start, entry_stop
            self.full_entry.pack_forget()
            if not whole_entry and entry_stop - entry_start > 1:
                self.full_entry.pack(side="right", padx=(0, 6))
            index = start
            self.index = index
            self.view_end = stop
            self.whole_entry = whole_entry
            self.highlight = highlight
            self.update_navigation()
            section = self.contents_index.section(index)
            self.heading.configure(text=section.title if section else "")
            try:
                page = self.volume.span(index, stop) if stop > index + 1 else self.volume.page(index)
            except (FormatError, OSError) as error:
                self.show_text(f"Could not read this page.\n\n{error}")
                self.metadata.configure(text="")
                return
            text = page.prose
            self.show_text(text or "(No text on this page)", page_text=text)
            if text:
                self.passage = Passage(text, index, page.prose_slices or ((0, len(text)),))
                self.draw_marks()
            for start, end in lead_ranges(text, section, index):
                self.paper.tag_add("lead", f"1.0+{start}c", f"1.0+{end}c")
            for start, end, target in self.contents_index.references(text, section):
                if target == index:
                    continue
                tag = f"reference-{start}"
                self.link_targets[tag] = target
                self.paper.tag_add("reference", f"1.0+{start}c", f"1.0+{end}c")
                self.paper.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")
            if page.illustrations:
                self.show_illustrations(page.illustrations)
            self.metadata.configure(text="  ·  ".join(filter(None, (
                f"Reader pages {index + 1:,}–{stop:,}" if stop > index + 1 else "",
                page.edition,
                "Print page " + ", ".join(map(str, page.numbers)) if page.numbers else "",
                page.source,
            ))))
            if highlight:
                for match in search_pattern(highlight).finditer(text):
                    self.paper.tag_add("match", f"1.0+{match.start()}c", f"1.0+{match.end()}c")
                first = self.paper.tag_nextrange("match", "1.0")
                if first:
                    self.paper.see(first[0])

        def follow_reference(self, event):
            if self.paper.tag_ranges("sel"):
                return
            position = self.paper.index(f"@{event.x},{event.y}")
            for tag in self.paper.tag_names(position):
                if tag in self.link_targets:
                    target = self.link_targets[tag]
                    self.history.append((self.index, self.highlight, self.whole_entry, self.paper.yview()[0]))
                    self.show_page(target, whole_entry=True)
                    return "break"

        def go_back(self):
            if self.history:
                index, highlight, whole_entry, scroll = self.history.pop()
                self.show_page(index, highlight, whole_entry)
                self.paper.yview_moveto(scroll)

        def show_illustrations(self, references):
            count = len(references)
            label = "View illustration" if count == 1 else f"View {count} illustrations"
            self.image_button.configure(text=label)
            self.image_button.pack(side="left", padx=(8, 0))
            self.paper.configure(state="normal")
            self.paper.insert("end", "\n\n")
            self.paper.mark_set("illustrations", "end-1c")
            self.paper.mark_gravity("illustrations", "left")
            if Image is None:
                self.paper.insert("end", "Install Pillow to display this page’s illustrations.")
            else:
                for index, reference in enumerate(references):
                    if index:
                        self.paper.insert("end", "\n\n")
                    try:
                        source = self.illustrations.read(reference) if self.illustrations else None
                        if source is None:
                            raise FileNotFoundError(reference)
                        with Image.open(source) as image:
                            width = max(240, min(900, self.paper.winfo_width() - 64))
                            photo = tk.PhotoImage(data=to_ppm(image, width, 850), format="ppm", master=self.paper)
                        self.photos.append(photo)
                        self.paper.image_create("end", image=photo)
                    except (OSError, ValueError, Image.DecompressionBombError, tk.TclError):
                        self.paper.insert("end", f"Illustration unavailable: {reference}")
            self.paper.configure(state="disabled")

        def step(self, offset):
            target = self.index - 1 if offset < 0 else self.view_end
            if self.volume is not None and 0 <= target < self.volume.count:
                self.show_page(target, whole_entry=self.whole_entry)
            return "break"

        def jump(self, event):
            try:
                target = int(self.page_field.get()) - 1
                if not 0 <= target < self.volume.count:
                    raise ValueError
            except ValueError:
                self.root.bell()
                self.update_navigation()
                return
            self.show_page(target)

        def zoom(self, amount):
            size = max(9, min(40, self.book_font.cget("size") + amount))
            self.book_font.configure(size=size)
            self.lead_font.configure(size=size)

        def clear_results(self):
            self.showing_marks = False
            self.remove_mark_button.configure(state="disabled")
            self.results.delete(*self.results.get_children())
            self.targets.clear()

        def show_contents(self):
            if not self.contents:
                self.scan("sections")
                return
            self.cancel()
            self.clear_results()
            self.results.column("#0", width=420)
            self.insert_contents(None, "")
            for root in self.contents.get(None, ()):
                row = f"toc-{root.index}"
                if root.index in self.contents:
                    self.populate_contents(root.index, row)
                    self.results.item(row, open=True)
            self.status.configure(text="" if self.mapped_contents else "Contents available. Page links unavailable.")

        def insert_contents(self, parent, row):
            for entry in self.contents.get(parent, ()):
                child = f"toc-{entry.index}"
                self.results.insert(row, "end", iid=child, text=entry.title)
                if entry.record is not None:
                    self.targets[child] = entry.record, ""
                if entry.index in self.contents:
                    self.results.insert(child, "end", iid=f"{child}-pending")

        def populate_contents(self, index, row):
            pending = f"{row}-pending"
            if self.results.exists(pending):
                self.results.delete(pending)
                self.insert_contents(index, row)

        def expand_contents(self, event):
            row = self.results.focus()
            if row.startswith("toc-") and not row.endswith("-pending"):
                self.populate_contents(int(row[4:]), row)

        def cancel(self):
            if self.job is not None:
                self.job.set()
                self.job = None
                self.cancel_button.configure(state="disabled")
                self.status.configure(text="Scan stopped.")

        def scan(self, mode):
            if self.volume is None:
                self.status.configure(text="Open a volume first.")
                return
            query = self.query.get().strip() if mode == "search" else ""
            if mode == "search" and not query:
                self.status.configure(text="Enter a word or phrase to find.")
                self.query.focus_set()
                return
            self.cancel()
            self.clear_results()
            self.results.column("#0", width=245)
            self.job = threading.Event()
            self.cancel_button.configure(state="normal")
            self.status.configure(text="Scanning volume…")
            thread = threading.Thread(
                target=scan_volume,
                args=(self.paths[self.selected].text, mode, query, self.job, self.events),
                daemon=True,
            )
            thread.start()

        def poll(self):
            for _ in range(24):
                try:
                    job, kind, value = self.events.get_nowait()
                except queue.Empty:
                    break
                if job is not self.job:
                    continue
                if kind == "rows":
                    for index, label, query in value:
                        row = str(len(self.targets))
                        self.targets[row] = index, query
                        self.results.insert("", "end", iid=row, text=label)
                else:
                    self.status.configure(text=value)
                    if kind == "done":
                        self.job = None
                        self.cancel_button.configure(state="disabled")
            self.root.after(70, self.poll)

        def select_result(self, event):
            selection = self.results.selection()
            if self.showing_marks:
                mark = self.marks.get(selection[0]) if selection else None
                self.remove_mark_button.configure(state="normal" if mark else "disabled")
                if mark:
                    self.show_page(mark.first, whole_entry=True)
                    marks_range = self.passage.locate(mark) if self.passage else None
                    if marks_range is not None:
                        self.paper.see(f"1.0+{marks_range[0]}c")
                return
            if selection and selection[0] in self.targets:
                row = selection[0]
                index, highlight = self.targets[row]
                leaf = row.startswith("toc-") and int(row[4:]) not in self.contents
                self.show_page(index, highlight, whole_entry=leaf or bool(highlight))

        def close(self):
            self.cancel()
            if self.volume is not None:
                self.volume.close()
            self.root.destroy()

    try:
        root = tk.Tk()
    except tk.TclError as error:
        sys.exit(f"Could not start the desktop window: {error}")
    reader = Reader(root)
    if args.path is not None:
        root.after_idle(lambda: reader.load(args.path))
    else:
        root.after_idle(reader.restore_session)
    root.mainloop()


def search_pattern(query):
    return re.compile(r"\s+".join(map(re.escape, query.split())), re.IGNORECASE)


def scan_volume(path, mode, query, stop, events):
    matches = skipped = 0
    previous_source = ""
    rows = []
    pattern = search_pattern(query) if query else None
    limit = 500 if mode == "search" else 10000
    try:
        with TextVolume(path) as volume:
            for index in range(volume.count):
                if stop.is_set():
                    return
                if index % 512 == 0:
                    events.put((stop, "progress", f"Scanning page {index + 1:,} / {volume.count:,}…"))
                try:
                    page = volume.page(index)
                except FormatError:
                    skipped += 1
                    continue
                if pattern is not None:
                    match = pattern.search(page.text)
                    if not match:
                        continue
                    snippet = page.text[max(0, match.start() - 16):match.end() + 70]
                    label = " ".join(snippet.split())
                else:
                    if not page.source or page.source == previous_source:
                        continue
                    previous_source = page.source
                    label = PureWindowsPath(page.source).stem or page.source
                matches += 1
                rows.append((index, f"{index + 1:,}  {label}", query))
                if len(rows) >= 32:
                    events.put((stop, "rows", rows))
                    rows = []
                if matches == limit:
                    break
        if rows:
            events.put((stop, "rows", rows))
        noun = "matching pages" if mode == "search" else "source sections"
        status = f"{matches:,} {noun} found."
        if matches == limit:
            status = f"Showing the first {limit:,} {noun}."
        if skipped:
            status += f" Skipped {skipped:,} unreadable pages."
        events.put((stop, "done", status))
    except (OSError, ValueError) as error:
        events.put((stop, "done", f"Scan failed: {error}"))


if __name__ == "__main__":
    main()
