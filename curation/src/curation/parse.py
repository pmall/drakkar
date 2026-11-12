"""Convert full texts and supplementary files to the texts a curation reads, short in tokens:
`entries`, run by `curation/scripts/parse.py`, which describes it, and by `fetch.py`.

Each file is converted by its type, to texts written beside it and named by their format. No
network.

- HTML, `<file>.html`: PMC XML (title, abstract, sections, paragraphs, lists, figures, tables
  and supplementary materials; references, acknowledgements, notes and peer reviews left out), a
  PMC article page by its structure, as its XML (the same blocks, the back matter left out), any
  other HTML page (its main text, as trafilatura finds it), a Word document (`.docx`, its XML
  cleaned up: paragraphs, headings, lists, tables, images, text boxes, field results, footnotes
  and endnotes, text in the Symbol font as the Greek letters and signs it shows; formatting,
  headers, footers, comments and tracked deletions left out), a Word 97-2003 document (`.doc`,
  through our own reader: its paragraphs and tables, a nested table flattened into its cell, its
  pictures left out). Only the content is kept, in these tags: headings, paragraphs (`p`), lists
  (`ul`, `ol`, `li`), tables (`table`, `tr`, `th`, `td`, with their `rowspan` and `colspan`, a
  table in a cell kept in it), figures (`figure`, `img` with its `src`, `figcaption`), labels in
  bold (`b`), `sup`, `sub`, `br`. Each block is on its own line, and so is each row of a table
  and each item of a list. An image is its file when the publication directory holds it (a PMC
  figure in `<stem>.fig/` beside the XML, where `fetch` saves them; a Word document's
  image beside it, where `prepare` saves them), else the name, URL or path the file gives.
- Plain text, `<file>.txt`: a PDF's text page by page (`--- page N ---`), line by line in the
  order pymupdf reads it, nothing moved; a line read right after another at the same height
  continues it after a tab, so a table's row the PDF writes cell after cell is one line, while a
  cell shared by several rows stays on its own lines.
- TSV, one file per sheet of a spreadsheet (`.xlsx`, `.xlsm`, `.xls`): `<file>.<n>.tsv`, numbered
  in workbook order, an empty sheet an empty file; its empty rows left out, every other row as
  many fields as the sheet's widest row.
- CSV, TSV and plain text are their own text, cleaned in place: in UTF-8 (their encoding found
  among UTF-8, UTF-16, Windows-1252 and Mac Roman), invisible characters removed, and a CSV's or
  TSV's rows padded as a sheet's (a TSV split at its tabs; a CSV read as CSV, its separator the
  one, among comma, semicolon and tab, that gives the most rows the same number of fields); a file
  whose encoding is not found is refused.

Each file is first made ready to read (`prepare`): an archive (zip, RAR, 7z, tar, gzip) replaced
by its files, saved beside it (its videos left out, an archive in it unpacked), a TIFF or a BMP
image replaced by its PNG, a document's images saved beside it.
"""

import bisect
import csv
import gzip
import io
import lzma
import re
import struct
import sys
import tarfile
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, cast

import charset_normalizer
import olefile
import openpyxl
import py7zr
import pymupdf
import trafilatura
import xlrd
from lxml import etree
from lxml.etree import _Element  # pyright: ignore[reportPrivateUsage]
from py7zr.io import BytesIOFactory
from unrar.cffi import rarfile  # pyright: ignore[reportMissingTypeStubs]
from unrar.cffi.unrarlib import BadRarFile  # pyright: ignore[reportMissingTypeStubs]


class ParseError(Exception):
    pass


def one_line(text: str) -> str:
    return " ".join(text.split())


# HTML texts

# The tags of the HTML texts, each with the attributes it keeps: the rest is cleaned away.
TAGS: dict[str, set[str]] = {
    **{f"h{n}": set() for n in range(1, 7)},
    "p": set(),
    "ul": set(),
    "ol": set(),
    "li": set(),
    "table": set(),
    "tr": set(),
    "th": {"rowspan", "colspan"},
    "td": {"rowspan", "colspan"},
    "figure": set(),
    "figcaption": set(),
    "img": {"src"},
    "b": set(),
    "sup": set(),
    "sub": set(),
    "br": set(),
}
# Never text: their content is left out.
NEVER = {"script", "style", "noscript", "template"}


