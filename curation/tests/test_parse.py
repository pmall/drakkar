"""The converters of `parse.py`, on small samples of each file type (no network)."""

import gzip
import io
import json
import re
import subprocess
import sys
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

import docx
import openpyxl
import py7zr
import pymupdf
import pytest
import xlwt
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from lxml import etree

from curation.parse import ParseError, convert, parse, prepare, sheets

# ppat.1002331.s00*.doc: supplementary tables of PMID 22046132 (CC BY). Ours, made once with
# LibreOffice from a .docx (LibreOffice is no dependency): beyond-bmp.doc, and page-break.doc,
# whose first paragraph mark was then turned into a page break, as Word writes one.
SAMPLES = Path(__file__).parent / "samples"

JATS = """<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front><article-meta>
    <title-group><article-title>NS1 binds <italic>TRIM25</italic></article-title></title-group>
    <abstract><p>We show that NS1 binds TRIM25.</p></abstract>
  </article-meta></front>
  <body>
    <sec><title>Results</title>
      <p>NS1 co-precipitates TRIM25 (<xref ref-type="fig" rid="f1">Fig. 1</xref>).
        <table-wrap><label>Table 1</label><caption><p>Interactions.</p></caption>
          <table>
            <thead><tr><th>Bait</th><th colspan="2">Prey</th></tr></thead>
            <tbody>
              <tr><td rowspan="2">NS1</td><td>TRIM25</td><td>Q14258</td></tr>
              <tr><td>RIG-I</td><td>O95786</td></tr>
            </tbody>
          </table>
        </table-wrap>
      </p>
      <fig id="f1"><label>Figure 1</label>
        <caption><title>Co-IP.</title><p>Anti-FLAG.</p></caption></fig>
      <sec><title>Mapping</title><p>Residues 1-73 of NS1.</p></sec>
    </sec>
  </body>
  <back>
    <ack><p>We thank everyone.</p></ack>
    <ref-list><ref><mixed-citation>A cited paper.</mixed-citation></ref></ref-list>
    <sec><title>Supporting Information</title>
      <supplementary-material xlink:href="s1.xlsx"><label>Table S1</label>
        <caption><p>Y2H screen.</p></caption></supplementary-material>
    </sec>
  </back>
</article>
"""


def test_jats(tmp_path: Path):
    path = tmp_path / "a.xml"
    path.write_text(JATS)
    assert parse(path) == (
        "<h1>NS1 binds TRIM25</h1>\n"
        "<h2>Abstract</h2>\n<p>We show that NS1 binds TRIM25.</p>\n"
        "<h2>Results</h2>\n"
        "<p>NS1 co-precipitates TRIM25 (Fig. 1).</p>\n"
        "<p><b>Table 1.</b> Interactions.</p>\n"
        "<table>\n"
        '<tr><th>Bait</th><th colspan="2">Prey</th></tr>\n'
        '<tr><td rowspan="2">NS1</td><td>TRIM25</td><td>Q14258</td></tr>\n'
        "<tr><td>RIG-I</td><td>O95786</td></tr>\n"
        "</table>\n"
        "<figure><figcaption><b>Figure 1.</b> Co-IP. Anti-FLAG.</figcaption></figure>\n"
        "<h3>Mapping</h3>\n<p>Residues 1-73 of NS1.</p>\n"
        "<h2>Supporting Information</h2>\n"
        "<p><b>Table S1.</b> Y2H screen. (file s1.xlsx)</p>\n"
    )


def test_jats_formula_alternatives_and_bad_spans(tmp_path: Path):
    path = tmp_path / "a.xml"
    path.write_text(
        "<article><body><p>K<sub>d</sub> = <inline-formula><alternatives>"
        "<tex-math>10^{-6}</tex-math><mml:math xmlns:mml='http://www.w3.org/1998/Math/MathML'>"
        "<mml:mn>10</mml:mn></mml:math></alternatives></inline-formula> M</p>"
        "<table-wrap><table><tr><td colspan='x'>a</td><td>b</td></tr></table></table-wrap>"
        "</body></article>"
    )
    assert parse(path) == (
        "<p>K<sub>d</sub> = 10^{-6} M</p>\n<p><b>Table.</b></p>\n"
        "<table>\n<tr><td>a</td><td>b</td></tr>\n</table>\n"
    )


def test_jats_block_alternatives(tmp_path: Path):
    path = tmp_path / "a.xml"
    path.write_text(
        "<article><body><p>The ratio:</p><disp-formula><alternatives><tex-math>a/b</tex-math>"
        "<mml:math xmlns:mml='http://www.w3.org/1998/Math/MathML'><mml:mi>a</mml:mi></mml:math>"
        "</alternatives></disp-formula><alternatives><p>First notation.</p><p>Second.</p>"
        "</alternatives></body></article>"
    )
    assert parse(path) == "<p>The ratio:</p>\n<p>a/b</p>\n<p>First notation.</p>\n"


