"""The routes of `fetch`, its manifest and its report, the downloads simulated (no
network). The pages in `samples/fetch/` are real responses cut to what the routes read."""

import dataclasses
import email.message
import io
import json
import zipfile
from pathlib import Path
from typing import Any, cast

import docx
import openpyxl
import pymupdf
import pytest

from curation.fetch import (
    EFETCH,
    EUROPE_PMC,
    LIMIT,
    OPENALEX,
    PMC_AWS,
    PMC_PAGE,
    UNPAYWALL,
    Response,
    download,
    fetch,
    http_get,
    pmcids,
    report_lines,
)

SAMPLES = Path(__file__).parent / "samples" / "fetch"
PMID = 123
SEARCH = f"{EUROPE_PMC}/search?query=EXT_ID%3A{PMID}%20AND%20SRC%3AMED&format=json&resultType=core"
WORK = f"{OPENALEX}/pmid:{PMID}"
XML = (
    b'<article xmlns:xlink="http://www.w3.org/1999/xlink"><body><p>Text</p>'
    b'<supplementary-material xlink:href="s1.xlsx"><caption><p>Hits</p></caption>'
    b"</supplementary-material>"
    b'<supplementary-material xlink:href="movie_s1.mp4"/>'
    b'<supplementary-material xlink:href="fig_s1.tif"/>'
    b'<supplementary-material><media xlink:href="s2.pdf"><caption><p>Reporting Summary</p>'
    b"</caption></media></supplementary-material></body></article>"
)
TIFF = (SAMPLES / "cmyk.tif").read_bytes()  # CMYK, LZW-compressed, as figures often are
PNG = b"\x89PNG"
DOI = "10.1/x"
PUBLISHER = f"https://doi.org/{DOI}"


def ok(body: bytes, content_type: str = "application/octet-stream", url: str = "") -> Response:
    return Response(url, 200, content_type, body)


def json_ok(data: Any) -> Response:
    return ok(json.dumps(data).encode(), "application/json")


def page(name: str, url: str = "") -> Response:
    return ok((SAMPLES / name).read_bytes(), "text/html", url)


def listing(*keys: str) -> Response:
    return ok(
        (
            "<ListBucketResult>" + "".join(f"<Key>{k}</Key>" for k in keys) + "</ListBucketResult>"
        ).encode()
    )


def found(pmcid: str = "PMC9", **record: Any) -> Response:
    return json_ok({"resultList": {"result": [{"pmcid": pmcid, **record}]}})


@pytest.fixture(autouse=True)
def no_configuration(monkeypatch: pytest.MonkeyPatch):
    """No address configured, unless a test sets one: Unpaywall must then not be asked."""
    monkeypatch.setattr("curation.fetch.load_dotenv", lambda: None)
    monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)


class Server:
    """The responses by URL, and every request made, with the limit it asked."""

    def __init__(self, responses: dict[str, Response]) -> None:
        self.responses = responses
        self.asked: list[str] = []
        self.limits: dict[str, int | None] = {}

    def __call__(self, url: str, limit: int | None = None) -> Response:
        self.asked.append(url)
        self.limits[url] = limit
        r = self.responses.get(url, Response(url, 404, "", b""))
        return dataclasses.replace(r, url=r.url or url)


def too_large(size: int | None = 1_300_000_000) -> Response:
    """A response over the limit asked, not read."""
    return Response("", 200, "application/zip", b"", over_limit=True, size=size)


def run(tmp_path: Path, responses: dict[str, Response]) -> tuple[dict[str, Any], Server]:
    server = Server(responses)
    return fetch(tmp_path, PMID, server), server


def location(url: str, pdf: str | None = None, name: str = "J Virol") -> dict[str, Any]:
    return {
        "is_oa": True,
        "landing_page_url": url,
        "pdf_url": pdf,
        "license": "cc-by",
        "source": {"display_name": name},
    }


def outcomes(report: dict[str, Any]) -> dict[str, str]:
    return {t["url"]: t["outcome"] for t in report["tried"]}


# The article