def _add_text(parent: _Element, text: str) -> None:
    """Text added at the end of an element's content."""
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _squeeze(block: _Element) -> None:
    """A block's text in one line, its spaces single, none at the start or the end of a block, a
    cell or an item, nor between the rows and cells of a table or the items of a list."""
    for el in block.iter():
        el.text = re.sub(r"\s+", " ", el.text) if el.text else el.text
        el.tail = re.sub(r"\s+", " ", el.tail) if el.tail else el.tail
    for el in block.iter("table", "tr", "ul", "ol", "figure"):
        el.text = el.text if (el.text or "").strip() else None
        for child in el:
            child.tail = child.tail if (child.tail or "").strip() else None
    for el in block.iter("p", "li", "td", "th", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6"):
        el.text = (el.text or "").lstrip() or None
        last = el[-1] if len(el) else None
        if last is not None:
            last.tail = (last.tail or "").rstrip() or None
        else:
            el.text = (el.text or "").rstrip() or None


def _all_text(el: _Element) -> str:
    return "".join(cast(Iterable[str], el.itertext()))


def _filled(block: _Element) -> bool:
    return bool(_all_text(block).strip()) or block.find(".//img") is not None


def _line(el: _Element) -> str:
    return etree.tostring(el, encoding="unicode", method="html", with_tail=False)


def html_text(blocks: Iterable[_Element]) -> str:
    """The blocks of an HTML text, each on its own line, and each row of a table and each item of
    a list on its own line, so that a search finds them; empty blocks left out."""
    lines: list[str] = []
    for block in blocks:
        _squeeze(block)
        if block.tag in ("table", "ul", "ol") and _filled(block):
            lines += [f"<{block.tag}>", *(_line(child) for child in block), f"</{block.tag}>"]
        elif block.tag == "img" or _filled(block):
            lines.append(_line(block))
    return "".join(f"{line}\n" for line in lines)


def _fill(parent: _Element, el: _Element, skip: Collection[str] = ()) -> _Element:
    """The content of an element, of PMC XML or HTML, added to an HTML element: its text, its
    superscripts and subscripts, a table as a table, a list as a list; the rest of its markup
    cleaned away, the text of a block, a cell or an item set apart by a space. Returns the
    HTML element."""
    _add_text(parent, el.text or "")
    for child in el:
        tag = tag_name(child)
        if not tag or tag in NEVER or tag in skip:
            pass
        elif tag == "alternatives":  # one formula in several notations: the first
            notations = [c for c in child if tag_name(c)]
            if notations:
                _fill(parent, notations[0], skip)
        elif tag in ("sup", "sub"):
            _fill(etree.SubElement(parent, tag), child, skip)
        elif tag == "table":
            parent.append(_html_table(child))
        elif tag in ("list", "def-list", "ul", "ol"):
            parent.append(_list(child))
        elif tag in ("break", "br"):
            _add_text(parent, " ")
        elif tag in SEPARATE:
            _add_text(parent, " ")
            _fill(parent, child, skip)
            _add_text(parent, " ")
        else:
            _fill(parent, child, skip)
        _add_text(parent, child.tail or "")
    return parent


def _span(value: str | None) -> int:
    try:
        return max(int(value or 1), 1)
    except ValueError:
        return 1


def _rows(table: _Element) -> Iterator[_Element]:
    """The rows of a table, not those of a table in one of its cells."""
    for child in table:
        tag = tag_name(child)
        if tag == "tr":
            yield child
        elif tag in ("thead", "tbody", "tfoot"):
            yield from (row for row in child if tag_name(row) == "tr")


def _html_table(table: _Element) -> _Element:
    """A table, of PMC XML or HTML, as it is: its rows, their header and data cells with their
    spans, a table in a cell kept in it."""
    found = etree.Element("table")
    for tr in _rows(table):
        row = etree.SubElement(found, "tr")
        for cell in tr:
            if (tag := tag_name(cell)) in ("td", "th"):
                spans = {s: str(n) for s in ("rowspan", "colspan") if (n := _span(cell.get(s))) > 1}
                _fill(etree.SubElement(row, tag, spans), cell)
    return found


def _list(el: _Element) -> _Element:
    """A list, of PMC XML (a list, or a list of definitions, its terms with them) or HTML, its
    items each with their content, a list in an item kept in it."""
    ordered = tag_name(el) == "ol" or (el.get("list-type") or "").startswith(
        ("order", "alpha", "roman")
    )
    found = etree.Element("ol" if ordered else "ul")
    for item in el:
        if tag_name(item) in ("list-item", "def-item", "li"):
            _fill(etree.SubElement(found, "li"), item)
    return found


def _top_tables(el: _Element) -> list[_Element]:
    """The tables in an element, not those in a cell of another."""
    return [
        t for t in el.iter("{*}table") if not any(tag_name(a) == "table" for a in t.iterancestors())
    ]


def _labelled(tag: str, label: str) -> _Element:
    """An element starting with a label in bold."""
    found = etree.Element(tag)
    etree.SubElement(found, "b").text = label
    return found


# PMC XML (JATS)

# Elements that are blocks of their own, even inside a paragraph.
BLOCKS = {
    "sec",
    "p",
    "list",
    "fig",
    "table-wrap",
    "supplementary-material",
    "boxed-text",
    "disp-formula",
    "def-list",
    "disp-quote",
    "statement",
    "fig-group",
    "table-wrap-group",
}
# Elements whose text is set apart from the text around it, as a block's is: of PMC XML, then of
# HTML.
SEPARATE = (
    BLOCKS
    | {"term", "def", "def-item", "list-item", "fn", "td", "th", "label", "title"}
    | {"div", "section", "figure", "figcaption", "li", "dt", "dd", "tr", "h2", "h3", "h4"}
)
# Never read for a curation.
DROPPED = {
    "ref-list",
    "ack",
    "fn-group",
    "notes",
    "sub-article",
    "response",
    "object-id",
    "permissions",
}
XLINK = "{http://www.w3.org/1999/xlink}href"


def tag_name(el: _Element) -> str:
    # Comments and processing instructions have a function as tag.
    return etree.QName(el).localname if isinstance(el.tag, str) else ""  # pyright: ignore[reportUnnecessaryIsInstance]


def _text(el: _Element, skip: Collection[str] = ()) -> str:
    """All the text of an element in one line, but for its children whose tag is in `skip`."""
    return one_line(_all_text(_fill(etree.Element("p"), el, skip)))


def _jats_caption(tag: str, el: _Element, kind: str) -> _Element:
    """An element holding the label of a figure, a table or a supplementary material in bold
    (`<kind>.` without a label), then its caption's title and paragraphs."""
    label = el.find("{*}label")
    found = _labelled(tag, (_text(label, BLOCKS) if label is not None else kind) + ".")
    caption = el.find("{*}caption")
    parts: list[_Element] = list(caption) if caption is not None else []
    for part in parts:
        if tag_name(part) in ("title", "p"):
            _add_text(found, " ")
            _fill(found, part)
    return found


def _figure(images: Iterable[str], caption: _Element | None) -> _Element:
    found = etree.Element("figure")
    for src in images:
        etree.SubElement(found, "img", src=src)
    if caption is not None:
        found.append(caption)
    return found


def _jats(
    children: Iterable[_Element], level: int, src: Callable[[str], str]
) -> Iterator[_Element]:
    for child in children:
        tag = tag_name(child)
        if tag in DROPPED or tag in ("label", "title", "caption"):
            continue
        graphics = [src(g.get(XLINK) or "") for g in child.iter("{*}graphic") if g.get(XLINK)]
        if tag in ("sec", "app", "abstract", "trans-abstract", "boxed-text", "app-group"):
            heading = etree.Element(f"h{min(level, 6)}")
            title = child.find("{*}title")
            if title is not None and _text(title, BLOCKS):
                yield _fill(heading, title, BLOCKS)
            elif tag in ("abstract", "trans-abstract"):
                heading.text = "Abstract"
                yield heading
            yield from _jats(child, level + 1, src)
        elif tag == "fig":
            yield _figure(graphics, _jats_caption("figcaption", child, "Figure"))
        elif tag == "table-wrap":
            yield _jats_caption("p", child, "Table")
            if tables := _top_tables(child):
                yield from (_html_table(t) for t in tables)
            elif graphics:  # a table given as an image
                yield _figure(graphics, None)
            for foot in child.iter("{*}table-wrap-foot"):
                yield _fill(etree.Element("p"), foot)
        elif tag == "supplementary-material":
            found = _jats_caption("p", child, "Supplementary material")
            media = child.find(".//{*}media")
            if href := child.get(XLINK) or (media.get(XLINK) if media is not None else None):
                _add_text(found, f" (file {href})")
            yield found
        elif tag in ("list", "def-list"):
            yield _list(child)
        elif tag == "alternatives":  # one block in several notations: the first
            yield from _jats([c for c in child if tag_name(c)][:1], level, src)
        elif blocks := [c for c in child if tag_name(c) in BLOCKS]:
            yield _fill(etree.Element("p"), child, BLOCKS)
            yield from _jats(blocks, level, src)
        else:
            yield _fill(etree.Element("p"), child)


def _figure_files(path: Path) -> Callable[[str], str]:
    """The image of a figure the XML names: its file in `<stem>.fig/` beside the XML, where
    `fetch` saves the PMC figures (a TIFF as PNG: found by its name without
    extension), as a path from the XML's directory; else the name the XML gives."""
    folder = path.with_name(f"{path.stem}.fig")
    files = {p.stem: f"{folder.name}/{p.name}" for p in folder.iterdir()} if folder.is_dir() else {}

    def src(href: str) -> str:
        name = Path(href).name
        return files.get(Path(name).stem if Path(name).suffix.lower() in IMAGES else name, href)

    return src


def jats(path: Path) -> str:
    try:
        root = etree.parse(path, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as e:
        raise ParseError(f"not XML: {e}") from e
    article = root.getroot()
    if tag_name(article) != "article":
        article = article.find(".//{*}article")
        if article is None:
            raise ParseError("XML without an article")
    src = _figure_files(path)
    blocks: list[_Element] = []
    title = article.find("{*}front/{*}article-meta/{*}title-group/{*}article-title")
    if title is not None:
        blocks.append(_fill(etree.Element("h1"), title, BLOCKS))
    meta = article.find("{*}front/{*}article-meta")
    if meta is not None:
        abstracts = [a for a in meta if tag_name(a) in ("abstract", "trans-abstract")]
        blocks.extend(_jats(abstracts, 2, src))
    for part in ("body", "back", "floats-group"):
        el = article.find(f"{{*}}{part}")
        if el is not None:
            blocks.extend(_jats(el, 2, src))
    return html_text(blocks)


# HTML

# The back matter of a PMC article page, left out as in its XML; `notes-<n>` sections too.
PMC_PAGE_DROPPED = {"kwd-group", "ack", "fn-group", "ref-list", "associated-data", "contrib-info"}


def class_names(el: _Element) -> set[str]:
    return set((el.get("class") or "").split())


def _pmc_page(children: Iterable[_Element], level: int) -> Iterator[_Element]:
    """The blocks of a PMC article page, its XML rendered as HTML: sections and their titles,
    paragraphs, lists, figures with their images and captions, tables, supplementary
    materials."""
    for child in children:
        tag, classes = tag_name(child), class_names(child)
        images = [src for img in child.iter("img") if (src := img.get("src"))]
        if tag == "section":
            if classes & PMC_PAGE_DROPPED or (child.get("id") or "").startswith("notes"):
                continue
            if "tw" in classes:  # a table
                head = child.find("h4")
                caption = child.find("div[@class='caption p']")
                found = _labelled("p", _text(head) if head is not None else "Table.")
                if caption is not None:
                    _add_text(found, " ")
                    _fill(found, caption)
                yield found
                if tables := _top_tables(child):
                    yield from (_html_table(t) for t in tables)
                elif images:  # a table given as an image
                    yield _figure(images, None)
                for foot in child.iterfind(".//div"):
                    if "tw-foot" in class_names(foot):
                        yield _fill(etree.Element("p"), foot)
            elif "sm" in classes:  # a supplementary material: its caption and file
                links = [a.get("href", "") for a in child.iter("a")]
                names = list(dict.fromkeys(Path(h).name for h in links if "/bin/" in h))
                found = _labelled("p", "Supplementary material.")
                _add_text(found, " ")
                _fill(found, child, {"a", "sup"})
                if names:
                    _add_text(found, f" (file {', '.join(names)})")
                yield found
            else:
                title = next((h for h in child if tag_name(h) in ("h2", "h3", "h4", "h5")), None)
                if title is not None and _text(title):
                    yield _fill(etree.Element(f"h{min(level, 6)}"), title)
                yield from _pmc_page(child, level + 1)
        elif tag == "figure":
            head = next((h for h in child if tag_name(h) in ("h3", "h4")), None)
            caption = _labelled("figcaption", _text(head) if head is not None else "Figure.")
            if (text := child.find("figcaption")) is not None:
                _add_text(caption, " ")
                _fill(caption, text)
            yield _figure(images, caption)
        elif tag in ("h2", "h3", "h4", "h5"):
            continue  # a section title, given with its section
        elif tag in ("ul", "ol"):
            yield _list(child)
        elif tag == "table":
            yield _html_table(child)
        elif tag in ("div", "dl") and any(
            tag_name(c) in ("p", "section", "figure", "table", "ul", "ol", "div") for c in child
        ):
            yield from _pmc_page(child, level)
        elif _text(child):
            yield _fill(etree.Element("p"), child)


def pmc_page(doc: _Element, body: _Element) -> str:
    title = next(doc.iter("h1"), None)
    blocks = [_fill(etree.Element("h1"), title)] if title is not None else []
    blocks.extend(_pmc_page(body, 2))
    return html_text(blocks)


def _cleaned(el: _Element) -> Iterator[_Element]:
    """An element of trafilatura's HTML with only the tags and attributes of the HTML texts
    (`TAGS`): another tag holding blocks gives them, else a paragraph of its content."""
    tag = tag_name(el)
    if tag in NEVER:
        return
    if tag in TAGS:
        yield _clean_into(etree.Element(tag, _attributes(el, tag)), el)
    elif any(tag_name(c) in TAGS and tag_name(c) not in ("b", "sup", "sub", "br") for c in el):
        for child in el:
            yield from _cleaned(child)
    else:
        yield _clean_into(etree.Element("p"), el)


def _attributes(el: _Element, tag: str) -> dict[str, str]:
    return {str(k): str(v) for k, v in el.attrib.items() if k in TAGS[tag]}


def _clean_into(parent: _Element, el: _Element) -> _Element:
    """The content of an element added to an HTML element, each tag of the HTML texts kept with
    its attributes, any other cleaned away, its text kept."""
    _add_text(parent, el.text or "")
    for child in el:
        tag = tag_name(child)
        if tag in TAGS:
            _clean_into(etree.SubElement(parent, tag, _attributes(child, tag)), child)
        elif tag and tag not in NEVER:
            _clean_into(parent, child)
        _add_text(parent, child.tail or "")
    return parent


def html(path: Path) -> str:
    """A PMC article page by its structure, as its XML; any other page by its main text, as
    trafilatura finds it, with its tables and its images."""
    raw = path.read_bytes()
    if b"main-article-body" in raw:
        doc = etree.fromstring(raw, etree.HTMLParser())
        for body in doc.iter("section"):
            if "main-article-body" in class_names(body):
                return pmc_page(doc, body)
    found = trafilatura.extract(
        raw,  # bytes: trafilatura finds the page's charset
        output_format="html",
        include_tables=True,
        include_comments=False,
        include_images=True,
        include_links=False,
        include_formatting=True,  # superscripts and subscripts
        favor_recall=True,
    )
    body = etree.fromstring(found, etree.HTMLParser()).find("body") if found else None
    if body is None or not _all_text(body).strip():
        raise ParseError("no main text in the HTML page")
    return html_text(block for child in body for block in _cleaned(child))


# PDF


@dataclass
class _Line:
    """A line of a page as MuPDF reads it: its text, the baseline and the size of its largest
    characters, and whether it is horizontal (not rotated)."""

    text: str
    baseline: float
    size: float
    horizontal: bool


def _beside(a: _Line, b: _Line) -> bool:
    """On one line of the page: both horizontal, their baselines closer than half the smaller
    size."""
    return a.horizontal and b.horizontal and abs(a.baseline - b.baseline) < min(a.size, b.size) / 2


def _page(page: Any) -> str:
    """A page's text as MuPDF reads it, line by line, in its order; a line read right after
    another and beside it (the next cell of a table's row) continues it, after a tab. Nothing
    is moved: two columns of text are never mixed."""
    rows: list[str] = []
    before: _Line | None = None
    blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]  # pyright: ignore[reportUnknownMemberType]
    for line in (line for block in blocks for line in block["lines"]):
        spans = [s for s in line["spans"] if s["text"].strip()]
        if not spans:
            continue
        largest = max(spans, key=lambda s: s["size"])
        text = "".join(s["text"] for s in line["spans"]).strip()
        current = _Line(text, largest["origin"][1], largest["size"], line["dir"][0] > 0.99)
        if before is not None and _beside(before, current):
            rows[-1] += "\t" + text
        else:
            rows.append(text)
        before = current
    return "\n".join(rows)


def pdf(path: Path) -> str:
    try:
        document = pymupdf.open(path)
    except pymupdf.FileDataError as e:
        raise ParseError(f"not a PDF: {e}") from e
    with document:
        pages = [_page(page) for page in document]
    if not any(pages):
        raise ParseError("no text layer: a scanned PDF")
    return "".join(f"--- page {n} ---\n\n{p}\n\n" for n, p in enumerate(pages, 1))


# Spreadsheets


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime | date):
        return value.isoformat()
    return one_line(str(value))