def test_jats_namespaced(tmp_path: Path):
    path = tmp_path / "a.xml"
    path.write_text(
        '<article xmlns="http://jats.nlm.nih.gov"><front><article-meta><title-group>'
        "<article-title>NS1 binds TRIM25</article-title></title-group></article-meta></front>"
        "<body><sec><title>Results</title><p>Co-IP.</p></sec></body></article>"
    )
    assert parse(path) == "<h1>NS1 binds TRIM25</h1>\n<h2>Results</h2>\n<p>Co-IP.</p>\n"


def test_jats_text_inside_paragraphs(tmp_path: Path):
    """In PMC XML, the text of list items, definitions, table cells and table footnotes sits in
    paragraphs of its own."""
    path = tmp_path / "a.xml"
    path.write_text(
        "<article><body><sec><title>Methods</title>"
        "<list><list-item><p>Y2H screen</p><list><list-item><p>ORFeome</p></list-item></list>"
        "</list-item><list-item><p>LUMIER</p></list-item></list>"
        "<glossary><def-list><def-item><term>IP</term><def><p>immunoprecipitation</p></def>"
        "</def-item></def-list></glossary>"
        "<table-wrap><table><tr><td><p>NS1</p></td><td><p>TRIM25<sup>a</sup></p></td></tr>"
        "</table><table-wrap-foot><fn><p><sup>a</sup> Confirmed by co-IP.</p></fn>"
        "</table-wrap-foot></table-wrap></sec></body></article>"
    )
    assert parse(path) == (
        "<h2>Methods</h2>\n"
        "<ul>\n<li>Y2H screen <ul><li>ORFeome</li></ul></li>\n<li>LUMIER</li>\n</ul>\n"
        "<ul>\n<li>IP immunoprecipitation</li>\n</ul>\n"
        "<p><b>Table.</b></p>\n"
        "<table>\n<tr><td>NS1</td><td>TRIM25<sup>a</sup></td></tr>\n</table>\n"
        "<p><sup>a</sup> Confirmed by co-IP.</p>\n"
    )


def test_jats_nested_table_figure_and_table_given_as_an_image(tmp_path: Path):
    """A table in a cell stays in it; a figure's image is its file in `<stem>.fig/`, found by its
    name without extension, else the name the XML gives; a table given as an image is its
    image."""
    inner = "<table><tr><td>TRIM25</td><td>Q14258</td></tr></table>"
    path = tmp_path / "a.xml"
    path.write_text(
        '<article xmlns:xlink="http://www.w3.org/1999/xlink"><body>'
        f"<table-wrap><label>Table 1</label><table><tr><td>NS1</td><td>{inner}</td></tr></table>"
        "</table-wrap>"
        '<fig><label>Figure 1</label><caption><p>Co-IP.</p></caption><graphic xlink:href="g001"/>'
        "</fig>"
        '<fig><label>Figure 2</label><graphic xlink:href="g002.tif"/></fig>'
        '<table-wrap><label>Table 2</label><graphic xlink:href="t002"/></table-wrap>'
        "</body></article>"
    )
    (tmp_path / "a.fig").mkdir()
    (tmp_path / "a.fig" / "g002.png").write_bytes(b"")  # saved from its TIFF
    assert parse(path) == (
        "<p><b>Table 1.</b></p>\n"
        "<table>\n"
        "<tr><td>NS1</td><td><table><tr><td>TRIM25</td><td>Q14258</td></tr></table></td></tr>\n"
        "</table>\n"
        '<figure><img src="g001"><figcaption><b>Figure 1.</b> Co-IP.</figcaption></figure>\n'
        '<figure><img src="a.fig/g002.png"><figcaption><b>Figure 2.</b></figcaption></figure>\n'
        "<p><b>Table 2.</b></p>\n"
        '<figure><img src="t002"></figure>\n'
    )


def test_html(tmp_path: Path):
    paragraphs = "".join(
        f"<p>Paragraph {i}: NS1 co-precipitates TRIM25 in HEK293 cells, as the blots show.</p>"
        for i in range(30)
    )
    path = tmp_path / "a.html"
    path.write_text(
        "<html><head><title>T</title><script>var x = 1;</script></head><body>"
        "<nav><a href='/'>Home</a></nav>"
        f"<article><h1>NS1 binds TRIM25</h1><h2>Results</h2>{paragraphs}"
        "<table><tr><th>Bait</th><th>Prey</th></tr><tr><td>NS1</td><td>TRIM25<sup>a</sup></td>"
        "</tr></table><figure><img src='https://journal.org/f1.png'></figure>"
        f"{paragraphs}</article></body></html>"
    )
    text = parse(path)
    assert "<p>Paragraph 29: NS1 co-precipitates TRIM25" in text
    assert "<tr><td>NS1</td><td>TRIM25<sup>a</sup></td></tr>\n" in text
    assert '<img src="https://journal.org/f1.png">' in text
    assert "var x" not in text and "Home" not in text