def test_pmc_open_access_files(tmp_path: Path):
    """The article, its XML alone; videos and the Reporting Summary skipped, never asked; the
    article's figures, the other images of the files, saved; a TIFF as PNG. Each file but an
    image converted, the manifest listing every file: one that cannot be converted by its file
    alone, the report giving why."""
    report, server = run(
        tmp_path,
        {
            SEARCH: found(license="cc by"),
            WORK: json_ok({}),
            f"{PMC_AWS}/?list-type=2&prefix=PMC9.": listing(
                "PMC9.1/PMC9.1.xml",
                "PMC9.2/PMC9.2.xml",
                "PMC9.2/PMC9.2.pdf",
                "PMC9.2/s1.xlsx",
                "PMC9.2/movie_s1.mp4",
                "PMC9.2/fig_s1.tif",
                "PMC9.2/s2.pdf",
                "PMC9.2/g001.jpg",
            ),
            f"{PMC_AWS}/PMC9.2/PMC9.2.xml": ok(XML),
            f"{PMC_AWS}/PMC9.2/s1.xlsx": ok(b"cells"),
            f"{PMC_AWS}/PMC9.2/fig_s1.tif": ok(TIFF),
            f"{PMC_AWS}/PMC9.2/g001.jpg": ok(b"\xff\xd8"),
        },
    )
    assert report["line"] == "Full text: PMC9 (cc by)"
    assert report["missing_supplements"] == []
    assert report["file"] == f"{PMID}.xml"
    assert not (tmp_path / f"{PMID}.pdf").exists()
    assert (tmp_path / f"{PMID}.xml.html").read_text().startswith("<p>Text</p>\n")
    assert report["supplements"] == [
        {
            "name": "s1.xlsx",
            "file": f"{PMID}.supp/s1.xlsx",
            "url": f"{PMC_AWS}/PMC9.2/s1.xlsx",
            "not_converted": "cannot be read: BadZipFile: File is not a zip file",
        },
        {
            "name": "fig_s1.tif",
            "file": f"{PMID}.supp/fig_s1.png",
            "url": f"{PMC_AWS}/PMC9.2/fig_s1.tif",
        },
    ]
    size = (tmp_path / f"{PMID}.xml.html").stat().st_size
    assert json.loads((tmp_path / "manifest.json").read_text()) == {
        "article": {"file": f"{PMID}.xml", "text": f"{PMID}.xml.html", "bytes": size},
        "supplements": [
            {"name": "s1.xlsx", "file": f"{PMID}.supp/s1.xlsx"},
            {"name": "fig_s1.tif", "file": f"{PMID}.supp/fig_s1.png"},
        ],
        "figures": [f"{PMID}.fig/g001.jpg"],
    }
    assert (tmp_path / f"{PMID}.fig" / "g001.jpg").read_bytes() == b"\xff\xd8"
    assert (tmp_path / f"{PMID}.supp" / "fig_s1.png").read_bytes().startswith(PNG)
    assert report_lines(report) == [
        "Full text: PMC9 (cc by)",
        "  s1.xlsx: not converted, cannot be read: BadZipFile: File is not a zip file",
    ]
    assert not any(u.endswith(("movie_s1.mp4", "s2.pdf")) for u in server.asked)
    assert not any(PUBLISHER in u for u in server.asked)  # nothing missing: no other route


def test_supplement_archive_is_unpacked(tmp_path: Path):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("tables/s1.xlsx", "cells")
        z.writestr("__MACOSX/._s1.xlsx", "junk")
        z.writestr("video_s2.mov", "frames")
    xml = (
        b'<article xmlns:xlink="http://www.w3.org/1999/xlink"><body>'
        b'<supplementary-material xlink:href="s.zip"/></body></article>'
    )
    report, _ = run(
        tmp_path,
        {
            SEARCH: found(),
            WORK: json_ok({}),
            f"{PMC_AWS}/?list-type=2&prefix=PMC9.": listing("PMC9.1/PMC9.1.xml", "PMC9.1/s.zip"),
            f"{PMC_AWS}/PMC9.1/PMC9.1.xml": ok(xml),
            f"{PMC_AWS}/PMC9.1/s.zip": ok(archive.getvalue()),
        },
    )
    assert [s["file"] for s in report["supplements"]] == [f"{PMID}.supp/s1.xlsx"]
    assert (tmp_path / f"{PMID}.supp" / "s1.xlsx").read_text() == "cells"
    assert report["missing_supplements"] == []


def test_document_images_are_saved_beside_it(tmp_path: Path):
    """A Word document: kept and converted, each image it holds saved beside it (a TIFF as PNG)
    and listed under its name."""
    document = docx.Document()
    document.add_paragraph("Figure S1. NS1 co-precipitates TRIM25.")
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2, 2), False)
    png = cast(bytes, pixmap.tobytes("png"))
    document.add_picture(io.BytesIO(png))
    document.add_picture(io.BytesIO(TIFF))
    body = io.BytesIO()
    document.save(body)
    xml = (
        b'<article xmlns:xlink="http://www.w3.org/1999/xlink"><body>'
        b'<supplementary-material xlink:href="s1.docx"/></body></article>'
    )
    run(
        tmp_path,
        {
            SEARCH: found(),
            WORK: json_ok({}),
            f"{PMC_AWS}/?list-type=2&prefix=PMC9.": listing("PMC9.1/PMC9.1.xml", "PMC9.1/s1.docx"),
            f"{PMC_AWS}/PMC9.1/PMC9.1.xml": ok(xml),
            f"{PMC_AWS}/PMC9.1/s1.docx": ok(body.getvalue()),
        },
    )
    supp = tmp_path / f"{PMID}.supp"
    text = (supp / "s1.docx.html").stat().st_size
    assert json.loads((tmp_path / "manifest.json").read_text())["supplements"] == [
        {
            "name": "s1.docx",
            "file": f"{PMID}.supp/s1.docx",
            "text": f"{PMID}.supp/s1.docx.html",
            "bytes": text,
        },
        {"name": "s1.docx", "file": f"{PMID}.supp/s1.docx.image1.png"},
        {"name": "s1.docx", "file": f"{PMID}.supp/s1.docx.image2.png"},
    ]
    assert (supp / "s1.docx.image1.png").read_bytes() == png
    html = (supp / "s1.docx.html").read_text()
    assert '<img src="s1.docx.image1.png">' in html and '<img src="s1.docx.image2.png">' in html
    assert (supp / "s1.docx.image2.png").read_bytes().startswith(PNG)