def _padded(rows: Iterable[list[str]]) -> list[list[str]]:
    """A table's rows, each as many cells as its widest row: its empty rows, and the empty
    cells after the last that holds a value, left out."""
    table: list[list[str]] = []
    for cells in rows:
        while cells and not cells[-1].strip():
            cells = cells[:-1]
        if cells:
            table.append(cells)
    width = max((len(cells) for cells in table), default=0)
    return [cells + [""] * (width - len(cells)) for cells in table]


def _tsv(rows: list[list[Any]]) -> str:
    """A sheet's rows, tab-separated, padded."""
    return "".join(
        "\t".join(cells) + "\n" for cells in _padded([_cell(v) for v in r] for r in rows)
    )


def xlsx(path: Path) -> list[tuple[str, str]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return [
            (ws.title, _tsv([list(r) for r in ws.iter_rows(values_only=True)]))
            for ws in workbook.worksheets
        ]
    finally:
        workbook.close()


def _xls_value(cell: Any, datemode: Literal[0, 1]) -> Any:
    """A cell's value; a date as a date, as in .xlsx (a number in the file)."""
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate.xldate_as_datetime(cell.value, datemode)
        except xlrd.xldate.XLDateError:
            pass
    return cell.value


def xls(path: Path) -> list[tuple[str, str]]:
    book: Any = xlrd.open_workbook(str(path))
    sheets: list[tuple[str, str]] = []
    for sheet in book.sheets():
        rows = [[_xls_value(c, book.datemode) for c in sheet.row(i)] for i in range(sheet.nrows)]
        sheets.append((str(sheet.name), _tsv(rows)))
    return sheets


# Word (.docx): its XML cleaned up

# Word elements whose content is not the document's text: formatting (every `...Pr`), tracked
# deletions, a field's code, the old form of an element Word also writes in a newer one, a
# note's own mark, comment marks.
WORD_LEFT_OUT = {
    "del",
    "delText",
    "moveFrom",
    "instrText",
    "Fallback",
    "footnoteRef",
    "endnoteRef",
    "commentReference",
    "tblGrid",
}
# The Word elements that give content: a field's code hides them, never the runs around them,
# which mark where the code ends.
WORD_CONTENT = {
    "t",
    "tab",
    "ptab",
    "br",
    "cr",
    "noBreakHyphen",
    "sym",
    "blip",
    "imagedata",
    "footnoteReference",
    "endnoteReference",
    "tbl",
    "p",
}
# The Symbol font: Word writes "IFN-γ" as "IFN-g" set in that font, or inserts the symbol by its
# code in the font, from U+F000. Its Greek letters and the signs a publication uses.
SYMBOL = {
    **dict(zip("ABGDEZHQIKLMNXOPRSTUFCYW", "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ", strict=True)),
    **dict(zip("abgdezhqiklmnxoprstufcywjJvV", "αβγδεζηθικλμνξοπρστυφχψωϕϑϖς", strict=True)),
    **dict(zip("-~@^\xa2\xa3\xa5\xab\xac\xad\xae\xaf", "−∼≅⊥′≤∞↔←↑→↓", strict=True)),
    **dict(
        zip("\xb0\xb1\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xbb\xbc", "°±″≥×∝∂•÷≠≡≈…", strict=True)
    ),
    **dict(zip("\xc6\xc7\xc8\xce\xd5\xd6\xd7\xdb\xde\xe5\xf2", "∅∩∪∈∏√⋅⇔⇒∑∫", strict=True)),
}
SYMBOL_CODES = str.maketrans({**SYMBOL, **{chr(0xF000 + ord(k)): v for k, v in SYMBOL.items()}})


def _w(el: _Element | None, name: str) -> str:
    """A Word attribute, by its name in any namespace; empty when it, or its element, is missing."""
    if el is None:
        return ""
    return next((str(v) for k, v in el.attrib.items() if etree.QName(k).localname == name), "")


def _child(el: _Element, path: str) -> _Element | None:
    """A descendant by its tags, in any namespace (`pPr/pStyle`)."""
    return el.find("/".join(f"{{*}}{t}" for t in path.split("/")))


def _all(el: _Element | None, tag: str) -> list[_Element]:
    """The descendants of an element with a tag, in any namespace."""
    return [] if el is None else list(el.iter(f"{{*}}{tag}"))


def _outline(el: _Element) -> int | None:
    """The heading level an outline level gives (Word's 0 to 8; 9 is body text)."""
    level = _w(_child(el, "pPr/outlineLvl"), "val")
    return int(level) + 1 if level.isdigit() and int(level) < 9 else None


@dataclass
class _Docx:
    """What the cleanup of a Word document reads besides its body."""

    headings: dict[str, int]  # a paragraph style's heading level
    lists: dict[str, int]  # a paragraph style's list level, for a style that numbers
    images: dict[str, list[str]]  # an image's files beside the document, by its relationship
    notes: dict[str, _Element]  # footnotes and endnotes, by `footnote <id>` or `endnote <id>`
    referenced: list[str]  # the notes, in the order the text refers to them
    fields: list[bool]  # the open fields of a paragraph, True while in their code


def _numbering(el: _Element) -> int | None:
    """The list level a paragraph or a style numbers at, if it numbers."""
    numbering = _child(el, "pPr/numPr")
    if numbering is None or _w(_child(numbering, "numId"), "val") in ("", "0"):
        return None
    return int(_w(_child(numbering, "ilvl"), "val") or 0)


def _style_levels(styles: _Element | None) -> tuple[dict[str, int], dict[str, int]]:
    """The heading level of each paragraph style that heads (`heading N`, `Title`, or an outline
    level), and the list level of each that numbers."""
    headings: dict[str, int] = {}
    lists: dict[str, int] = {}
    for style in _all(styles, "style"):
        name, key = _w(_child(style, "name"), "val").lower(), _w(style, "styleId")
        if m := re.fullmatch(r"heading (\d)", name):
            headings[key] = int(m.group(1))
        elif name == "title":
            headings[key] = 1
        elif level := _outline(style):
            headings[key] = level
        elif (level := _numbering(style)) is not None:
            lists[key] = level
    return headings, lists


def _image_files(path: Path, rels: _Element | None) -> dict[str, list[str]]:
    """The files of each image of a Word document, by its relationship: beside the document, as
    `prepare` saves them (`<file>.<image>`, a TIFF as PNG, several for several frames), else its
    path in the document."""
    beside: dict[str, list[str]] = {}
    for file in sorted(path.parent.iterdir()):
        if file.name.startswith(f"{path.name}."):
            beside.setdefault(re.sub(r"-\d+$", "", file.stem), []).append(file.name)
    images: dict[str, list[str]] = {}
    for rel in _all(rels, "Relationship"):
        target = rel.get("Target") or ""
        if target and rel.get("TargetMode") != "External":
            saved = beside.get(Path(f"{path.name}.{Path(target).name}").stem)
            images[rel.get("Id") or ""] = saved or [f"word/{target}"]
    return images


def _docx(path: Path, package: zipfile.ZipFile) -> tuple[_Element, _Docx]:
    """A Word document's body, and what its cleanup reads besides."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    names = set(package.namelist())

    def part(name: str) -> _Element | None:
        return etree.fromstring(package.read(name), parser) if name in names else None

    document = part("word/document.xml")
    body = _child(document, "body") if document is not None else None
    if body is None:
        raise ParseError("a Word document without its body")
    notes = {
        f"{kind} {_w(note, 'id')}": note
        for kind in ("footnote", "endnote")
        for note in _all(part(f"word/{kind}s.xml"), kind)
    }
    headings, lists = _style_levels(part("word/styles.xml"))
    images = _image_files(path, part("word/_rels/document.xml.rels"))
    return body, _Docx(headings, lists, images, notes, [], [])


def _word_level(paragraph: _Element, docx: _Docx) -> tuple[str, int]:
    """A paragraph's kind, by its own properties, else its style's: a heading and its level, a
    list item and its level, else a paragraph."""
    style = _w(_child(paragraph, "pPr/pStyle"), "val")
    if level := _outline(paragraph) or docx.headings.get(style):
        return "h", min(level, 6)
    if (level := _numbering(paragraph)) is not None or (level := docx.lists.get(style)) is not None:
        return "li", level
    return "p", 0


def _word_inline(parent: _Element, el: _Element, docx: _Docx, symbol: bool = False) -> _Element:
    """The content of a Word element added to an HTML element: its text (in the Symbol font, as
    the characters it shows), its superscripts and subscripts, its images, the text of its text
    boxes, its tables, the results of its fields, references to its notes; its formatting
    cleaned away. Returns the HTML element."""
    for child in el:
        tag = tag_name(child)
        if not tag or tag in WORD_LEFT_OUT or tag.endswith("Pr"):
            continue
        if tag == "fldChar":  # a field: its code, then its result
            kind = _w(child, "fldCharType")
            if kind == "begin":
                docx.fields.append(True)
            elif kind == "separate" and docx.fields:
                docx.fields[-1] = False
            elif kind == "end" and docx.fields:
                docx.fields.pop()
        elif any(docx.fields) and tag in WORD_CONTENT:  # a field's code
            continue
        elif tag == "t":
            _add_text(parent, (child.text or "").translate(SYMBOL_CODES if symbol else {}))
        elif tag in ("tab", "ptab"):
            _add_text(parent, " ")
        elif tag in ("br", "cr"):
            if _w(child, "type") in ("page", "column"):
                _add_text(parent, " ")
            else:
                etree.SubElement(parent, "br")
        elif tag == "noBreakHyphen":
            _add_text(parent, "-")
        elif tag == "sym" and (code := _w(child, "char")):
            value = chr(int(code, 16))
            _add_text(
                parent, value.translate(SYMBOL_CODES) if _w(child, "font") == "Symbol" else value
            )
        elif tag == "r":
            align = _w(_child(child, "rPr/vertAlign"), "val")
            script = {"superscript": "sup", "subscript": "sub"}.get(align)
            fonts = _child(child, "rPr/rFonts")
            in_symbol = "Symbol" in (_w(fonts, "ascii"), _w(fonts, "hAnsi"), _w(fonts, "cs"))
            target = etree.SubElement(parent, script) if script else parent
            _word_inline(target, child, docx, in_symbol)
        elif tag in ("blip", "imagedata"):
            for src in docx.images.get(_w(child, "embed") or _w(child, "id"), []):
                etree.SubElement(parent, "img", src=src)
        elif tag in ("footnoteReference", "endnoteReference"):
            note = f"{tag.removesuffix('Reference')} {_w(child, 'id')}"
            if note in docx.notes:
                if note not in docx.referenced:
                    docx.referenced.append(note)
                etree.SubElement(parent, "sup").text = str(docx.referenced.index(note) + 1)
        elif tag == "tbl":
            parent.append(_word_table(child, docx))
        elif tag == "p":  # a paragraph in a cell or a text box
            _add_text(parent, " ")
            _word_inline(parent, child, docx)
            _add_text(parent, " ")
        else:  # a run's container, a text box, a content control, a link, an insertion...
            _word_inline(parent, child, docx)
    return parent


def _word_table(tbl: _Element, docx: _Docx) -> _Element:
    """A Word table: its rows and cells, a cell spanning columns (`gridSpan`) as `colspan`, cells
    merged down a column (`vMerge`) as one with its `rowspan`, a table in a cell kept in it."""
    table = etree.Element("table")
    above: dict[int, _Element] = {}  # by grid column, the cell a merge down the column starts
    for tr in (r for r in tbl.iter("{*}tr") if r.getparent() is tbl or _owner(r) is tbl):
        row = etree.SubElement(table, "tr")
        column = int(_w(_child(tr, "trPr/gridBefore"), "val") or 0)
        for tc in (c for c in tr.iter("{*}tc") if _owner(c) is tr):
            span = max(int(_w(_child(tc, "tcPr/gridSpan"), "val") or 1), 1)
            merge = _child(tc, "tcPr/vMerge")
            if merge is not None and _w(merge, "val") != "restart" and column in above:
                cell = above[column]
                cell.set("rowspan", str(int(cell.get("rowspan") or 1) + 1))
            else:
                cell = etree.SubElement(row, "td", {"colspan": str(span)} if span > 1 else {})
                _word_inline(cell, tc, docx)
                if merge is not None:
                    above[column] = cell
                else:
                    above.pop(column, None)
            column += span
    return table


def _owner(el: _Element) -> _Element | None:
    """The row or table an element of a table belongs to, past the content controls around it."""
    parent = el.getparent()
    while parent is not None and tag_name(parent) not in ("tr", "tbl"):
        parent = parent.getparent()
    return parent


def _word_blocks(el: _Element, docx: _Docx) -> list[_Element]:
    """The blocks of a Word body: its paragraphs and headings, its lists (numbered paragraphs,
    nested by level), its tables, those of its content controls."""
    blocks: list[_Element] = []
    lists: list[_Element] = []  # the open lists, by level
    for child in el:
        tag = tag_name(child)
        if not tag or tag in WORD_LEFT_OUT or tag.endswith("Pr"):
            continue
        if tag == "p":
            kind, level = _word_level(child, docx)
            docx.fields.clear()
            block = _word_inline(etree.Element(f"h{level}" if kind == "h" else kind), child, docx)
            if kind != "li":
                lists.clear()
                blocks.append(block)
                continue
            del lists[level + 1 :]
            while len(lists) <= level:
                nested = etree.Element("ul")
                if lists:
                    if not len(lists[-1]):
                        etree.SubElement(lists[-1], "li")
                    lists[-1][-1].append(nested)
                else:
                    blocks.append(nested)
                lists.append(nested)
            lists[level].append(block)
        elif tag == "tbl":
            lists.clear()
            blocks.append(_word_table(child, docx))
        else:  # a content control, an insertion...: its blocks
            lists.clear()
            blocks.extend(_word_blocks(child, docx))
    return blocks


def word(path: Path) -> str:
    """A Word document (`.docx`), its XML cleaned up to HTML, read in its order: its paragraphs,
    headings and lists, its tables, its images where they stand, the text of its text boxes, its
    content controls and its tracked insertions (its deletions left out), the results of its
    fields (their code left out), its footnotes and endnotes at the end; its formatting, headers,
    footers and comments left out. An element it does not know keeps its text."""
    try:
        package = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise ParseError(f"not a Word document: {e}") from e
    with package:
        body, docx = _docx(path, package)
        blocks = _word_blocks(body, docx)
    for n, note in enumerate(docx.referenced, 1):
        paragraph = etree.Element("p")
        etree.SubElement(paragraph, "sup").text = str(n)
        _add_text(paragraph, " ")
        blocks.append(_word_inline(paragraph, docx.notes[note], docx))
    return html_text(blocks)


# Old Word documents (Word 97-2003, [MS-DOC])

# Paragraph properties that place a paragraph in a table.
SPRM_IN_TABLE, SPRM_ROW_END, SPRM_DEPTH = 0x2416, 0x2417, 0x6649
SPRM_TABLE_DEFINITIONS = (0xD608, 0xD606)  # sprmTDefTable, sprmTDefTable10
SPRM_TABS = 0xC615  # sprmPChgTabs
SPRM_HUGE_PAPX = 0x6646  # the properties are in the Data stream, at this offset


@dataclass
class _Piece:
    """A run of the main text stored in one place of the WordDocument stream."""

    cp: int  # its first character
    length: int
    fc: int  # the byte offset of its first character
    width: int  # bytes per character: 1 (cp1252) or 2 (UTF-16)


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


@dataclass
class _Properties:
    """A paragraph's properties: the values of 1 to 4 bytes, and for the end of a table row the
    edges of its cells (sprmTDefTable)."""

    values: dict[int, int]
    edges: tuple[int, ...] = ()


def _sprms(grpprl: bytes) -> _Properties:
    """The properties set by a list of property modifiers."""
    found = _Properties({})
    i = 0
    while i + 2 <= len(grpprl):
        sprm = _u16(grpprl, i)
        i += 2
        spra = sprm >> 13
        if spra in (0, 1):
            size = 1
        elif spra in (2, 4, 5):
            size = 2
        elif spra == 3:
            size = 4
        elif spra == 7:
            size = 3
        elif sprm in SPRM_TABLE_DEFINITIONS:
            size = 1 + _u16(grpprl, i)  # 2 bytes of size, counting itself minus 1
        elif sprm == SPRM_TABS and i < len(grpprl) and grpprl[i] == 255:
            deleted = grpprl[i + 1]  # tabs deleted (positions, closures), then tabs added
            added = grpprl[i + 2 + 4 * deleted]
            size = 3 + 4 * deleted + 3 * added
        else:
            size = 1 + grpprl[i] if i < len(grpprl) else 0
        if size in (1, 2, 4) and i + size <= len(grpprl):
            found.values[sprm] = int.from_bytes(grpprl[i : i + size], "little")
        elif sprm in SPRM_TABLE_DEFINITIONS and i + size <= len(grpprl):
            cells = grpprl[i + 2]  # then the edges of the cells, in twips
            found.edges = struct.unpack_from(f"<{cells + 1}h", grpprl, i + 3)
        i += size
    return found


def _paragraphs(
    document: bytes, table: bytes, data: bytes, fc_lcb: int
) -> list[tuple[int, int, _Properties]]:
    """Every paragraph's byte range in the WordDocument stream and its properties, from the
    formatted disk pages listed in PlcBtePapx; properties too large for their page are in the
    Data stream (sprmPHugePapx)."""
    fc_plc, lcb_plc = struct.unpack_from("<II", document, fc_lcb + 13 * 8)
    plc = table[fc_plc : fc_plc + lcb_plc]
    n = (lcb_plc - 4) // 8
    paragraphs: list[tuple[int, int, _Properties]] = []
    for k in range(n):
        page = (_u32(plc, 4 * (n + 1) + 4 * k) & 0x3FFFFF) * 512
        fkp = document[page : page + 512]
        if len(fkp) < 512:
            raise ParseError("a Word document with a broken paragraph table")
        runs = fkp[511]
        fcs = struct.unpack_from(f"<{runs + 1}I", fkp, 0)
        for r in range(runs):
            offset = 2 * fkp[4 * (runs + 1) + 13 * r]
            properties = _Properties({})
            if offset:
                cb = fkp[offset]
                start, size = (offset + 1, 2 * cb - 1) if cb else (offset + 2, 2 * fkp[offset + 1])
                properties = _sprms(fkp[start + 2 : start + size])  # after the style index
                if (huge := properties.values.get(SPRM_HUGE_PAPX)) is not None:
                    if huge + 2 > len(data):
                        raise ParseError("a Word document with its properties out of its file")
                    properties = _sprms(data[huge + 2 : huge + 2 + _u16(data, huge)])
            paragraphs.append((fcs[r], fcs[r + 1], properties))
    paragraphs.sort(key=lambda p: p[0])
    return paragraphs


def _word_document(path: Path) -> tuple[str, list[int], list[tuple[int, int, _Properties]]]:
    """The main text of a Word 97-2003 document, the byte offset of each of its characters, and
    its paragraphs."""
    try:
        ole = olefile.OleFileIO(str(path))
    except OSError as e:
        raise ParseError(f"not a Word 97-2003 document: {e}") from e
    with ole:
        if not ole.exists("WordDocument"):
            raise ParseError("not a Word 97-2003 document")
        document = ole.openstream("WordDocument").read()
        if _u16(document, 0) != 0xA5EC or _u16(document, 2) < 0x00C1:
            raise ParseError("a Word document older than Word 97")
        flags = _u16(document, 0x0A)
        if flags & 0x0100:
            raise ParseError("an encrypted Word document")
        table_name = "1Table" if flags & 0x0200 else "0Table"
        if not ole.exists(table_name):
            raise ParseError("a Word document without its table stream")
        table = ole.openstream(table_name).read()
        data = ole.openstream("Data").read() if ole.exists("Data") else b""
    # The FIB: 32 bytes, then 16-bit values, 32-bit values, then (fc, lcb) pairs.
    fc_lw = 34 + 2 * _u16(document, 32) + 2
    fc_lcb = fc_lw + 4 * _u16(document, fc_lw - 2) + 2
    ccp_text = _u32(document, fc_lw + 12)
    fc_clx, lcb_clx = struct.unpack_from("<II", document, fc_lcb + 33 * 8)
    clx = table[fc_clx : fc_clx + lcb_clx]
    i = 0
    while i < len(clx) and clx[i] == 0x01:  # property modifiers, before the piece table
        i += 3 + _u16(clx, i + 1)
    if i >= len(clx) or clx[i] != 0x02:
        raise ParseError("a Word document without a piece table")
    lcb = _u32(clx, i + 1)
    plc = clx[i + 5 : i + 5 + lcb]
    n = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    pieces: list[_Piece] = []
    for k in range(n):
        fc = _u32(plc, 4 * (n + 1) + 8 * k + 2)
        compressed = bool(fc & 0x40000000)
        start = (fc & 0x3FFFFFFF) // 2 if compressed else fc
        pieces.append(_Piece(cps[k], cps[k + 1] - cps[k], start, 1 if compressed else 2))
    chars: list[str] = []
    offsets: list[int] = []
    for piece in pieces:
        if piece.cp >= ccp_text:
            break
        length = min(piece.length, ccp_text - piece.cp)
        raw = document[piece.fc : piece.fc + piece.width * length]
        decoded = raw.decode("cp1252" if piece.width == 1 else "utf-16-le", errors="replace")
        chars.append(decoded)
        position = piece.fc
        for char in decoded:  # a character beyond U+FFFF takes 4 bytes in UTF-16
            offsets.append(position)
            position += 1 if piece.width == 1 else len(char.encode("utf-16-le"))
    return "".join(chars), offsets, _paragraphs(document, table, data, fc_lcb)


def _aligned(rows: list[tuple[list[str], tuple[int, ...]]]) -> _Element:
    """The rows of one table, aligned. A cell spanning several columns is one wider cell in
    Word: in a row with fewer cells than the fullest row, each cell is placed by its edges on the
    nearest edges of the fullest row, its span the columns it covers."""
    grid = max((edges for _, edges in rows), key=len, default=())
    table = etree.Element("table")
    for cells, edges in rows:
        spans = [1] * len(cells)
        if len(cells) < len(grid) - 1 and len(edges) == len(cells) + 1:
            column = [min(range(len(grid)), key=lambda k: abs(grid[k] - e)) for e in edges]
            spans = [max(b - a, 1) for a, b in zip(column, column[1:], strict=False)]
        row = etree.SubElement(table, "tr")
        for cell, span in zip(cells, spans, strict=False):
            etree.SubElement(row, "td", {"colspan": str(span)} if span > 1 else {}).text = cell
    return table


def doc(path: Path) -> str:
    """An old Word document, as HTML: its paragraphs, and its tables. Each mark
    that ends a paragraph (a carriage return, a cell mark in a table, a page or section break)
    is read with its paragraph's properties: in a table or not, the end of a cell or of a row. A
    nested table's cells are flattened into the cell holding them."""
    text, offsets, paragraphs = _word_document(path)
    starts = [p[0] for p in paragraphs]

    def properties(i: int) -> _Properties:
        k = bisect.bisect_right(starts, offsets[i]) - 1
        if k >= 0 and paragraphs[k][0] <= offsets[i] < paragraphs[k][1]:
            return paragraphs[k][2]
        return _Properties({})

    blocks: list[_Element] = []
    table: list[tuple[list[str], tuple[int, ...]]] = []  # the rows of the current table
    row: list[str] = []
    current: list[str] = []

    def end_paragraph() -> None:
        """The table before the paragraph, if any, then the paragraph."""
        nonlocal table, row, current
        if row:  # cells whose row end was not found: kept, never lost
            table.append((row, ()))
        if table:
            blocks.append(_aligned(table))
        paragraph = etree.Element("p")
        paragraph.text = one_line("".join(current))
        blocks.append(paragraph)
        table, row, current = [], [], []

    fields: list[bool] = []  # open fields, True while in their code (hidden)
    for i, char in enumerate(text):
        if char == "\x13":
            fields.append(True)
        elif char == "\x14":
            if fields:
                fields[-1] = False
        elif char == "\x15":
            if fields:
                fields.pop()
        elif any(fields):
            continue
        elif char in "\r\x07\x0c":
            p = properties(i)
            depth = p.values.get(SPRM_DEPTH, 1 if p.values.get(SPRM_IN_TABLE) else 0)
            row_end = char != "\x0c" and p.values.get(SPRM_ROW_END) and depth <= 1
            if char == "\x07" and depth <= 1 and not row_end:
                row.append(one_line("".join(current)))  # the end of a cell
                current = []
            elif row_end:
                table.append((row, p.edges))
                row, current = [], []
            elif depth >= 1:
                current.append(" ")  # a paragraph, a page break or a nested table's mark in a cell
            else:
                end_paragraph()  # a paragraph mark, or a page or section break
        elif char == "\x0b":  # a line break
            current.append(" ")
        elif char in "\x01\x08\x1f":  # pictures, drawn objects, optional hyphens
            continue
        elif char == "\x1e":  # non-breaking hyphen
            current.append("-")
        else:
            current.append(char)
    end_paragraph()
    return html_text(blocks)


# Downloaded files made ready to read

# Documents that are zip archives, and the folder of the images each holds.
DOCUMENT_MEDIA = {
    ".docx": "word/media/",
    ".xlsx": "xl/media/",
    ".xlsm": "xl/media/",
    ".pptx": "ppt/media/",
}
# Videos: no curation reads them.
VIDEOS = {".mp4", ".mov", ".avi", ".wmv", ".mpg", ".mpeg", ".m4v", ".webm"}
# Images are read as they are, never converted to text.
IMAGES = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".eps", ".svg", ".webp"}
# Images the Read tool cannot open, saved as PNG.
TO_PNG = {".tif", ".tiff", ".bmp"}


