"""Download the full text of a publication, as published, with its supplementary files, and
convert them to text for the curation; or one file, at a URL: `fetch` and `download`, run by
`curation/scripts/fetch.py` and `curation/scripts/download.py`, which describe them.

`fetch` downloads the full text in three steps. Each step is a list of routes, each route
answering yes or no by one test.

1. Access: the article is free when it has a PMCID, when OpenAlex or Unpaywall list a free copy,
   or when the publisher's page (at the DOI) declares free access (`"isAccessibleForFree": true`,
   `<meta name="access" content="Yes">`, `citation_fulltext_world_readable`, or a link to the
   article's Creative Commons license, PLOS's only declaration); a declared paywall wins. Closed
   otherwise. A preprint is never a copy of the article: its copies, its DOI and a PMC copy of it
   (known by its own DOI) are never fetched.
2. The article, one file, from the first route that gives it: the PMC open access files, Europe
   PMC `fullTextXML`, NCBI `efetch` (each when its XML has a body); the PMC article page, which
   serves the PMC copies outside the open access files (when it has the body sections; one page
   per publication, as NCBI forbids bulk downloads); the publisher's HTML page (when it declares
   free access; a page that declares a paywall is never the article); then, last, the publisher's
   PDF (`citation_pdf_url`) and the other free copies' PDFs (when the file is a PDF).
3. The supplementary files, as the article lists them: its XML, the supplementary sections of the
   PMC page, or else the supplementary links of the publisher's page. Each is looked for on every
   route that serves one, whatever route gave the article: the PMC open access files, the link
   the article gives (never the PMC website's, which is behind a challenge), the publisher's page,
   then Europe PMC's supplementary files service. Archives are unpacked. A video, the Reporting
   Summary and the peer review file (both by their caption) are skipped. A file over 100 MB is
   never downloaded, by the size the server announces or once its download passes 100 MB, nor
   read from Europe PMC's archive: it is left to a download by hand (`download`), when
   judged needed.

It writes the article, `<pmid>.xml`, `<pmid>.html` or `<pmid>.pdf`, the supplementary files in
`<pmid>.supp/`, and the article's figures, the other images of the PMC open access files, in
`<pmid>.fig/`. Then the parser (`parse.py`) makes each file ready to read (`prepare`) and
converts it as `parse.py` does: a TIFF or a BMP image replaced by its PNG, one file per
image it holds (`<name>-<n>.png` when several), which the Read tool reads; a Word document, a
workbook or a presentation (`.docx`, `.xlsx`, `.xlsm`, `.pptx`) kept, with each image it holds
(its `media` folder, its videos left out) saved beside it, `<file>.<image>`; each file but an
image converted, its texts beside it; an image read as it is.

Last, when the article was downloaded, the manifest `manifest.json`, every file downloaded:
`article`, with `file`, the original, `text`, its text, and `bytes`, the size of the text;
`supplements`, each with the `name` the article gives it (the images of an archive or a document
under its name), `file`, then `text` and `bytes`, or for a spreadsheet `sheets`, each with `sheet`,
its name, `text` and `bytes`; `figures`, the paths of the figures. An image, or a file that could
not be converted, has its `file` alone. Paths are relative to `<dir>`. A publication directory set
up from files the user provides holds the same: each file converted with
`curation/scripts/parse.py`, which prints its entries, and the manifest in this format, `bytes`
optional.

Configuration, in the project's `.env`: `UNPAYWALL_EMAIL`, the address Unpaywall asks for to
answer a request. Without it Unpaywall is not asked at all.
"""

import io
import json
import mimetypes
import os
import re
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import quote, unquote, urljoin, urlparse

from dotenv import load_dotenv
from lxml import etree
from lxml.etree import _Element  # pyright: ignore[reportPrivateUsage]

from curation.parse import (
    IMAGES,
    VIDEOS,
    XLINK,
    class_names,
    entries,
    entry,
    is_image,
    is_video,
    one_line,
    prepare,
    save,
    tag_name,
)

EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
OPENALEX = "https://api.openalex.org/works"
UNPAYWALL = "https://api.unpaywall.org/v2"
PMC_AWS = "https://pmc-oa-opendata.s3.amazonaws.com"
PMC_PAGE = "https://pmc.ncbi.nlm.nih.gov/articles"
# Publishers refuse requests without a browser user agent.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
TIMEOUT = 30
SUPPLEMENT_SUFFIXES = {
    ".xlsx",
    ".xls",
    ".xlsm",
    ".csv",
    ".tsv",
    ".txt",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".pdf",
    ".zip",
}
# Preprints are not peer-reviewed publications: their copies are never fetched.
PREPRINT_HOSTS = (
    "biorxiv.org",
    "medrxiv.org",
    "researchsquare.com",
    "preprints.org",
    "ssrn.com",
    "arxiv.org",
)
PREPRINT_DOIS = ("10.1101/", "10.64898/", "10.21203/", "10.20944/", "10.2139/", "10.48550/")
# PMC copies are fetched by their PMCID (routes of the article), never as an open access location.
PMC_HOSTS = ("ncbi.nlm.nih.gov", "europepmc.org")
# Services, not copies: a failure there says nothing of where the article is blocked.
SERVICES = (PMC_AWS, EUROPE_PMC, EFETCH)
CAPTION_LENGTH = 200
MANIFEST = "manifest.json"
# A supplementary file over it is never downloaded automatically, only by hand once judged needed.
LIMIT = 100 * 2**20
CHUNK = 2**20


@dataclass
class Response:
    url: str  # after redirects
    status: int
    content_type: str
    body: bytes
    over_limit: bool = False  # a body over the limit asked, not read
    size: int | None = None  # its size, when the server announced it


class Get(Protocol):
    def __call__(self, url: str, limit: int | None = None) -> Response: ...


def http_get(url: str, limit: int | None = None) -> Response:
    """The response at a URL. With a limit, a body over it is not read: by the size the server
    announces, or once more than the limit has been read; read in chunks."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as r:
            response = Response(r.geturl(), r.status, r.headers.get_content_type(), b"")
            length = r.headers.get("Content-Length", "")
            size = int(length) if length.isdigit() else None
            if limit is not None and size is not None and size > limit:
                response.over_limit, response.size = True, size
                return response
            chunks: list[bytes] = []
            read = 0
            while chunk := r.read(CHUNK):
                read += len(chunk)
                if limit is not None and read > limit:
                    response.over_limit = True
                    return response
                chunks.append(chunk)
            response.body = b"".join(chunks)
            return response
    except urllib.error.HTTPError as e:
        return Response(url, e.code, "", b"")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        return Response(url, 0, "", str(reason).encode())


def _outcome(r: Response) -> str:
    if r.status == 0:
        return f"failed: {r.body.decode(errors='replace')}"
    if r.over_limit:
        return f"HTTP {r.status}, {_over_limit(r.size)}"
    return f"HTTP {r.status}"


def _over_limit(size: int | None) -> str:
    """A file over the limit, with its size when known."""
    return f"over {LIMIT // 2**20} MB" + (f" ({size / 2**20:,.0f} MB)" if size else "")


def _json(get: Get, url: str) -> dict[str, Any] | None:
    r = get(url)
    if r.status != 200:
        return None
    try:
        return cast(dict[str, Any], json.loads(r.body))
    except ValueError:  # an error page sent as a success
        return None


def _is_pdf(r: Response) -> bool:
    return r.body.startswith(b"%PDF")


def _is_html(r: Response) -> bool:
    return r.content_type in ("text/html", "application/xhtml+xml")


def _xml(body: bytes) -> _Element | None:
    try:
        return etree.fromstring(body, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        return None


def _html(body: bytes) -> _Element | None:
    try:
        return etree.fromstring(body, etree.HTMLParser())
    except (etree.XMLSyntaxError, ValueError):
        return None


def _zip(body: bytes) -> zipfile.ZipFile | None:
    try:
        return zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile:
        return None


def _text(el: _Element) -> str:
    return one_line(" ".join(str(t) for t in el.itertext()))


def _extension(name: str) -> str:
    """The extension of a file name when it names a file type: not `.s004` in PLOS's
    `journal.ppat.1002331.s004`."""
    suffix = Path(name).suffix.lower()
    known = SUPPLEMENT_SUFFIXES | VIDEOS | IMAGES
    return suffix if suffix in known or mimetypes.guess_type(f"x{suffix}")[0] else ""


def _url_name(url: str) -> str:
    """The last part of the URL's path, or of its query when the path names no file."""
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
    if not _extension(name) and parsed.query:
        name = re.split(r"[=/]", unquote(parsed.query))[-1]
    return name


def _left_out(name: str, caption: str = "") -> bool:
    """Whether a supplementary file is never fetched: a video (or an archive named as videos,
    `movies_s1_to_s3.zip`), or by its caption the Reporting Summary (a checklist) or the peer
    review file: none holds an interaction."""
    if is_video(name):
        return True
    useless = r"reporting summary|peer review (file|report)|transparent peer review"
    return re.search(useless, caption, re.I) is not None


def _typed(name: str, content_type: str) -> str:
    """A file name with the extension of its type, from the response when the name gives none."""
    if Path(name).suffix.lower() not in SUPPLEMENT_SUFFIXES | IMAGES:
        name += mimetypes.guess_extension(content_type) or ""
    return name