def test_europe_pmc_xml_and_its_supplementary_files_service(tmp_path: Path):
    """Outside the open access files: the XML from Europe PMC, the files from its archive, asked
    once; a file in no route is missing, with every place tried."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("s1.xlsx", "cells")
        z.writestr("fig_s1.png", "pixels")
    report, server = run(
        tmp_path,
        {
            SEARCH: found(),
            WORK: json_ok({}),
            f"{PMC_AWS}/?list-type=2&prefix=PMC9.": listing(),
            f"{EUROPE_PMC}/PMC9/fullTextXML": ok(
                XML.replace(b"s2.pdf", b"s3.pdf").replace(b"Reporting Summary", b"Table S3")
            ),
            f"{EUROPE_PMC}/PMC9/supplementaryFiles": ok(archive.getvalue(), "application/zip"),
        },
    )
    assert report["file"] == f"{PMID}.xml"
    assert [s["file"] for s in report["supplements"]] == [
        f"{PMID}.supp/s1.xlsx",
        f"{PMID}.supp/fig_s1.png",
    ]
    assert (
        report["line"] == "Full text: PMC9 (no license given), supplementary files missing: s3.pdf"
    )
    [missing] = report["missing_supplements"]
    assert missing["name"] == "s3.pdf" and missing["caption"] == "Table S3"
    assert [t["url"] for t in missing["tried"]] == [f"{EUROPE_PMC}/PMC9/supplementaryFiles"]
    assert server.asked.count(f"{EUROPE_PMC}/PMC9/supplementaryFiles") == 1


def test_supplement_over_the_limit_is_not_downloaded(tmp_path: Path):
    """A supplementary file over the limit: not downloaded, no other route tried for it, no
    figure made of it, absent from the manifest and reported, its size when announced; the
    download complete without it. The article is asked with no limit."""
    xml = (
        b'<article xmlns:xlink="http://www.w3.org/1999/xlink"><body><p>Text</p>'
        b'<supplementary-material xlink:href="s1.xlsx"/>'
        b'<supplementary-material xlink:href="images.zip"/>'
        b'<supplementary-material xlink:href="stack.tif"/></body></article>'
    )
    report, server = run(
        tmp_path,
        {
            SEARCH: found(license="cc by"),
            WORK: json_ok({}),
            f"{PMC_AWS}/?list-type=2&prefix=PMC9.": listing(
                "PMC9.1/PMC9.1.xml", "PMC9.1/s1.xlsx", "PMC9.1/images.zip", "PMC9.1/stack.tif"
            ),
            f"{PMC_AWS}/PMC9.1/PMC9.1.xml": ok(xml),
            f"{PMC_AWS}/PMC9.1/s1.xlsx": ok(b"cells"),
            f"{PMC_AWS}/PMC9.1/images.zip": too_large(),
            f"{PMC_AWS}/PMC9.1/stack.tif": too_large(None),
        },
    )
    assert report["line"] == (
        "Full text: PMC9 (cc by), supplementary files over 100 MB: images.zip, stack.tif"
    )
    assert report["missing_supplements"] == []
    assert report["figures"] == []
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert [s["name"] for s in manifest["supplements"]] == ["s1.xlsx"]
    assert report_lines(report)[1:] == [
        "  s1.xlsx: not converted, cannot be read: BadZipFile: File is not a zip file",
        f"  images.zip: over 100 MB (1,240 MB), not downloaded, {PMC_AWS}/PMC9.1/images.zip",
        f"  stack.tif: over 100 MB, not downloaded, {PMC_AWS}/PMC9.1/stack.tif",
    ]
    assert server.asked.count(f"{PMC_AWS}/PMC9.1/stack.tif") == 1  # never again as a figure
    assert f"{EUROPE_PMC}/PMC9/supplementaryFiles" not in server.asked  # not missing
    assert server.limits[f"{PMC_AWS}/PMC9.1/PMC9.1.xml"] is None
    assert server.limits[f"{PMC_AWS}/PMC9.1/s1.xlsx"] == LIMIT


def test_europe_pmc_archive_over_the_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Europe PMC's archive: asked with the limit; a file of it over the limit not read."""
    monkeypatch.setattr("curation.fetch.LIMIT", 6)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("s1.xlsx", "cells")
        z.writestr("fig_s1.png", "pixels!")
    report, server = run(
        tmp_path,
        {
            SEARCH: found(),
            WORK: json_ok({}),
            f"{PMC_AWS}/?list-type=2&prefix=PMC9.": listing(),
            f"{EUROPE_PMC}/PMC9/fullTextXML": ok(XML),
            f"{EUROPE_PMC}/PMC9/supplementaryFiles": ok(archive.getvalue(), "application/zip"),
        },
    )
    url = f"{EUROPE_PMC}/PMC9/supplementaryFiles"
    assert server.limits[url] == 6
    assert [s["file"] for s in report["supplements"]] == [f"{PMID}.supp/s1.xlsx"]
    assert report["over_limit"] == [{"name": "fig_s1.tif", "url": f"{url}#fig_s1.png", "size": 7}]
    assert not (tmp_path / f"{PMID}.supp" / "fig_s1.png").exists()