def _safe_name(name: str, taken: set[str]) -> str:
    """A file name with no path and no odd character, unique in the directory."""
    name = re.sub(r"[^\w.-]", "_", name).lstrip(".") or "file"
    stem, suffix, n = Path(name).stem, Path(name).suffix, 1
    while name in taken:
        n += 1
        name = f"{stem}_{n}{suffix}"
    taken.add(name)
    return name


def save(folder: Path, name: str, body: bytes) -> Path:
    """A file saved in the folder under a name no other file there has."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / _safe_name(name, {p.name for p in folder.iterdir()})
    path.write_bytes(body)
    return path


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGES


def is_video(name: str) -> bool:
    """A video, or an archive named as videos (`movies_s1_to_s3.zip`)."""
    return Path(name).suffix.lower() in VIDEOS or re.search(r"movie|video", name, re.I) is not None


def as_png(name: str, body: bytes) -> list[tuple[str, bytes]]:
    """A TIFF or a BMP image as PNG, in RGB (a TIFF can be CMYK), one file per image it holds
    (`<name>-<n>.png` when several); none when it cannot be opened."""
    try:
        document = pymupdf.open(stream=body)
    except pymupdf.FileDataError:
        return []
    with document:  # one page per image, its image at its own resolution
        blocks = [
            block
            for page in document
            for block in cast(dict[str, Any], page.get_text("dict"))["blocks"]  # pyright: ignore[reportUnknownMemberType]
            if block["type"] == 1
        ]
    images = [
        cast(bytes, pymupdf.Pixmap(pymupdf.csRGB, pymupdf.Pixmap(b["image"])).tobytes("png"))
        for b in blocks
    ]
    stem = Path(name).stem
    if len(images) > 1:
        return [(f"{stem}-{n}.png", image) for n, image in enumerate(images, 1)]
    return [(f"{stem}.png", image) for image in images]


Files = Iterator[tuple[str, bytes]]


def _zip_files(path: Path) -> Files:
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if not info.is_dir():
                yield info.filename, archive.read(info)


def _rar_files(path: Path) -> Files:
    archive = rarfile.RarFile(path)
    for info in archive.infolist():
        if not info.is_dir():
            yield info.filename, archive.read(info)


def _7z_files(path: Path) -> Files:
    files = BytesIOFactory(sys.maxsize)  # a file over its limit would be cut short
    with py7zr.SevenZipFile(path) as archive:
        archive.extractall(factory=files)
    for name, file in files.products.items():
        file.seek(0)
        yield name, file.read()


def _tar_files(path: Path) -> Files:
    """A tar archive's files, the archive compressed or not (gzip, bzip2, xz); a `.gz` that is
    no tar, its one compressed file, named without `.gz`."""
    if path.name.lower().endswith(".gz") and not tarfile.is_tarfile(path):
        yield path.stem, gzip.decompress(path.read_bytes())
        return
    with tarfile.open(path) as archive:
        for member in archive:
            if member.isfile() and (file := archive.extractfile(member)):
                yield member.name, file.read()


# The archives, by the end of their name, each with the reader of its files.
ARCHIVES: dict[str, Callable[[Path], Files]] = {
    ".zip": _zip_files,
    ".rar": _rar_files,
    ".7z": _7z_files,
    ".tar": _tar_files,
    ".tgz": _tar_files,
    ".gz": _tar_files,
    ".tar.bz2": _tar_files,
    ".tar.xz": _tar_files,
}
# What a reader raises on a file that is no archive, or a damaged one.
ARCHIVE_ERRORS = (
    zipfile.BadZipFile,
    rarfile.RarFileError,
    BadRarFile,
    py7zr.Bad7zFile,
    tarfile.TarError,
    gzip.BadGzipFile,
    lzma.LZMAError,
    zlib.error,
    EOFError,
)


def archive_files(path: Path) -> list[tuple[str, bytes]] | None:
    """The files of an archive (`ARCHIVES`, by the end of its name: zip, RAR, 7z, tar, gzip),
    each its name, without its folder, and its body; folders, `__MACOSX` and hidden files left
    out, and videos. None when the file is no archive, or one that cannot be read or holds no
    file."""
    reader = next((r for end, r in ARCHIVES.items() if path.name.lower().endswith(end)), None)
    if reader is None:
        return None
    try:
        files = list(reader(path))
    except ARCHIVE_ERRORS:
        return None
    if not files:
        return None
    kept: list[tuple[str, bytes]] = []
    for name, body in files:
        member = Path(name)
        hidden = "__MACOSX" in member.parts or member.name[:1] == "."
        if not hidden and not is_video(member.name):
            kept.append((member.name, body))
    return kept


def prepare(base: Path, file: str) -> list[str]:
    """A downloaded file, at a path relative to `base`, made ready to read: an archive replaced
    by its files (`archive_files`), saved beside it and each made ready likewise (an archive in
    an archive unpacked), kept as it is when it cannot be read or holds no file; a TIFF or a BMP
    image replaced by its PNG (`as_png`), kept as it is when it cannot be opened; a document that
    is a zip archive (`DOCUMENT_MEDIA`) kept, each image it holds but its videos saved beside it,
    `<file>.<image>`, and made ready likewise. Returns the files to list, paths relative to
    `base`: an archive's files, or the file, or its PNG, then a document's images."""
    path = base / file
    suffix = path.suffix.lower()
    if (files := archive_files(path)) is not None:
        path.unlink()
        ready: list[str] = []
        for name, body in files:
            saved = save(path.parent, name, body)
            ready += prepare(base, str(Path(file).with_name(saved.name)))
        return ready
    if suffix in TO_PNG:
        images = as_png(path.name, path.read_bytes())
        if not images:
            return [file]
        path.unlink()
        return [str(Path(file).with_name(save(path.parent, n, c).name)) for n, c in images]
    ready = [file]
    if suffix not in DOCUMENT_MEDIA:
        return ready
    try:
        document = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return ready
    with document:
        for info in document.infolist():
            image = Path(info.filename).name
            media = info.filename.startswith(DOCUMENT_MEDIA[suffix]) and not info.is_dir()
            if media and not is_video(image):
                saved = save(path.parent, f"{path.name}.{image}", document.read(info))
                ready += prepare(base, str(Path(file).with_name(saved.name)))
    return ready


# The converters of each file type, with the extension of the text they give: HTML, or a PDF's
# plain text.
CONVERTERS: dict[str, tuple[Callable[[Path], str], str]] = {
    ".xml": (jats, ".html"),
    ".nxml": (jats, ".html"),
    ".html": (html, ".html"),
    ".htm": (html, ".html"),
    ".pdf": (pdf, ".txt"),
    ".docx": (word, ".html"),
    ".doc": (doc, ".html"),
}
# Spreadsheets: each sheet's name and rows, one TSV text per sheet.
SPREADSHEETS: dict[str, Callable[[Path], list[tuple[str, str]]]] = {
    ".xlsx": xlsx,
    ".xlsm": xlsx,
    ".xls": xls,
}
# Already text: cleaned in place.
AS_THEY_ARE = {".csv", ".tsv", ".txt"}
# The encodings of text files other than UTF-8: spreadsheet exports (Excel's "Unicode text",
# Windows, old Mac).
ENCODINGS = ["utf_16", "utf_16_le", "utf_16_be", "cp1252", "mac_roman"]


def _read[T](converter: Callable[[Path], T], path: Path) -> T:
    try:
        return converter(path)
    except ParseError:
        raise
    except Exception as e:  # a damaged or encrypted file, from anywhere: refused with why
        raise ParseError(f"cannot be read: {type(e).__name__}: {e}") from e


def _visible(text: str) -> str:
    # Zero-width spaces and soft hyphens: invisible, and tokens all the same.
    return re.sub("[\u200b\u200c\u200d\u00ad\ufeff]", "", text)


def parse(path: Path) -> str:
    """A full text or a document, as Markdown or plain text by its type."""
    found = CONVERTERS.get(path.suffix.lower())
    if found is None:
        raise ParseError(f"no converter for {path.suffix or 'files without extension'}")
    return _visible(_read(found[0], path))


def sheets(path: Path) -> list[tuple[str, str]]:
    """A spreadsheet's sheets, in workbook order: each its name and its rows as TSV."""
    return [(name, _visible(rows)) for name, rows in _read(SPREADSHEETS[path.suffix.lower()], path)]