def unpacked(name: str, body: bytes, url: str) -> Iterator[tuple[str, str, bytes]]:
    """A downloaded file, or each file of a zip archive but its videos: its name, its URL
    (`<url>#<path>` for a file of an archive) and its body."""
    archive = _zip(body) if name.lower().endswith(".zip") else None
    if archive is None:
        yield name, url, body
        return
    for info in archive.infolist():
        member = Path(info.filename)
        if info.is_dir() or "__MACOSX" in member.parts or member.name[:1] == ".":
            continue
        if not _left_out(member.name):
            yield from unpacked(member.name, archive.read(info), f"{url}#{info.filename}")


def _same_file(name: str, url: str, text: str = "") -> bool:
    """Whether a link holds the file the article names: the same file name; or its name,
    extension apart, standing whole in the URL (`s004` in `...journal.ppat.1002331.s004`,
    `mmc1` in `...-mmc1.xlsx`); or, for a label rather than a file name (`Table S1`), standing
    whole in the link's text."""
    if Path(unquote(urlparse(url).path)).name.lower() == name.lower():
        return True
    stem = (Path(name).stem if _extension(name) else name).lower()
    whole = rf"(?<![a-z0-9]){re.escape(stem)}(?![a-z0-9])"
    if len(stem) >= 3 and re.search(whole, unquote(url).lower()):
        return True
    return not _extension(name) and bool(re.search(whole, one_line(text).lower()))


def _is_preprint(location: dict[str, Any]) -> bool:
    urls = [(location.get(k) or "").lower() for k in ("landing_page_url", "pdf_url")]
    return any(
        any(host in urlparse(url).netloc for host in PREPRINT_HOSTS)
        or any(f"doi.org/{prefix}" in url for prefix in PREPRINT_DOIS)
        for url in urls
    )


def _locations(work: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], work.get("locations") or [])


def _is_pmc(url: str | None) -> bool:
    return any(host in urlparse(url or "").netloc for host in PMC_HOSTS)


def _pmcid(url: str | None) -> str | None:
    """The PMCID of a PMC link: `.../pmc/articles/123` or `.../articles/PMC123/`."""
    m = re.search(r"/articles/(?:PMC)?(\d+)", url or "") if _is_pmc(url) else None
    return f"PMC{m.group(1)}" if m else None


def pmcids(record: dict[str, Any], work: dict[str, Any]) -> list[str]:
    """Every PMCID of a publication, Europe PMC's first: Europe PMC can lag behind PMC, and
    OpenAlex gives some only in the links of its PMC copies."""
    ids = cast(dict[str, Any], work.get("ids") or {})
    found = [record.get("pmcid"), _pmcid(ids.get("pmcid"))]
    found += [_pmcid(x.get("landing_page_url")) for x in _locations(work)]
    return list(dict.fromkeys(p for p in found if p))


def _pmc_license(record: dict[str, Any], work: dict[str, Any]) -> str:
    if record.get("license"):
        return record["license"]
    for location in _locations(work):
        if _is_pmc(location.get("landing_page_url")) and location.get("license"):
            return location["license"]
    return "no license given"


@dataclass
class Supplement:
    """A supplementary file the article lists: its file name (or the label the curation gives
    it), its caption, and the link the article gives to it when that link can be fetched."""

    name: str
    caption: str = ""
    url: str | None = None


def jats_supplements(xml: bytes) -> list[Supplement]:
    """The supplementary files of a PMC XML, in their order, with their captions."""
    root = _xml(xml)
    found: dict[str, Supplement] = {}
    if root is None:
        return []

    def caption(node: _Element) -> str:
        return " ".join(_text(c) for c in node if tag_name(c) in ("label", "caption"))

    for el in root.iter("{*}supplementary-material", "{*}inline-supplementary-material"):
        for node in [el, *el.iter("{*}media")]:
            name = node.get(XLINK)
            if name and name not in found:
                # The caption of the material, or of its file (Nature's: `media/caption`).
                both = (caption(el), caption(node) if node is not el else "")
                found[name] = Supplement(name, " ".join(c for c in both if c))
    return list(found.values())


def pmc_page_supplements(page: bytes) -> list[Supplement]:
    """The supplementary files of a PMC article page, from its supplementary sections. Their
    links on the PMC website are behind a challenge: only their names are kept."""
    doc = _html(page)
    found: dict[str, Supplement] = {}
    if doc is None:
        return []
    for section in doc.iter("section"):
        if "sm" not in class_names(section):
            continue
        for a in section.iter("a"):
            href = a.get("href") or ""
            if "/bin/" in href:
                name = _url_name(href)
                found.setdefault(name, Supplement(name, _text(section)))
    return list(found.values())