class Body:
    """An HTTP response read by `http_get`: its headers and its body, read in chunks."""

    def __init__(self, body: bytes, length: str | None) -> None:
        self.body, self.status, self.chunks = body, 200, 0
        self.headers = email.message.Message()
        self.headers["Content-Type"] = "application/zip"
        if length is not None:
            self.headers["Content-Length"] = length

    def __enter__(self) -> "Body":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def geturl(self) -> str:
        return "https://journal.org/s1.zip"

    def read(self, size: int) -> bytes:
        self.chunks += 1
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


@pytest.mark.parametrize(
    ("length", "over_limit", "size", "body", "chunks"),
    [
        ("20", True, 20, b"", 0),  # refused by its announced size, never read
        (None, True, None, b"", 6),  # read until past the limit, never to its end
        (None, False, None, b"0123456789", 6),  # within the limit
    ],
)
def test_http_get_limit(
    monkeypatch: pytest.MonkeyPatch,
    length: str | None,
    over_limit: bool,
    size: int | None,
    body: bytes,
    chunks: int,
):
    sent = Body(b"0123456789" + (b"x" * 10 if over_limit else b""), length)
    monkeypatch.setattr("curation.fetch.CHUNK", 2)

    def urlopen(*_: object, **__: object) -> Body:
        return sent

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    r = http_get("https://journal.org/s1.zip", 10)
    assert (r.status, r.over_limit, r.size, r.body) == (200, over_limit, size, body)
    assert sent.chunks == chunks


def test_pmc_page_when_no_xml_has_a_body(tmp_path: Path):
    """`efetch` gives the front matter alone; the PMC article page holds the article. Its
    supplementary file, behind a challenge on PMC's website, is looked for elsewhere."""
    report, server = run(
        tmp_path,
        {
            SEARCH: found("PMC10537728", doi=DOI),
            WORK: json_ok({}),
            f"{EFETCH}?db=pmc&id=PMC10537728&rettype=xml": ok(
                b"<pmc-articleset><article><front/></article></pmc-articleset>"
            ),
            f"{PMC_PAGE}/PMC10537728/": page("pmc-page.html"),
            PUBLISHER: Response(PUBLISHER, 403, "", b""),
        },
    )
    assert (report["file"], report["source"]) == (f"{PMID}.html", "PMC10537728")
    assert report["supplements_from"] == "the PMC article page"
    assert outcomes(report)[f"{EFETCH}?db=pmc&id=PMC10537728&rettype=xml"] == "HTTP 200, no body"
    [missing] = report["missing_supplements"]
    assert missing["name"] == "jvi.00040-23-s0001.pdf"
    assert missing["tried"][-1]["url"] == f"{EUROPE_PMC}/PMC10537728/supplementaryFiles"
    assert not any("/bin/" in u for u in server.asked)
    assert server.asked.count(f"{PMC_PAGE}/PMC10537728/") == 1


def test_pmc_page_without_body_sections_is_no_article(tmp_path: Path):
    abstract_only = (
        b'<html><body><section class="body main-article-body"><section class="abstract">'
        b'<p>Abstract.</p></section><section id="notes1"><p>Note.</p></section></section>'
        b"</body></html>"
    )
    report, _ = run(
        tmp_path,
        {SEARCH: found(), WORK: json_ok({}), f"{PMC_PAGE}/PMC9/": ok(abstract_only, "text/html")},
    )
    assert report["file"] is None
    assert outcomes(report)[f"{PMC_PAGE}/PMC9/"] == "HTTP 200, no body sections"
    assert report["free"] is True


def test_pmcid_known_only_to_openalex():
    work = {
        "ids": {"pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/111"},
        "locations": [
            location("https://pmc.ncbi.nlm.nih.gov/articles/PMC222/"),
            location("https://doi.org/10.1/x"),
        ],
    }
    assert pmcids({}, work) == ["PMC111", "PMC222"]
    assert pmcids({"pmcid": "PMC111"}, work) == ["PMC111", "PMC222"]


