# Digitale Bibliothek Reader

An offline desktop reader for the text on Directmedia Digitale Bibliothek CD-ROMs and DVDs. It runs on Windows, macOS, and Linux with Python 3.10+ and Tkinter.

## Install and run

From the cloned repository, preferably in a Python virtual environment:

```sh
python -m pip install ".[images]"
digibib
```

The `images` extra installs Pillow for illustrations. Use `python -m pip install .` for text-only use, or run `python -m digibib` directly from the repository without installing the reader.

Use `python3` if that is your Python command, or `py` on Windows. On Linux, install your distribution's Tkinter package if needed, such as `python3-tk` on Debian/Ubuntu or `python3-tkinter` on Fedora. On macOS, use a Python distribution that includes Tkinter.

Choose **Open folder…** and select the mounted disc, a copied disc folder, or a folder containing volume directories. You can also pass a folder or a `TEXT.DKI` file on the command line:

```sh
digibib "/path/to/mounted disc"
```

Mount ISO images through your operating system before opening them. Use the volume selector to switch titles, Previous and Next to turn pages, or enter a reader page number and press Enter. The reader shows print-edition page numbers below the text when the disc provides them. **Find text** scans the selected volume for a word or phrase. **Contents** returns to the expandable disc hierarchy. If the disc has no readable tree, it lists sections based on source-file markers.

The reader shows the current entry above the page and bolds its name when it opens the text. Prose wraps to the reading pane and keeps paragraph spacing. Blue underlined references link to unambiguous entry titles from the volume’s contents. Use **Back** to return to the previous page and scroll position after following a link.

Selecting an individual entry in the contents, following a cross-reference, or opening a search result reads its continuation pages together. Entries longer than 64 reader pages are shown in chunks accessible with **Previous** and **Next**. Enter a page number to view that page on its own, then use **Read full entry** when the entry spans multiple pages. Recognized author signatures appear on their own line.

To save a highlight, select a passage, choose a color, and click **Highlight**. Open **Marks** in the sidebar to jump to a saved passage. Select a mark and click **Remove mark** to delete it. The reader stores marks per volume in `marks.sqlite3` beside `session.json`, so highlights survive restarts.

Startup restores the last opened location and selected volume when available. Passing a path on the command line opens that location instead. The reader stores the two paths in a per-user `session.json` file.

| Platform | Session file |
| --- | --- |
| Windows | `%LOCALAPPDATA%\digibib\session.json` |
| macOS | `~/Library/Application Support/digibib/session.json` |
| Linux | `$XDG_STATE_HOME/digibib/session.json`, defaulting to `~/.local/state/digibib/session.json` |

## Format coverage

The reader decodes CP1252 text from the documented Family A and Family M `TEXT.DKI` layouts. It reads the hierarchy from `TREE.DKI` and links headings to pages when it recognizes the `TREE.DKA` page map. On illustrated pages, **View illustrations** jumps to the pictures below the text. The reader loads them using loose files under `IMAGES` or the packed BMP/JPEG archive layout verified on DB016. The original `LINKS.*` index, other image archive layouts, audio, embedded objects, and facsimile layout remain unsupported. DB006 requires a Cyrillic font mapping. Some malformed records, including the long-word exception documented upstream, may be unreadable.

Format and opcode-width reference: [DirectMedia MCP DKI format](https://github.com/sandraschi/directmedia-mcp/blob/master/docs/DKI_FORMAT.md) and its [reference decoder](https://github.com/sandraschi/directmedia-mcp/blob/master/src/directmedia_mcp/dki_text.py).
Contents layout reference: [digibib5-mcp](https://github.com/sandraschi/digibib5-mcp).

## Development

Run the regression tests from the repository root:

```sh
python -m unittest discover -s tests
```

To build a wheel and source distribution:

```sh
python -m pip install build
python -m build
```

## AI Policy

This repo is fully vibe coded