PMC_PAGE = """<html><body><hgroup><h1>NS1 binds <i>TRIM25</i></h1></hgroup>
<section class="body main-article-body">
  <section class="abstract" id="abstract1"><h2 class="pmc_sec_title">Abstract</h2>
    <p>We show that NS1 binds TRIM25.</p></section>
  <section id="kwd-group1" class="kwd-group"><p>influenza</p></section>
  <section id="S1"><h2 class="pmc_sec_title">Results</h2>
    <p>NS1 co-precipitates TRIM25 (<a href="#F1">Fig. 1</a>).</p>
    <figure class="fig xbox font-sm" id="F1"><h3 class="obj_head">Figure 1.</h3>
      <p class="img-box"><img src="f1.jpg"></p><figcaption><p>Co-IP. Anti-FLAG.</p></figcaption>
    </figure>
    <section class="tw xbox font-sm" id="T1"><h4 class="obj_head">Table 1.</h4>
      <div class="caption p"><p>Interactions.</p></div>
      <div class="tbl-box p"><table><thead><tr><th>Bait</th><th colspan="2">Prey</th></tr></thead>
        <tbody><tr><td>NS1</td><td>TRIM25</td><td>Q14258</td></tr></tbody></table></div>
      <div class="tw-foot p"><div class="fn"><p>Co-IP in HEK293T cells.</p></div></div>
    </section>
    <section id="S1.1"><h3 class="pmc_sec_title">Mapping</h3>
      <ul><li>Residues 1-73 of NS1.</li></ul></section>
  </section>
  <section class="ack" id="ack1"><h2 class="pmc_sec_title">Acknowledgments</h2>
    <p>Thanks.</p></section>
  <section id="notes1"><h2 class="pmc_sec_title">Author contributions</h2><p>All.</p></section>
  <section id="S2"><h2 class="pmc_sec_title">Supplementary Material</h2>
    <section class="sm xbox font-sm" id="SM1"><div class="media p"><div class="caption">
      <a href="/articles/instance/1/bin/s1.xlsx">s1.xlsx</a><sup> (12KB, xlsx) </sup>
      <p>Table S1. Y2H screen.</p></div></div></section>
  </section>
  <section class="ref-list" id="ref-list1"><h2 class="pmc_sec_title">References</h2>
    <ol><li><cite>A cited paper.</cite></li></ol></section>
  <section class="associated-data"><p>Data.</p></section>
</section></body></html>"""


def test_pmc_page(tmp_path: Path):
    """A PMC article page is read by its structure, as its XML: the same blocks, the back
    matter left out."""
    path = tmp_path / "a.html"
    path.write_text(PMC_PAGE)
    assert parse(path) == (
        "<h1>NS1 binds TRIM25</h1>\n"
        "<h2>Abstract</h2>\n<p>We show that NS1 binds TRIM25.</p>\n"
        "<h2>Results</h2>\n"
        "<p>NS1 co-precipitates TRIM25 (Fig. 1).</p>\n"
        '<figure><img src="f1.jpg"><figcaption><b>Figure 1.</b> Co-IP. Anti-FLAG.</figcaption>'
        "</figure>\n"
        "<p><b>Table 1.</b> Interactions.</p>\n"
        "<table>\n"
        '<tr><th>Bait</th><th colspan="2">Prey</th></tr>\n'
        "<tr><td>NS1</td><td>TRIM25</td><td>Q14258</td></tr>\n"
        "</table>\n"
        "<p>Co-IP in HEK293T cells.</p>\n"
        "<h3>Mapping</h3>\n<ul>\n<li>Residues 1-73 of NS1.</li>\n</ul>\n"
        "<h2>Supplementary Material</h2>\n"
        "<p><b>Supplementary material.</b> Table S1. Y2H screen. (file s1.xlsx)</p>\n"
    )


def test_html_charset(tmp_path: Path):
    paragraphs = "".join(
        f"<p>Prot&eacute;ine {i} : NS1 lie TRIM25, voir la figure.</p>" for i in range(30)
    )
    head = '<head><meta charset="iso-8859-1"></head>'
    page = f"<html>{head}<body><article>{paragraphs}</article></body></html>"
    path = tmp_path / "a.html"
    path.write_bytes(page.replace("&eacute;", "\u00e9").encode("iso-8859-1"))
    assert "Prot\u00e9ine 29 : NS1 lie TRIM25" in parse(path)


def test_pdf_pages(tmp_path: Path):
    document = pymupdf.open()
    for words in ("NS1 binds TRIM25", "Figure 2: co-IP"):
        page = document.new_page()
        page.insert_text((72, 72), words)
    path = tmp_path / "a.pdf"
    document.save(path)
    assert parse(path) == (
        "--- page 1 ---\n\nNS1 binds TRIM25\n\n--- page 2 ---\n\nFigure 2: co-IP\n\n"
    )