def _decoded(raw: bytes) -> str:
    """A text file's text: UTF-8 (never with NUL bytes, which UTF-16 has), else in the encoding
    found among `ENCODINGS`."""
    if b"\x00" not in raw:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
    found = charset_normalizer.from_bytes(raw, cp_isolation=ENCODINGS).best()
    if found is None:
        raise ParseError("unknown encoding")
    return str(found)


def _csv(text: str, separator: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=separator))


def _fit(rows: list[list[str]]) -> tuple[int, int]:
    """How many rows share the commonest number of fields, and that number; none for one field."""
    widths = Counter(len(cells) for cells in rows if any(cells))
    width, count = max(widths.items(), key=lambda w: (w[1], w[0]), default=(0, 0))
    return (count, width) if width > 1 else (0, 0)


def _table(text: str, suffix: str) -> str:
    """A CSV or TSV file's text, its rows padded as a sheet's: a TSV split at its tabs, a CSV
    read as CSV, its separator the one, among comma, semicolon and tab, that gives the most rows
    the same number of fields (left as it is when each gives one field). Plain text as it is."""
    if suffix == ".tsv":
        rows = _padded(line.split("\t") for line in text.splitlines())
        return "".join("\t".join(cells) + "\n" for cells in rows)
    if suffix != ".csv":
        return text
    try:
        separator, rows = max(((s, _csv(text, s)) for s in ",;\t"), key=lambda s: _fit(s[1]))
    except csv.Error:  # a field over the csv module's size limit
        return text
    if _fit(rows) == (0, 0):
        return text
    out = io.StringIO()
    csv.writer(out, delimiter=separator, lineterminator="\n").writerows(_padded(rows))
    return out.getvalue()