def _is_preprint_doi(doi: str | None) -> bool:
    return bool(doi) and doi.lower().removeprefix("https://doi.org/").startswith(PREPRINT_DOIS)


def pmc_xml_problem(xml: bytes) -> str | None:
    """Why a PMC XML is not the article: no body (`efetch` answers the front matter alone for an
    article it does not serve), or the copy of a preprint, by its own DOI."""
    if b"<body" not in xml:
        return "no body"
    doi = re.search(rb'<article-id pub-id-type="doi">\s*([^<\s]+)', xml)
    return "a preprint" if doi and _is_preprint_doi(doi.group(1).decode(errors="replace")) else None


def pmc_page_problem(page: bytes) -> str | None:
    """Why a PMC article page is not the article: no body sections, or the copy of a preprint,
    by its own DOI (`citation_doi`)."""
    if not pmc_page_has_body(page):
        return "no body sections"
    return "a preprint" if _is_preprint_doi(_meta(page, "citation_doi")) else None


def pmc_page_has_body(page: bytes) -> bool:
    """A PMC article page holds the article when its main body has sections of its own, beyond
    the abstract and the back matter: those have a class, or are notes."""
    doc = _html(page)
    if doc is None:
        return False
    for body in doc.iter("section"):
        if "main-article-body" not in class_names(body):
            continue
        for section in body.iterchildren("section"):
            own = not section.get("class") and not (section.get("id") or "").startswith("notes")
            if own and next(section.iter("p"), None) is not None:
                return True
    return False


def declared_access(page: bytes) -> bool | None:
    """What a publisher's page declares of the article's access: True free, False a paywall,
    None nothing. Free: `"isAccessibleForFree": true`, `<meta name="access" content="Yes">`,
    `citation_fulltext_world_readable`, or a link to the article's Creative Commons license
    (PLOS declares it only so, in its copyright line). A paywall declared anywhere wins."""
    found = {
        m.lower()
        for m in re.findall(
            rb'"isAccessibleForFree"\s*:\s*"?(true|false)', page, flags=re.IGNORECASE
        )
    }
    doc = _html(page)
    for meta in doc.iter("meta") if doc is not None else iter(()):
        name, content = (meta.get("name") or "").lower(), (meta.get("content") or "").lower()
        if name == "access" and content in ("yes", "no"):
            found.add(b"true" if content == "yes" else b"false")
        elif name == "citation_fulltext_world_readable":
            found.add(b"true")
    for link in doc.iter("a", "link") if doc is not None else iter(()):
        if "creativecommons.org/licenses/" in (link.get("href") or "").lower():
            found.add(b"true")
    if b"false" in found:
        return False
    return True if b"true" in found else None


def _meta(page: bytes, name: str) -> str | None:
    doc = _html(page)
    for meta in doc.iter("meta") if doc is not None else iter(()):
        if (meta.get("name") or "").lower() == name and meta.get("content"):
            return meta.get("content")
    return None


def supplement_links(page: bytes, base: str) -> list[Supplement]:
    """The supplementary files a publisher's page links: a link or a URL that says
    supplementary (`mmc` is Elsevier's name for them, `MOESM` Springer Nature's), to a file type
    or to a URL that names no type (PLOS: `article/file?type=supplementary&id=...`)."""
    doc = _html(page)
    found: dict[str, Supplement] = {}
    for a in doc.iter("a") if doc is not None else iter(()):
        href = a.get("href")
        if not href or href.startswith("#"):
            continue
        url, text = urljoin(base, href), _text(a)
        lowered = unquote(url).lower()
        named = re.search(r"supp|mmc\d|moesm", lowered) or re.search(r"supp|additional", text, re.I)
        suffix = Path(urlparse(url).path).suffix.lower()
        typed = suffix in SUPPLEMENT_SUFFIXES | VIDEOS | IMAGES or "supplementary" in lowered
        if named and typed and url not in found:
            found[url] = Supplement(_url_name(url), text, url)
    return list(found.values())