def test_pdf_table_rows_on_one_line(tmp_path: Path):
    """Two columns of text, each written whole, then a table written row by row: the columns
    stay as they are read, each row of the table is one line."""
    document = pymupdf.open()
    page = document.new_page()
    for x, lines in [
        (50, ["NS1 binds TRIM25 in infected cells, as", "co-immunoprecipitation shows."]),
        (320, ["The NS1 mutant R38A/K41A does not bind", "TRIM25 in the same assay."]),
    ]:
        for n, text in enumerate(lines):
            page.insert_text((x, 72 + 14 * n), text, fontsize=10)
    for n, row in enumerate([["P84243", "H3-3A", "2.07"], ["Q969G3", "SMARCE1", "2.06"]]):
        for x, cell in zip((100, 200, 300), row, strict=True):
            page.insert_text((x, 200 + 14 * n), cell, fontsize=10)
    path = tmp_path / "a.pdf"
    document.save(path)
    assert parse(path) == (
        "--- page 1 ---\n\n"
        "NS1 binds TRIM25 in infected cells, as\nco-immunoprecipitation shows.\n"
        "The NS1 mutant R38A/K41A does not bind\nTRIM25 in the same assay.\n"
        "P84243\tH3-3A\t2.07\nQ969G3\tSMARCE1\t2.06\n\n"
    )


def test_scanned_pdf(tmp_path: Path):
    document = pymupdf.open()
    document.new_page()
    path = tmp_path / "a.pdf"
    document.save(path)
    with pytest.raises(ParseError, match="no text layer"):
        parse(path)


def workbook(path: Path) -> None:
    """A workbook of two sheets, the second empty."""
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Y2H; Caco-2"
    sheet.append(["Bait", "Prey", "Score", None])
    sheet.append(["NS1", "TRIM\u200b25", 2.0, None])
    sheet.append([None, None, None, None])
    sheet.append(["NS2", "line\nbreak", 0.5])
    book.create_sheet("Empty")
    book.save(path)


def test_xlsx(tmp_path: Path):
    path = tmp_path / "a.xlsx"
    workbook(path)
    assert sheets(path) == [
        ("Y2H; Caco-2", "Bait\tPrey\tScore\nNS1\tTRIM25\t2\nNS2\tline break\t0.5\n"),
        ("Empty", ""),
    ]


def test_sheet_rows_as_wide_as_the_widest(tmp_path: Path):
    """A title above the header, a row whose last cells are empty: every row has every field."""
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    for row in [["Table S1. Y2H screen"], ["Bait", "Prey", "Score"], ["NS1", "TRIM25", None]]:
        sheet.append(row)
    path = tmp_path / "a.xlsx"
    book.save(path)
    assert sheets(path) == [
        ("Sheet", "Table S1. Y2H screen\t\t\nBait\tPrey\tScore\nNS1\tTRIM25\t\n")
    ]


def test_xls(tmp_path: Path):
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Y2H")
    for column, value in enumerate(["Bait", "Prey", "Score"]):
        sheet.write(0, column, value)
    sheet.write(1, 0, "NS1")
    sheet.write(
        1, 1, datetime(2002, 9, 2), xlwt.easyxf(num_format_str="D-MMM")
    )  # SEPT2, as Excel saw it
    sheet.write(1, 2, 2.0)
    path = tmp_path / "a.xls"
    workbook.save(str(path))
    assert sheets(path) == [("Y2H", "Bait\tPrey\tScore\nNS1\t2002-09-02T00:00:00\t2\n")]


def test_docx(tmp_path: Path):
    document = docx.Document()
    document.add_heading("Table S1", level=1)
    document.add_paragraph("Validated interactions.")
    table = document.add_table(rows=2, cols=2)
    for row, cells in zip(table.rows, [("Bait", "Prey"), ("NS1", "TRIM25")], strict=True):
        for cell, value in zip(row.cells, cells, strict=True):
            cell.text = value
    path = tmp_path / "a.docx"
    document.save(str(path))
    assert parse(path) == (
        "<h1>Table S1</h1>\n<p>Validated interactions.</p>\n"
        "<table>\n<tr><td>Bait</td><td>Prey</td></tr>\n<tr><td>NS1</td><td>TRIM25</td></tr>\n"
        "</table>\n"
    )


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def word_xml(xml: str) -> Any:
    """A Word element written in XML, its namespaces (`w`, `mc`, `v`) declared on it."""
    namespaces = f'xmlns:w="{W}" xmlns:mc="{MC}" xmlns:v="urn:schemas-microsoft-com:vml"'
    return etree.fromstring(re.sub(r"^<([\w:]+)", rf"<\1 {namespaces}", xml, count=1))