def test_publisher_page_declaring_free_access(tmp_path: Path):
    url = "https://www.nature.com/articles/s41467-020-19808-4"
    media = "https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41467-020-19808-4/MediaObjects/41467_2020_19808_"
    report, server = run(
        tmp_path,
        {
            SEARCH: json_ok({"resultList": {"result": [{"doi": DOI}]}}),
            WORK: json_ok(
                {"doi": PUBLISHER, "locations": [location(PUBLISHER, name="Nat Commun")]}
            ),
            PUBLISHER: page("nature-free.html", url),
            f"{media}MOESM1_ESM.pdf": ok(b"%PDF-1.7", "application/pdf"),
            f"{media}MOESM2_ESM.pdf": ok(b"%PDF-1.7", "application/pdf"),
            f"{media}MOESM4_ESM.xlsx": ok(b"cells"),
        },
    )
    assert report["file"] == f"{PMID}.html"
    assert report["line"] == f"Full text: Nat Commun (cc-by, {url})"
    assert outcomes(report)[PUBLISHER] == "HTTP 200, declares free access"
    assert [s["name"] for s in report["supplements"]] == [
        "41467_2020_19808_MOESM1_ESM.pdf",
        "41467_2020_19808_MOESM4_ESM.xlsx",
    ]
    assert f"{media}MOESM2_ESM.pdf" not in server.asked
    assert f"{media}MOESM3_ESM.pdf" not in server.asked
    assert report["missing_supplements"] == []