def _write(path: Path, text: str) -> int:
    data = text.encode()
    path.write_bytes(data)
    return len(data)


def convert(base: Path, file: str) -> dict[str, Any]:
    """A file, at a path relative to `base`, converted to its texts, written beside it; returns
    its entry of the manifest, paths relative to `base`: `file`, then `text` and `bytes`, or for
    a spreadsheet `sheets`, each with `sheet` (its name), `text` and `bytes`. CSV, TSV and plain
    text are their own text, rewritten in UTF-8 without invisible characters, a CSV's or TSV's
    rows padded, when they were not. A file that cannot be converted writes nothing."""
    path = base / file
    suffix = path.suffix.lower()
    if not path.is_file():
        raise ParseError("no such file")
    if suffix in AS_THEY_ARE:
        raw = path.read_bytes()
        cleaned = _table(_visible(_decoded(raw)), suffix).encode()
        if cleaned != raw:
            path.write_bytes(cleaned)
        return {"file": file, "text": file, "bytes": len(cleaned)}
    if suffix in SPREADSHEETS:
        found: list[dict[str, Any]] = []
        for n, (name, rows) in enumerate(sheets(path), 1):
            text = f"{file}.{n}.tsv"
            found.append({"sheet": name, "text": text, "bytes": _write(base / text, rows)})
        return {"file": file, "sheets": found}
    content = parse(path)
    text = file + CONVERTERS[suffix][1]
    return {"file": file, "text": text, "bytes": _write(base / text, content)}


def entry(base: Path, file: str) -> dict[str, Any]:
    """A file's entry of the manifest, at a path relative to `base`: its texts (`convert`); an
    image, or a file that cannot be converted, its `file` alone, why in `not_converted`, which
    the manifest leaves out."""
    if is_image(Path(file)):
        return {"file": file}
    try:
        return convert(base, file)
    except ParseError as e:
        return {"file": file, "not_converted": str(e)}


def entries(base: Path, file: str) -> list[dict[str, Any]]:
    """A downloaded file, at a path relative to `base`, made ready to read (`prepare`), then the
    entry of each file it gives: the file's, or its PNG's, then its images'."""
    if not (base / file).is_file():
        raise ParseError("no such file")
    return [entry(base, ready) for ready in prepare(base, file)]