def test_docx_cleaned_up(tmp_path: Path):
    """Each part of a Word document that holds content: a heading, a superscript, a list nested
    by level, merged cells, a table in a cell, an image where it stands, a tracked insertion (its
    deletion left out), a field's result in both of Word's forms (never its code), a text box
    read once (Word writes it twice), a content control, text in the Symbol font, a footnote."""
    document = docx.Document()
    document.add_heading("Table S1", level=1)
    paragraph = document.add_paragraph("Kd = 10")
    paragraph.add_run("-6").font.superscript = True
    table = document.add_table(rows=3, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "Bait and prey"
    table.cell(0, 2).text = "Score"
    table.cell(1, 0).merge(table.cell(2, 0)).text = "NS1"
    table.cell(1, 1).text = "TRIM25"
    table.cell(1, 2).text = "2"
    table.cell(2, 1).add_table(rows=1, cols=2).cell(0, 0).text = "RIG-I"
    document.add_paragraph("Figure 1. Co-IP.")
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2, 2), False)
    document.add_picture(io.BytesIO(cast(bytes, pixmap.tobytes("png"))))
    numbered = '<w:pPr><w:numPr><w:ilvl w:val="{}"/><w:numId w:val="1"/></w:numPr></w:pPr>'
    paragraphs = [
        *(
            f"<w:p>{numbered.format(level)}<w:r><w:t>{text}</w:t></w:r></w:p>"
            for level, text in [(0, "Y2H screen"), (1, "ORFeome"), (0, "LUMIER")]
        ),
        '<w:p><w:ins w:id="1" w:author="a"><w:r><w:t>Kept.</w:t></w:r></w:ins>'
        '<w:del w:id="2" w:author="a"><w:r><w:delText>Deleted.</w:delText></w:r></w:del></w:p>',
        '<w:p><w:r><w:t xml:space="preserve">Table S</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>SEQ Table</w:instrText>'
        '</w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>2</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        '<w:r><w:t xml:space="preserve">, Figure S</w:t></w:r><w:fldSimple w:instr="SEQ Figure">'
        "<w:r><w:t>3</w:t></w:r></w:fldSimple></w:p>",
        "<w:p><w:r><mc:AlternateContent><mc:Choice Requires='wps'><w:drawing><w:txbxContent><w:p>"
        "<w:r><w:t>In a text box.</w:t></w:r></w:p></w:txbxContent></w:drawing></mc:Choice>"
        "<mc:Fallback><w:pict><v:textbox><w:txbxContent><w:p><w:r><w:t>In a text box.</w:t>"
        "</w:r></w:p></w:txbxContent></v:textbox></w:pict></mc:Fallback></mc:AlternateContent>"
        "</w:r></w:p>",
        "<w:sdt><w:sdtContent><w:p><w:r><w:t>In a content control.</w:t></w:r></w:p></w:sdtContent>"
        "</w:sdt>",
        '<w:p><w:r><w:t>IFN-</w:t></w:r><w:r><w:rPr><w:rFonts w:ascii="Symbol" w:hAnsi="Symbol"/>'
        '</w:rPr><w:t>g</w:t></w:r><w:r><w:t xml:space="preserve"> and </w:t></w:r><w:r><w:sym '
        'w:font="Symbol" w:char="F061"/></w:r><w:r><w:t>-actinin</w:t></w:r><w:r>'
        '<w:footnoteReference w:id="1"/></w:r></w:p>',
    ]
    body: Any = cast(Any, document.element).body
    for xml in paragraphs:
        body.insert(len(body) - 1, word_xml(xml))
    notes = (
        f'<w:footnotes xmlns:w="{W}"><w:footnote w:id="1"><w:p><w:r><w:footnoteRef/></w:r>'
        "<w:r><w:t>Confirmed by co-IP.</w:t></w:r></w:p></w:footnote></w:footnotes>"
    ).encode()
    footnotes = "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
    part = Part(PackURI("/word/footnotes.xml"), footnotes, notes, document.part.package)
    document.part.relate_to(part, RT.FOOTNOTES)
    document.save(str(tmp_path / "a.docx"))
    assert prepare(tmp_path, "a.docx") == ["a.docx", "a.docx.image1.png"]
    assert parse(tmp_path / "a.docx") == (
        "<h1>Table S1</h1>\n"
        "<p>Kd = 10<sup>-6</sup></p>\n"
        "<table>\n"
        '<tr><td colspan="2">Bait and prey</td><td>Score</td></tr>\n'
        '<tr><td rowspan="2">NS1</td><td>TRIM25</td><td>2</td></tr>\n'
        "<tr><td><table><tr><td>RIG-I</td><td></td></tr></table></td><td></td></tr>\n"
        "</table>\n"
        "<p>Figure 1. Co-IP.</p>\n"
        '<p><img src="a.docx.image1.png"></p>\n'
        "<ul>\n<li>Y2H screen<ul><li>ORFeome</li></ul></li>\n<li>LUMIER</li>\n</ul>\n"
        "<p>Kept.</p>\n"
        "<p>Table S2, Figure S3</p>\n"
        "<p>In a text box.</p>\n"
        "<p>In a content control.</p>\n"
        "<p>IFN-\u03b3 and \u03b1-actinin<sup>1</sup></p>\n"
        "<p><sup>1</sup> Confirmed by co-IP.</p>\n"
    )