class Fetch:
    def __init__(self, out: Path, pmid: int, get: Get) -> None:
        self.out, self.pmid, self.get = out, pmid, get
        self.report: dict[str, Any] = {"file": None}
        self.tried: list[dict[str, str]] = []  # the routes of the article
        self.record: dict[str, Any] = {}
        self.work: dict[str, Any] = {}
        self.pmcids: list[str] = []
        self.doi: str | None = None
        self.listed: list[Supplement] = []
        self.oa_files: dict[str, str] = {}  # the PMC open access files, name to URL
        self._page: Response | None = None
        self._copies: list[dict[str, Any]] | None = None
        self._archive: tuple[zipfile.ZipFile | None, str] | None = None  # and its outcome
        load_dotenv()

    # Requests

    def _try(self, url: str) -> Response:
        r = self.get(url)
        self.tried.append({"url": url, "outcome": _outcome(r)})
        return r

    def _note(self, outcome: str) -> None:
        self.tried[-1]["outcome"] += f", {outcome}"

    @property
    def page(self) -> Response | None:
        """The publisher's page, at the DOI, asked once."""
        if self._page is None and self.doi:
            self._page = self._try(f"https://doi.org/{self.doi}")
            if self._page.status == 200 and _is_html(self._page):
                said: dict[bool | None, str] = {
                    True: "declares free access",
                    False: "declares a paywall",
                    None: "declares no access",
                }
                self._note(said[declared_access(self._page.body)])
        return self._page

    @property
    def html_page(self) -> Response | None:
        """The publisher's page when it is an HTML page."""
        page = self.page
        return page if page is not None and page.status == 200 and _is_html(page) else None

    @property
    def copies(self) -> list[dict[str, Any]]:
        """The free copies OpenAlex and Unpaywall list, best first, never a preprint nor a PMC
        copy (fetched by its PMCID). Unpaywall is asked once, and only when needed."""
        if self._copies is None:
            best = self.work.get("best_oa_location")
            locations = [best] if best else []
            locations += [x for x in _locations(self.work) if x.get("is_oa") and x != best]
            if self.doi:
                locations += self.unpaywall(self.doi)
            self._copies, seen = [], set[str]()
            for location in locations:
                key = f"{location.get('landing_page_url')}|{location.get('pdf_url')}"
                if _is_pmc(location.get("landing_page_url")) or key in seen:
                    continue
                seen.add(key)
                self._copies.append(location)
        return self._copies

    def unpaywall(self, doi: str) -> list[dict[str, Any]]:
        """Unpaywall's open access copies, in its own order (best first). It answers only a
        request that carries an address, so it is asked only when one is configured."""
        email = os.environ.get("UNPAYWALL_EMAIL")
        if not email:
            return []
        record = _json(self.get, f"{UNPAYWALL}/{quote(doi)}?email={quote(email)}")
        locations = cast(list[dict[str, Any]], (record or {}).get("oa_locations") or [])
        return [
            {
                "is_oa": True,
                "landing_page_url": x.get("url_for_landing_page") or x.get("url"),
                "pdf_url": x.get("url_for_pdf"),
                "license": x.get("license"),
                "source": {"display_name": x.get("repository_institution") or "Unpaywall"},
            }
            for x in locations
        ]

    def _publisher(self) -> dict[str, Any]:
        """The publisher's location in OpenAlex, the one at the DOI, for its name and license."""
        doi = f"https://doi.org/{self.doi}".lower()
        for location in _locations(self.work):
            if (location.get("landing_page_url") or "").lower() == doi:
                return location
        return {}

    # Access

    def free(self) -> bool:
        return bool(
            self.pmcids
            or [x for x in self.copies if not _is_preprint(x)]
            or ((page := self.html_page) is not None and declared_access(page.body) is True)
        )

    def closed_why(self) -> str:
        if any(_is_preprint(x) for x in self.copies):
            return "open access only as a preprint"
        return "not open access anywhere"

    # The article

    def article_routes(self) -> Iterator[Callable[[], bool]]:
        for pmcid in self.pmcids:
            yield lambda pmcid=pmcid: self.pmc_files(pmcid)
            yield lambda pmcid=pmcid: self.pmc_xml(pmcid, f"{EUROPE_PMC}/{pmcid}/fullTextXML")
            yield lambda pmcid=pmcid: self.pmc_xml(pmcid, f"{EFETCH}?db=pmc&id={pmcid}&rettype=xml")
        for pmcid in self.pmcids:
            yield lambda pmcid=pmcid: self.pmc_page(pmcid)
        yield self.publisher_html
        yield self.pdfs

    def _save(self, body: bytes, suffix: str) -> None:
        name = f"{self.pmid}{suffix}"
        (self.out / name).write_bytes(body)
        self.report["file"] = name

    def _from_pmc(self, pmcid: str) -> None:
        license_ = _pmc_license(self.record, self.work)
        self.report.update(source=pmcid, url=f"{PMC_PAGE}/{pmcid}/", license=license_)

    def _from(self, url: str, location: dict[str, Any]) -> None:
        venue = cast(dict[str, Any], location.get("source") or {})
        source = venue.get("display_name") or urlparse(url).netloc
        license_ = location.get("license") or "no license given"
        self.report.update(source=source, url=url, license=license_)

    def pmc_listing(self, pmcid: str) -> str | None:
        """The latest version of a PMC copy in the open access files (`PMC123.2` after
        `PMC123.1`), its files kept as a route of the supplementary files."""
        listing = self._try(f"{PMC_AWS}/?list-type=2&prefix={pmcid}.")
        keys = re.findall(r"<Key>([^<]+)</Key>", listing.body.decode(errors="replace"))
        if not keys:
            if listing.status == 200:
                self._note("not in the PMC open access files")
            return None
        version = max({k.split("/")[0] for k in keys}, key=lambda v: int(v.split(".")[1]))
        for key in keys:
            folder, _, name = key.partition("/")
            if folder == version:
                self.oa_files[name] = f"{PMC_AWS}/{version}/{quote(name)}"
        return version

    def pmc_files(self, pmcid: str) -> bool:
        """The PMC open access files: their XML, as `pmc_xml`."""
        version = self.pmc_listing(pmcid)
        return version is not None and self.pmc_xml(pmcid, f"{PMC_AWS}/{version}/{version}.xml")

    def pmc_xml(self, pmcid: str, url: str) -> bool:
        """A PMC XML (the open access files', Europe PMC `fullTextXML` or NCBI `efetch`), the
        article when it has a body and is no preprint."""
        xml = self._try(url)
        if xml.status != 200:
            return False
        if problem := pmc_xml_problem(xml.body):
            self._note(problem)
            return False
        self._save(xml.body, ".xml")
        self._from_pmc(pmcid)
        self._list(jats_supplements(xml.body), "the article's XML")
        return True

    def pmc_page(self, pmcid: str) -> bool:
        """The PMC article page: the whole article of a PMC copy outside the open access files.
        NCBI forbids bulk downloads from its website: one page per publication."""
        r = self._try(f"{PMC_PAGE}/{pmcid}/")
        if r.status != 200:
            return False
        if problem := pmc_page_problem(r.body):
            self._note(problem)
            return False
        self._save(r.body, ".html")
        self._from_pmc(pmcid)
        self._list(pmc_page_supplements(r.body), "the PMC article page")
        return True

    def publisher_html(self) -> bool:
        """The publisher's page, the article when it declares free access."""
        page = self.html_page
        if page is None or declared_access(page.body) is not True:
            return False
        self._save(page.body, ".html")
        self._from(page.url, self._publisher())
        return True

    def pdfs(self) -> bool:
        """The publisher's PDF (`citation_pdf_url`), then the other free copies' PDFs."""
        candidates: list[tuple[str, dict[str, Any]]] = []
        if (page := self.html_page) is not None and (url := _meta(page.body, "citation_pdf_url")):
            candidates.append((url, self._publisher()))
        for location in self.copies:
            if not _is_preprint(location):
                for key in ("pdf_url", "landing_page_url"):
                    if url := location.get(key):
                        candidates.append((url, location))
        seen: set[str] = {t["url"] for t in self.tried}
        for url, location in candidates:
            if url in seen:
                continue
            seen.add(url)
            r = self._try(url)
            if r.status == 200 and _is_pdf(r):
                self._save(r.body, ".pdf")
                self._from(url, location)
                return True
            if r.status == 200:
                self._note("not a PDF")
        return False

    def _list(self, supplements: list[Supplement], source: str) -> None:
        self.listed = supplements
        self.report["supplements_from"] = source

    # The supplementary files

    def supplement_routes(self, item: Supplement) -> Iterator[str]:
        """The URLs that may serve a file, in order; Europe PMC's archive comes after them all."""
        for name, url in self.oa_files.items():
            if name == item.name or _same_file(item.name, url):
                yield url
        if item.url and not _is_pmc(item.url):
            yield item.url
        if (page := self.html_page) is not None:
            for link in supplement_links(page.body, page.url):
                if (
                    link.url
                    and link.url != item.url
                    and _same_file(item.name, link.url, link.caption)
                ):
                    yield link.url

    def find(self, items: list[Supplement]) -> list[tuple[Supplement, list[dict[str, str]]]]:
        """Each file looked for on every route, one over the limit left out; returns the files
        still missing, with every place tried."""
        missing: list[tuple[Supplement, list[dict[str, str]]]] = []
        for item in items:
            if _left_out(item.name, item.caption):
                continue
            tried: list[dict[str, str]] = []
            for url in dict.fromkeys(self.supplement_routes(item)):
                r = self.get(url, LIMIT)
                tried.append({"url": url, "outcome": _outcome(r)})
                if r.over_limit:
                    self._over(item, url, r.size)
                    break
                if self._take(item, r, url, tried):
                    break
            else:
                missing.append((item, tried))
        if missing and self.pmcids:
            missing = self.from_europe_pmc(missing)
        return missing

    def from_europe_pmc(
        self, missing: list[tuple[Supplement, list[dict[str, str]]]]
    ) -> list[tuple[Supplement, list[dict[str, str]]]]:
        """Europe PMC's supplementary files service: one archive of all of them, slow, so it is
        asked once and last."""
        url = f"{EUROPE_PMC}/{self.pmcids[0]}/supplementaryFiles"
        if self._archive is None:
            r = self.get(url, LIMIT)
            archive = _zip(r.body) if r.status == 200 and r.body[:2] == b"PK" else None
            no_archive = "" if archive or r.over_limit else ", no archive"
            self._archive = (archive, _outcome(r) + no_archive)
        archive, outcome = self._archive
        still: list[tuple[Supplement, list[dict[str, str]]]] = []
        for item, tried in missing:
            members = [
                m
                for m in (archive.infolist() if archive else [])
                if not m.is_dir() and _same_file(item.name, Path(m.filename).name)
            ]
            for member in members:
                assert archive is not None
                where = f"{url}#{member.filename}"
                if member.file_size > LIMIT:
                    self._over(item, where, member.file_size)
                    continue
                body = archive.read(member)
                self._keep(item, Path(member.filename).name, body, where)
            if not members:
                place = outcome if archive is None else f"{outcome}, not in it"
                still.append((item, [*tried, {"url": url, "outcome": place}]))
        return still

    def _take(self, item: Supplement, r: Response, url: str, tried: list[dict[str, str]]) -> bool:
        """Whether a response is the file: kept, or skipped once its type shows a video."""
        if r.status != 200:
            return False
        if r.content_type.startswith("video/"):  # a link that named no type
            return True
        if _is_html(r):
            tried[-1]["outcome"] += ", an HTML page"
            return False
        name = item.name if _extension(item.name) else _url_name(url)
        self._keep(item, _typed(name, r.content_type), r.body, url)
        return True

    def _over(self, item: Supplement, url: str, size: int | None) -> None:
        """A supplementary file over the limit: not downloaded, reported with its URL."""
        self.report["over_limit"].append({"name": item.name, "url": url, "size": size})

    def _keep(self, item: Supplement, name: str, body: bytes, url: str) -> None:
        """A supplementary file saved, a zip archive unpacked (its videos left out), each file
        made ready to read (`prepare`)."""
        for file, where, content in unpacked(name, body, url):
            path = save(self.out / f"{self.pmid}.supp", file, content)
            for ready in prepare(self.out, str(path.relative_to(self.out))):
                self.report.setdefault("supplements", []).append(
                    {"name": item.name, "file": ready, "url": where}
                )

    def figures(self) -> None:
        """The article's figures: the images of the PMC open access files that are no
        supplementary file."""
        figures: list[str] = []
        taken = {x["url"] for x in self.report["supplements"] + self.report["over_limit"]}
        for name, url in self.oa_files.items():
            if is_image(Path(name)) and url not in taken and (r := self.get(url)).status == 200:
                for file, _, content in unpacked(name, r.body, url):
                    path = save(self.out / f"{self.pmid}.fig", file, content)
                    figures += prepare(self.out, str(path.relative_to(self.out)))
        self.report["figures"] = figures

    # The report

    def _missing(self, item: Supplement, tried: list[dict[str, str]]) -> dict[str, Any]:
        entry: dict[str, Any] = {"name": item.name}
        if item.caption:
            entry["caption"] = item.caption[:CAPTION_LENGTH]
        if item.url:
            entry["url"] = item.url
        entry["tried"] = tried
        return entry

    def conclude(self) -> None:
        """The first line of the report: where the article comes from, or why there is none."""
        report = self.report
        if report["file"] is None:
            if report["free"]:
                report["why"] = self.not_downloaded_why()
                report["line"] = f"Full text: not downloaded — {report['why']}"
            else:
                report["line"] = f"Full text: closed — {report['why']}"
            return
        report.pop("why", None)
        if report["source"] in self.pmcids:
            report["line"] = f"Full text: {report['source']} ({report['license']})"
        else:
            report["line"] = f"Full text: {report['source']} ({report['license']}, {report['url']})"
        if missing := [x["name"] for x in report["missing_supplements"]]:
            report["line"] += ", supplementary files missing: " + ", ".join(missing)
        if over := list(dict.fromkeys(x["name"] for x in report["over_limit"])):
            report["line"] += f", supplementary files {_over_limit(None)}: " + ", ".join(over)

    def not_downloaded_why(self) -> str:
        """Why a free article was not downloaded: the first copy tried, outside the services
        and the preprints."""
        copies = [
            t
            for t in self.tried
            if not t["url"].startswith(SERVICES) and not t["outcome"].endswith("a preprint")
        ]
        for t in copies:
            if not t["outcome"].startswith("HTTP 200"):
                return f"a free copy at {t['url']} but download blocked ({t['outcome']})"
        if copies:
            return f"a free copy at {copies[0]['url']} but no article there"
        return "free, but no copy to download"

    # The manifest

    def write_manifest(self) -> None:
        """Every file converted, then the manifest of every file downloaded, written last, when
        the article was downloaded: a manifest means the curation can start."""
        report = self.report
        article = self._entry(report)
        supplements = [{"name": x["name"]} | self._entry(x) for x in report["supplements"]]
        path = self.out / MANIFEST
        tmp = path.with_suffix(".json.tmp")
        manifest = {"article": article, "supplements": supplements, "figures": report["figures"]}
        tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(path)

    def _entry(self, x: dict[str, Any]) -> dict[str, Any]:
        """A file's entry of the manifest (`entry`), why it could not be converted moved to the
        report."""
        found = entry(self.out, x["file"])
        if why := found.pop("not_converted", None):
            x["not_converted"] = why
        return found

    # The fetch

    def _identify(self) -> None:
        query = quote(f"EXT_ID:{self.pmid} AND SRC:MED")
        search = _json(self.get, f"{EUROPE_PMC}/search?query={query}&format=json&resultType=core")
        results = (search or {}).get("resultList", {}).get("result", [])
        self.record = cast(dict[str, Any], results[0]) if results else {}
        self.work = _json(self.get, f"{OPENALEX}/pmid:{self.pmid}") or {}
        self.pmcids = pmcids(self.record, self.work)
        # Europe PMC may give the DOI of the preprint, never the article's.
        work_doi = (self.work.get("doi") or "").removeprefix("https://doi.org/")
        dois = [d for d in (self.record.get("doi"), work_doi) if d]
        self.doi = next((d for d in dois if not _is_preprint_doi(d)), None)

    def run(self) -> dict[str, Any]:
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / MANIFEST).unlink(missing_ok=True)
        self._identify()
        report = self.report
        report.update(doi=self.doi, free=self.free())
        if not report["free"]:
            report["why"] = self.closed_why()
        any(route() for route in self.article_routes())
        report["tried"] = self.tried
        if report["file"] is not None:
            if "supplements_from" not in report and (page := self.html_page) is not None:
                self._list(supplement_links(page.body, page.url), "the publisher's page")
            report.setdefault("supplements", [])
            report["over_limit"] = []
            missing = self.find(self.listed)
            report["missing_supplements"] = [self._missing(item, tried) for item, tried in missing]
            self.figures()
            self.write_manifest()
        self.conclude()
        return report