def test_page_declaring_a_creative_commons_license(tmp_path: Path):
    """PLOS declares open access only by its license, in its copyright line; its
    supplementary links name no file type, the type comes with the download."""
    url = "https://journals.plos.org/plospathogens/article?id=10.1371/journal.ppat.1009743"
    file = "https://journals.plos.org/plospathogens/article/file?type=supplementary&id=10.1371/journal.ppat.1009743"
    report, _ = run(
        tmp_path,
        {
            SEARCH: json_ok({"resultList": {"result": [{"doi": DOI}]}}),
            WORK: json_ok({}),
            PUBLISHER: page("plos.html", url),
            f"{file}.s001": ok(b"II*", "image/tiff"),
            f"{file}.s005": ok(
                b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        },
    )
    assert outcomes(report)[PUBLISHER] == "HTTP 200, declares free access"
    assert report["file"] == f"{PMID}.html"
    assert [s["file"] for s in report["supplements"]] == [
        f"{PMID}.supp/journal.ppat.1009743.s001.tiff",
        f"{PMID}.supp/journal.ppat.1009743.s005.xlsx",
    ]
    assert [x["name"] for x in report["missing_supplements"]] == [
        f"journal.ppat.1009743.s00{n}" for n in (2, 3, 4, 6, 7)
    ]


def test_paywalled_page_is_no_article_but_lists_the_files(tmp_path: Path):
    """A page that declares a paywall is never the article; its PDF is tried, then the free
    copies' PDFs. Its supplementary links, served freely, are the article's files."""
    pdf = "https://link.springer.com/content/pdf/10.1007/s10495-023-01883-9.pdf"
    docx = "https://media.springernature.com/original/springer-static/esm/art%3A10.1007%2Fs10495-023-01883-9/MediaObjects/10495_2023_1883_MOESM1_ESM.docx"
    repository = location("https://repo.org/record/1", "https://repo.org/record/1.pdf", "Repo")
    report, server = run(
        tmp_path,
        {
            SEARCH: json_ok({"resultList": {"result": [{"doi": DOI}]}}),
            WORK: json_ok({"doi": PUBLISHER, "locations": [repository]}),
            PUBLISHER: page("springer-paywall.html", "https://link.springer.com/article/x"),
            pdf: Response(pdf, 403, "", b""),
            "https://repo.org/record/1.pdf": ok(b"%PDF-1.7", "application/pdf"),
            docx: ok(b"PK\x03\x04", "application/octet-stream"),
        },
    )
    assert outcomes(report)[PUBLISHER] == "HTTP 200, declares a paywall"
    assert (report["file"], report["source"]) == (f"{PMID}.pdf", "Repo")
    assert server.asked.index(pdf) < server.asked.index("https://repo.org/record/1.pdf")
    assert report["supplements_from"] == "the publisher's page"
    assert [s["file"] for s in report["supplements"]] == [
        f"{PMID}.supp/10495_2023_1883_MOESM1_ESM.docx"
    ]
    assert report["missing_supplements"] == []


def test_plos_link_names_the_file_without_its_extension(tmp_path: Path):
    """A file of the XML found on the publisher's page, its name inside the link."""
    xml = (
        b'<article xmlns:xlink="http://www.w3.org/1999/xlink"><body><p>T</p>'
        b'<supplementary-material xlink:href="ppat.1002331.s004.doc"/></body></article>'
    )
    link = "https://journals.plos.org/plospathogens/article/file?type=supplementary&id=10.1371/journal.ppat.1002331.s004"
    article_page = f'<html><body><a href="{link}">Table S4</a></body></html>'.encode()
    report, _ = run(
        tmp_path,
        {
            SEARCH: found(doi=DOI),
            WORK: json_ok({}),
            f"{PMC_AWS}/?list-type=2&prefix=PMC9.": listing("PMC9.1/PMC9.1.xml"),
            f"{PMC_AWS}/PMC9.1/PMC9.1.xml": ok(xml),
            PUBLISHER: ok(article_page, "text/html", "https://journals.plos.org/x"),
            link: ok(b"\xd0\xcf\x11\xe0", "application/msword"),
        },
    )
    assert [s["file"] for s in report["supplements"]] == [f"{PMID}.supp/ppat.1002331.s004.doc"]
    assert report["missing_supplements"] == []


def test_supplement_known_as_an_image_only_once_downloaded(tmp_path: Path):
    """A link that names no type: an image kept, named by its type; a damaged TIFF as it is."""
    links = (
        '<a href="/file?type=supplementary&id=s1">Supplementary Table S1</a>'
        '<a href="/file?type=supplementary&id=s2">Supplementary Figure S2</a>'
    )
    free = '<meta name="citation_fulltext_world_readable" content="">'
    html = f"<html><head>{free}</head><body><p>Text</p>{links}</body></html>".encode()
    report, _ = run(
        tmp_path,
        {
            WORK: json_ok({"doi": PUBLISHER}),
            PUBLISHER: ok(html, "text/html", url="https://journal.org/article/x"),
            "https://journal.org/file?type=supplementary&id=s1": ok(b"cells", "application/msword"),
            "https://journal.org/file?type=supplementary&id=s2": ok(b"II*", "image/tiff"),
        },
    )
    assert report["file"] == f"{PMID}.html"
    assert [s["file"] for s in report["supplements"]] == [
        f"{PMID}.supp/s1.doc",
        f"{PMID}.supp/s2.tiff",
    ]
    assert report["missing_supplements"] == []


# Access, and the outcome without an article


def test_closed(tmp_path: Path):
    report, _ = run(
        tmp_path,
        {
            SEARCH: json_ok({"resultList": {"result": [{"doi": DOI}]}}),
            WORK: json_ok({"locations": [{"is_oa": False, "landing_page_url": PUBLISHER}]}),
            PUBLISHER: page("springer-paywall.html"),
        },
    )
    assert (report["free"], report["file"]) == (False, None)
    assert report["line"] == "Full text: closed — not open access anywhere"
    assert not (tmp_path / "manifest.json").exists()
    assert report_lines(report)[1] == f"  tried {PUBLISHER} (HTTP 200, declares a paywall)"


def test_manifest_lists_the_converted_files(tmp_path: Path):
    """Each text named by its format: a CSV its own text, a spreadsheet one TSV per sheet."""
    xml = (
        b'<article xmlns:xlink="http://www.w3.org/1999/xlink"><body><p>Text</p>'
        b'<supplementary-material xlink:href="s1.csv"/>'
        b'<supplementary-material xlink:href="s2.xlsx"/></body></article>'
    )
    book = openpyxl.Workbook()
    assert book.active is not None
    book.active.title = "Y2H"
    book.active.append(["NS1", "TRIM25"])
    book.create_sheet("Co-IP").append(["NS2"])
    workbook = io.BytesIO()
    book.save(workbook)
    responses = {
        SEARCH: found(),
        WORK: json_ok({}),
        f"{PMC_AWS}/?list-type=2&prefix=PMC9.": listing(
            "PMC9.1/PMC9.1.xml", "PMC9.1/s1.csv", "PMC9.1/s2.xlsx"
        ),
        f"{PMC_AWS}/PMC9.1/PMC9.1.xml": ok(xml),
        f"{PMC_AWS}/PMC9.1/s1.csv": ok(b"a,b\n1,2\n", "text/csv"),
        f"{PMC_AWS}/PMC9.1/s2.xlsx": ok(workbook.getvalue()),
    }
    report, _ = run(tmp_path, responses)
    size = (tmp_path / f"{PMID}.xml.html").stat().st_size
    s1 = {"name": "s1.csv", "file": f"{PMID}.supp/s1.csv", "text": f"{PMID}.supp/s1.csv"}
    s2 = f"{PMID}.supp/s2.xlsx"
    assert json.loads((tmp_path / "manifest.json").read_text()) == {
        "article": {"file": f"{PMID}.xml", "text": f"{PMID}.xml.html", "bytes": size},
        "supplements": [
            s1 | {"bytes": 8},  # a,b\n1,2\n
            {
                "name": "s2.xlsx",
                "file": s2,
                "sheets": [
                    {"sheet": "Y2H", "text": f"{s2}.1.tsv", "bytes": 11},  # NS1\tTRIM25\n
                    {"sheet": "Co-IP", "text": f"{s2}.2.tsv", "bytes": 4},  # NS2\n
                ],
            },
        ],
        "figures": [],
    }
    assert (tmp_path / f"{s2}.1.tsv").read_text() == "NS1\tTRIM25\n"
    assert sorted(p.name for p in (tmp_path / f"{PMID}.supp").iterdir()) == [
        "s1.csv",
        "s2.xlsx",
        "s2.xlsx.1.tsv",
        "s2.xlsx.2.tsv",
    ]
    assert report_lines(report) == ["Full text: PMC9 (no license given)"]


def test_article_that_cannot_be_converted_is_listed_by_its_file(tmp_path: Path):
    """A scanned or damaged PDF: the manifest lists it by its file alone, the report gives why;
    a manifest left by an earlier fetch is replaced."""
    (tmp_path / "manifest.json").write_text("{}")
    pdf = "https://repo.org/record/1.pdf"
    report, _ = run(
        tmp_path,
        {
            SEARCH: json_ok({"resultList": {"result": [{"doi": DOI}]}}),
            WORK: json_ok({"locations": [location("https://repo.org/record/1", pdf, "Repo")]}),
            pdf: ok(b"%PDF-1.7 damaged", "application/pdf"),
        },
    )
    assert report["file"] == f"{PMID}.pdf"
    assert json.loads((tmp_path / "manifest.json").read_text()) == {
        "article": {"file": f"{PMID}.pdf"},
        "supplements": [],
        "figures": [],
    }
    assert report_lines(report)[1].startswith(f"  {PMID}.pdf: not converted, ")


def test_preprint_is_never_fetched(tmp_path: Path):
    preprint = location("https://doi.org/10.1101/y", "https://www.biorxiv.org/y.pdf", "bioRxiv")
    report, server = run(tmp_path, {WORK: json_ok({"locations": [preprint]})})
    assert report["line"] == "Full text: closed — open access only as a preprint"
    assert not any("10.1101" in url or "biorxiv" in url for url in server.asked)


def test_free_but_blocked(tmp_path: Path):
    report, _ = run(
        tmp_path,
        {
            WORK: json_ok(
                {"doi": PUBLISHER, "locations": [location(PUBLISHER, PUBLISHER + ".pdf")]}
            ),
            PUBLISHER: Response(PUBLISHER, 403, "", b""),
            PUBLISHER + ".pdf": Response(PUBLISHER + ".pdf", 403, "", b""),
        },
    )
    assert (report["free"], report["file"]) == (True, None)
    assert report["line"] == (
        f"Full text: not downloaded — a free copy at {PUBLISHER} but download blocked (HTTP 403)"
    )


def test_page_declaring_free_access_makes_the_article_free(tmp_path: Path):
    """Neither a PMCID nor a free copy listed: the publisher's page decides."""
    report, _ = run(
        tmp_path,
        {
            WORK: json_ok({"doi": PUBLISHER}),
            PUBLISHER: page("nature-free.html", "https://www.nature.com/articles/x"),
        },
    )
    assert report["free"] is True and report["file"] == f"{PMID}.html"


def test_copy_from_unpaywall_when_an_address_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("UNPAYWALL_EMAIL", "curator@example.org")
    report, _ = run(
        tmp_path,
        {
            SEARCH: json_ok({"resultList": {"result": [{"doi": DOI}]}}),
            WORK: json_ok({}),
            f"{UNPAYWALL}/{DOI}?email=curator%40example.org": json_ok(
                {
                    "oa_locations": [
                        {
                            "url_for_landing_page": "https://repo.org/record/1",
                            "url_for_pdf": "https://repo.org/record/1.pdf",
                            "license": "cc-by",
                            "repository_institution": "Repo",
                        }
                    ]
                }
            ),
            "https://repo.org/record/1.pdf": ok(b"%PDF-1.7", "application/pdf"),
        },
    )
    assert report["line"] == "Full text: Repo (cc-by, https://repo.org/record/1.pdf)"
    assert report["file"] == f"{PMID}.pdf"


def test_unpaywall_is_not_asked_without_an_address(tmp_path: Path):
    report, server = run(
        tmp_path, {SEARCH: json_ok({"resultList": {"result": [{"doi": DOI}]}}), WORK: json_ok({})}
    )
    assert not any(url.startswith(UNPAYWALL) for url in server.asked)
    assert (report["free"], report["file"]) == (False, None)


def test_error_page_sent_as_success(tmp_path: Path):
    report, _ = run(tmp_path, {SEARCH: ok(b"<html>Service unavailable</html>", "text/html")})
    assert report["line"] == "Full text: closed — not open access anywhere"


def test_preprint_doi_is_never_the_articles(tmp_path: Path):
    """Europe PMC may give the preprint's DOI; OpenAlex the article's."""
    report, server = run(
        tmp_path,
        {
            SEARCH: json_ok({"resultList": {"result": [{"doi": "10.1101/y"}]}}),
            WORK: json_ok({"doi": PUBLISHER}),
        },
    )
    assert report["doi"] == DOI
    assert PUBLISHER in server.asked and "https://doi.org/10.1101/y" not in server.asked


def test_pmc_copy_of_a_preprint_is_no_article(tmp_path: Path):
    """PubMed links some articles to the PMC copy of their preprint, known by its own DOI."""
    preprint = b'<html><head><meta name="citation_doi" content="10.1101/y"></head><body>'
    preprint += (SAMPLES / "pmc-page.html").read_bytes().split(b"<body>", 1)[1]
    efetch = (
        b'<article><front><article-meta><article-id pub-id-type="doi">10.1101/y</article-id>'
        b"</article-meta></front><body><p>Text</p></body></article>"
    )
    report, _ = run(
        tmp_path,
        {
            SEARCH: found(),
            WORK: json_ok({"doi": PUBLISHER}),
            f"{EFETCH}?db=pmc&id=PMC9&rettype=xml": ok(efetch),
            f"{PMC_PAGE}/PMC9/": ok(preprint, "text/html"),
            PUBLISHER: Response(PUBLISHER, 403, "", b""),
        },
    )
    assert report["file"] is None
    assert outcomes(report)[f"{EFETCH}?db=pmc&id=PMC9&rettype=xml"] == "HTTP 200, a preprint"
    assert outcomes(report)[f"{PMC_PAGE}/PMC9/"] == "HTTP 200, a preprint"
    assert report["line"] == (
        f"Full text: not downloaded — a free copy at {PUBLISHER} but download blocked (HTTP 403)"
    )


# download


def test_download_unpacks_and_converts(tmp_path: Path):
    """A repository's archive: each file saved and converted, an image saved as it is (a TIFF as
    PNG), a video left out."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("data/s1.csv", "a,b\n1,2\n")
        z.writestr("fig_s3.tif", TIFF)
        z.writestr("movie_s2.mp4", "frames")
    url = "https://zenodo.org/records/1/files/data.zip"
    lines = download(tmp_path, url, Server({url: ok(archive.getvalue(), "application/zip")}))
    s1 = str(tmp_path / "s1.csv")
    assert [json.loads(line) for line in lines] == [
        {"file": s1, "text": s1, "bytes": 8},
        {"file": str(tmp_path / "fig_s3.png")},
    ]
    assert (tmp_path / "fig_s3.png").read_bytes().startswith(PNG)
    assert not (tmp_path / "movie_s2.mp4").exists()


def test_download_saves_each_image_of_a_tiff_as_png(tmp_path: Path):
    url = "https://journal.org/suppl/fig_s1.tif"
    two = (SAMPLES / "two-images.tif").read_bytes()
    lines = download(tmp_path, url, Server({url: ok(two, "image/tiff")}))
    assert [json.loads(line)["file"] for line in lines] == [
        str(tmp_path / "fig_s1-1.png"),
        str(tmp_path / "fig_s1-2.png"),
    ]
    assert (tmp_path / "fig_s1-2.png").read_bytes().startswith(PNG)


def test_download_saves_the_images_of_a_presentation(tmp_path: Path):
    """A presentation: kept, though no text is made of it, its images saved beside it, its
    videos left out."""
    pptx = io.BytesIO()
    with zipfile.ZipFile(pptx, "w") as z:
        z.writestr("ppt/slides/slide1.xml", "<p:sld/>")
        z.writestr("ppt/media/image1.png", PNG)
        z.writestr("ppt/media/media1.mp4", "frames")
    url = "https://journal.org/suppl/s1.pptx"
    lines = download(tmp_path, url, Server({url: ok(pptx.getvalue())}))
    assert lines == [
        f"{tmp_path / 's1.pptx'}: not converted, no converter for .pptx",
        json.dumps({"file": str(tmp_path / "s1.pptx.image1.png")}),
    ]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s1.pptx", "s1.pptx.image1.png"]


def test_download_names_the_type_from_the_response(tmp_path: Path):
    """A link without an extension (`?download=1`): the type from the response."""
    url = "https://figshare.com/ndownloader/files/42"
    lines = download(tmp_path, url, Server({url: ok(b"x\ty\n", "text/csv")}))
    assert [json.loads(line)["file"] for line in lines] == [str(tmp_path / "42.csv")]


def test_download_has_no_limit(tmp_path: Path):
    """A file downloaded by hand, once judged needed: whatever its size."""
    url = "https://journal.org/suppl/images.zip"
    server = Server({url: ok(b"x\ty\n", "text/csv")})
    download(tmp_path, url, server)
    assert server.limits[url] is None


def test_download_failure(tmp_path: Path):
    url = "https://journal.org/suppl/s1.xlsx"
    assert download(tmp_path, url, Server({})) == ["HTTP 404"]  # its line starts with the URL
    assert not tmp_path.exists() or not any(tmp_path.iterdir())