def table_rows(text: str) -> list[list[str]]:
    """The rows of the HTML tables of a converted text, a cell spanning columns repeated over
    them."""
    rows = [line for line in text.splitlines() if line.startswith("<tr>")]
    cell = re.compile(r'<td(?: colspan="(\d+)")?>(.*?)</td>')
    return [[c for n, c in cell.findall(row) for _ in range(int(n or 1))] for row in rows]


def test_doc():
    """Table S3, Word 97-2003."""
    rows = table_rows(parse(SAMPLES / "ppat.1002331.s006.doc"))
    assert len(rows) == 3
    assert rows[0][1].startswith("Fraction of SARS-CoV interaction partners")
    assert rows[2] == [
        "SARS interaction partners (complete)",
        "36/514=7%",
        "884/31,941=2.8%",
        "4.4e-07",
    ]


def test_doc_rows_end_where_word_ends_them():
    """Table S1: a header cell broken over two lines, empty cells, and row properties too large
    for their page (in the Data stream)."""
    rows = table_rows(parse(SAMPLES / "ppat.1002331.s004.doc"))
    assert {len(r) for r in rows} == {9}
    assert rows[0][4] == "Number of times this prey has been isolated."
    assert rows[1] == [
        "A",
        "ORF13",
        "RYBP",
        "23429",
        "5",
        "RING1 and YY1 binding protein",
        "ORFeome",
        "4,9",
        "78,4",
    ]
    assert len(rows) == 88


def test_doc_cell_spanning_columns():
    """Table S2: empty last cells, and a row whose second cell spans two columns."""
    rows = table_rows(parse(SAMPLES / "ppat.1002331.s005.doc"))
    assert {len(r) for r in rows} == {7}
    assert rows[3] == ["Nsp13", "nsp13", "DDX5", "1655", "Ddx5", "19224332", ""]
    spanning = next(r for r in rows if "(prev desig U122 and X4)" in r)
    assert spanning == ["", "(prev desig U122 and X4)", "(prev desig U122 and X4)", "", "", "", ""]


def test_doc_characters_beyond_the_basic_plane():
    """A character beyond U+FFFF takes 4 bytes in the text: the cell marks after it are still
    found."""
    assert parse(SAMPLES / "beyond-bmp.doc") == (
        "<p>Binding of \U0001d6fc-actinin (\U0001d6fc beyond U+FFFF) to NS1.</p>\n"
        "<table>\n<tr><td>Bait</td><td>Prey</td></tr>\n"
        "<tr><td>\U0001d6fc-NS1</td><td>TRIM25</td></tr>\n</table>\n"
        "<p>After the table.</p>\n"
    )


def test_doc_page_break_ends_a_paragraph():
    assert parse(SAMPLES / "page-break.doc") == (
        "<p>Before the break.</p>\n<p>After the break.</p>\n<p>Next paragraph.</p>\n"
    )


def test_not_a_doc(tmp_path: Path):
    path = tmp_path / "a.doc"
    path.write_text("plain text")
    with pytest.raises(ParseError, match="not a Word 97-2003 document"):
        parse(path)


def test_unknown_type(tmp_path: Path):
    path = tmp_path / "a.tif"
    path.write_bytes(b"II*\x00")
    with pytest.raises(ParseError, match="no converter for .tif"):
        parse(path)


def test_damaged_file_is_refused(tmp_path: Path):
    path = tmp_path / "a.xlsx"
    path.write_bytes(b"PK\x03\x04 not really a workbook")
    with pytest.raises(ParseError, match="cannot be read"):
        sheets(path)


# The texts, named by their format


def test_spreadsheet_gives_one_tsv_file_per_sheet(tmp_path: Path):
    """Numbered in workbook order, an empty sheet an empty file: every sheet listed."""
    (tmp_path / "1.supp").mkdir()
    workbook(tmp_path / "1.supp" / "s1.xlsx")
    rows = "Bait\tPrey\tScore\nNS1\tTRIM25\t2\nNS2\tline break\t0.5\n"
    assert convert(tmp_path, "1.supp/s1.xlsx") == {
        "file": "1.supp/s1.xlsx",
        "sheets": [
            {"sheet": "Y2H; Caco-2", "text": "1.supp/s1.xlsx.1.tsv", "bytes": len(rows)},
            {"sheet": "Empty", "text": "1.supp/s1.xlsx.2.tsv", "bytes": 0},
        ],
    }
    assert (tmp_path / "1.supp" / "s1.xlsx.1.tsv").read_text() == rows
    assert (tmp_path / "1.supp" / "s1.xlsx.2.tsv").read_text() == ""