def fetch(out: Path, pmid: int, get: Get = http_get) -> dict[str, Any]:
    """The full text fetched and converted, its manifest written; returns the report."""
    return Fetch(out, pmid, get).run()


def report_lines(report: dict[str, Any]) -> list[str]:
    """The report printed: its first line, then what could not be had."""
    lines = [report["line"]]
    if report["file"] is None:
        lines += [f"  tried {t['url']} ({t['outcome']})" for t in report["tried"]]
    elif why := report.get("not_converted"):
        lines.append(f"  {report['file']}: not converted, {why}")
    for x in report.get("supplements", []):
        if why := x.get("not_converted"):
            lines.append(f"  {x['name']}: not converted, {why}")
    for x in report.get("missing_supplements", []):
        places = "; ".join(f"{t['url']} ({t['outcome']})" for t in x["tried"])
        lines.append(f"  {x['name']}: missing, tried {places or 'nothing: no route holds it'}")
    for x in report.get("over_limit", []):
        lines.append(f"  {x['name']}: {_over_limit(x['size'])}, not downloaded, {x['url']}")
    return lines


def download(out: Path, url: str, get: Get = http_get) -> list[str]:
    """The file at a URL saved in `out`, an archive unpacked, each file made ready to read and
    converted (`entries`); returns one line per file: its entry, as in the manifest (paths
    starting with `out`), or why it could not be had or converted."""
    r = get(url)
    if r.status != 200:
        return [_outcome(r)]
    name = _typed(_url_name(r.url or url) or "file", r.content_type)
    lines: list[str] = []
    for file, _, content in unpacked(name, r.body, r.url or url):
        for found in entries(Path(), str(save(out, file, content))):
            if why := found.pop("not_converted", None):
                lines.append(f"{found['file']}: not converted, {why}")
            else:
                lines.append(json.dumps(found, ensure_ascii=False))
    return lines