def test_pdf_gives_plain_text_and_xml_html(tmp_path: Path):
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "NS1 binds TRIM25")
    document.save(tmp_path / "1.pdf")
    (tmp_path / "1.xml").write_text(JATS)
    pdf = convert(tmp_path, "1.pdf")
    assert pdf == {"file": "1.pdf", "text": "1.pdf.txt", "bytes": pdf["bytes"]}
    assert (tmp_path / "1.pdf.txt").read_text() == "--- page 1 ---\n\nNS1 binds TRIM25\n\n"
    xml = convert(tmp_path, "1.xml")
    assert xml == {"file": "1.xml", "text": "1.xml.html", "bytes": xml["bytes"]}
    assert xml["bytes"] == (tmp_path / "1.xml.html").stat().st_size


def test_text_files_are_their_own_text(tmp_path: Path):
    (tmp_path / "s1.csv").write_bytes(b"bait,prey\nNS1,TRIM25\n")
    assert convert(tmp_path, "s1.csv") == {"file": "s1.csv", "text": "s1.csv", "bytes": 21}
    assert [p.name for p in tmp_path.iterdir()] == ["s1.csv"]


@pytest.mark.parametrize(
    "raw",
    [
        "bait;prey\nNS1;prot\u00e9ine\n".encode("cp1252"),  # Excel's Windows export
        "bait;prey\nNS1;prot\u00e9ine\n".encode("utf-16"),  # Excel's "Unicode text"
        "bait;prey\nNS1;prot\u00e9ine\n".encode("mac_roman"),
        "\ufeffbait;prey\nNS1;prot\u200b\u00e9i\u00adne\n".encode(),
    ],
)
def test_text_files_are_cleaned_in_place(tmp_path: Path, raw: bytes):
    """In UTF-8, invisible characters removed."""
    (tmp_path / "s1.csv").write_bytes(raw)
    entry = convert(tmp_path, "s1.csv")
    assert (tmp_path / "s1.csv").read_text() == "bait;prey\nNS1;prot\u00e9ine\n"
    assert entry == {"file": "s1.csv", "text": "s1.csv", "bytes": 24}


@pytest.mark.parametrize(
    ("name", "raw", "padded"),
    [
        (
            "s1.tsv",
            "Table S1\n\nbait\tprey\tscore\r\nNS1\tTRIM25\n",
            "Table S1\t\t\nbait\tprey\tscore\nNS1\tTRIM25\t\n",
        ),
        (
            "s1.csv",
            'bait,prey,note\nNS1,"TRIM25, RIG-I"\n',
            'bait,prey,note\nNS1,"TRIM25, RIG-I",\n',
        ),
        ("s1.csv", "bait;prey;score\nNS1;TRIM25\n", "bait;prey;score\nNS1;TRIM25;\n"),
    ],
)
def test_tables_are_padded_in_place(tmp_path: Path, name: str, raw: str, padded: str):
    """Every row as many fields as the widest, as a sheet's; a quoted separator kept."""
    (tmp_path / name).write_text(raw, newline="")
    convert(tmp_path, name)
    assert (tmp_path / name).read_bytes().decode() == padded


def test_text_of_unknown_encoding_is_refused(tmp_path: Path):
    (tmp_path / "s1.txt").write_bytes(bytes(range(256)) * 4)
    with pytest.raises(ParseError, match="unknown encoding"):
        convert(tmp_path, "s1.txt")


def test_refused_file_writes_nothing(tmp_path: Path):
    (tmp_path / "s1.xlsx").write_bytes(b"PK\x03\x04 not really a workbook")
    with pytest.raises(ParseError, match="cannot be read"):
        convert(tmp_path, "s1.xlsx")
    with pytest.raises(ParseError, match="no such file"):
        convert(tmp_path, "s2.pdf")
    assert [p.name for p in tmp_path.iterdir()] == ["s1.xlsx"]


def test_parse_script_prints_the_manifest_entries(tmp_path: Path):
    """Every file listed: an image (a damaged TIFF as it is) and a file that cannot be converted
    by their file alone, why on stderr."""
    (tmp_path / "1.xml").write_text(JATS)
    (tmp_path / "s1.tif").write_bytes(b"II*\x00")
    workbook(tmp_path / "s2.xlsx")
    (tmp_path / "s3.rtf").write_text("{\\rtf1 NS1 binds TRIM25}")
    files = ["1.xml", "s1.tif", "s2.xlsx", "s3.rtf", "s4.pdf"]
    script = Path(__file__).parents[1] / "scripts" / "parse.py"
    done = subprocess.run(
        [sys.executable, script, str(tmp_path), *files], capture_output=True, text=True
    )
    assert done.returncode == 1
    assert done.stderr == (
        "s3.rtf: not converted, no converter for .rtf\ns4.pdf: not converted, no such file\n"
    )
    entries = [json.loads(line) for line in done.stdout.splitlines()]
    assert [e["file"] for e in entries] == ["1.xml", "s1.tif", "s2.xlsx", "s3.rtf"]
    assert entries[0]["text"] == "1.xml.html"
    assert entries[1] == {"file": "s1.tif"}
    assert [s["sheet"] for s in entries[2]["sheets"]] == ["Y2H; Caco-2", "Empty"]
    assert entries[3] == {"file": "s3.rtf"}
    assert (tmp_path / "1.xml.html").read_text().startswith("<h1>NS1 binds TRIM25</h1>\n")


def _tar(mode: Literal["w", "w:gz", "w:bz2", "w:xz"]) -> bytes:
    body = io.BytesIO()
    with tarfile.open(fileobj=body, mode=mode) as archive:
        for path, content in [("data/s1.csv", b"a,b\n"), ("movie_s2.mp4", b"frames")]:
            info = tarfile.TarInfo(path)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return body.getvalue()


def _7z() -> bytes:
    body = io.BytesIO()
    with py7zr.SevenZipFile(body, "w") as archive:
        archive.writestr(b"a,b\n", "data/s1.csv")
        archive.writestr(b"frames", "movie_s2.mp4")
    return body.getvalue()


def _zip(files: dict[str, bytes]) -> bytes:
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return body.getvalue()


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("s.zip", _zip({"data/s1.csv": b"a,b\n", "movie_s2.mp4": b"frames"})),
        ("s.tar", _tar("w")),
        ("s.tar.gz", _tar("w:gz")),
        ("s.tgz", _tar("w:gz")),
        ("s.tar.bz2", _tar("w:bz2")),
        ("s.tar.xz", _tar("w:xz")),
        ("s.7z", _7z()),
    ],
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_every_archive_is_replaced_by_its_files(tmp_path: Path, name: str, body: bytes):
    """Every kind of archive alike: replaced by its files, saved beside it, a video left out."""
    (tmp_path / "supp").mkdir()
    (tmp_path / "supp" / name).write_bytes(body)
    assert prepare(tmp_path, f"supp/{name}") == ["supp/s1.csv"]
    assert sorted(p.name for p in (tmp_path / "supp").iterdir()) == ["s1.csv"]
    assert (tmp_path / "supp" / "s1.csv").read_bytes() == b"a,b\n"


def test_rar_archive_is_replaced_by_its_files(tmp_path: Path):
    (tmp_path / "s.rar").write_bytes((SAMPLES / "archive.rar").read_bytes())  # unrar2-cffi's
    assert prepare(tmp_path, "s.rar") == ["test_file.txt", "test_file2.txt", "testfile"]
    assert (tmp_path / "test_file2.txt").read_text() == "This is another test!\n"
    assert not (tmp_path / "s.rar").exists()


def test_gzip_file_is_replaced_by_its_file(tmp_path: Path):
    """A `.gz` that is no tar: its one file, named without `.gz`."""
    (tmp_path / "s1.csv.gz").write_bytes(gzip.compress(b"a,b\n"))
    assert prepare(tmp_path, "s1.csv.gz") == ["s1.csv"]
    assert (tmp_path / "s1.csv").read_bytes() == b"a,b\n"


def test_archive_in_an_archive_is_unpacked_and_its_files_made_ready(tmp_path: Path):
    """Hidden files and `__MACOSX` left out; an archive inside unpacked; a TIFF made a PNG."""
    tiff = (SAMPLES / "fetch" / "cmyk.tif").read_bytes()
    inner = _zip({"fig_s1.tif": tiff, ".DS_Store": b"junk"})
    (tmp_path / "s.zip").write_bytes(
        _zip({"inner.zip": inner, "__MACOSX/._inner.zip": b"junk", "s2.txt": b"text"})
    )
    assert prepare(tmp_path, "s.zip") == ["fig_s1.png", "s2.txt"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fig_s1.png", "s2.txt"]


@pytest.mark.parametrize("name", ["s.zip", "s.rar", "s.7z", "s.tar", "s.tgz", "s.gz"])
def test_archive_that_cannot_be_read_is_kept(tmp_path: Path, name: str):
    (tmp_path / name).write_bytes(b"not an archive")
    assert prepare(tmp_path, name) == [name]
    assert (tmp_path / name).read_bytes() == b"not an archive"


def test_archive_holding_no_file_is_kept(tmp_path: Path):
    (tmp_path / "s.zip").write_bytes(_zip({}))
    assert prepare(tmp_path, "s.zip") == ["s.zip"]
