"""PubMed for the runs: `associate`, `populate` and `abstracts`, run by the scripts of the same
names (`database/scripts/`), which describe them.

A run's `info` holds the query that filled it and its window of entry dates, as JSON:
`{"query": <text>, "from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}`.

A publication's `metadata` is its PubMed XML record (efetch) as JSON, as the original import
wrote every record stored (drakkar-cli, `src/Services/Efetch.php`): the XML prepared (`_prepare`),
then converted as PHP's SimpleXML and `json_encode` do. An element is an object of its children,
its attributes under `@attributes`, a repeated child a list; an element without children is its
text, its attributes dropped, or, when empty, `{}` or its `@attributes`. `ArticleTitle` and
`AbstractText` are their raw XML text, character references and inline tags (`<i>`, `<sub>`…)
kept, a line break between adjacent tags; elsewhere an inline tag is a child, the text around it
dropped.
"""

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any, cast

import psycopg
from dotenv import load_dotenv
from lxml import etree

from database.db import require_idle

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
# PubMed returns at most 10,000 PMIDs per search: a window holding more is searched by halves.
MAX_PMIDS = 9_999

# PMIDs per efetch request.
FETCH_SIZE = 200
Search = Callable[[str, date, date], list[int]]
Fetch = Callable[[Sequence[int]], str]


class _Eutils:
    """Requests to the NCBI E-utilities, spaced as NCBI asks (3 per second, 10 with a key), each
    tried again a few times on a network or server error."""

    def __init__(self) -> None:
        load_dotenv()
        self.key = os.environ.get("NCBI_API_KEY")
        self.pause = 0.11 if self.key else 0.34
        self.last = 0.0

    def __call__(self, tool: str, **params: str | int) -> str:
        params = {**params, "tool": "drakkar", **({"api_key": self.key} if self.key else {})}
        data = urllib.parse.urlencode(params).encode()
        for attempt in range(5):
            wait = self.last + self.pause - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                request = urllib.request.Request(f"{EUTILS}/{tool}", data=data)
                with urllib.request.urlopen(request, timeout=300) as response:
                    return response.read().decode()
            except (urllib.error.URLError, TimeoutError):
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
            finally:
                self.last = time.monotonic()
        raise AssertionError("unreachable")


def _esearch(eutils: _Eutils, term: str, retmax: int) -> tuple[int, list[int]]:
    """One PubMed search: its count and its PMIDs. PubMed's error, or a term it could not read,
    raises `ValueError`."""
    body = eutils("esearch.fcgi", db="pubmed", term=term, retmax=retmax, retmode="json")
    found: dict[str, Any] = json.loads(body)["esearchresult"]
    if "ERROR" in found:
        raise ValueError(f"PubMed: {found['ERROR']}")
    errors: dict[str, list[str]] = found.get("errorlist") or {}
    if errors.get("phrasesnotfound"):
        raise ValueError(f"PubMed does not know: {', '.join(errors['phrasesnotfound'])}")
    return int(found["count"]), [int(pmid) for pmid in found["idlist"]]


def search(query: str, start: date, end: date) -> list[int]:
    """The PMIDs of the query among the records entered in PubMed from `start` to `end`
    (inclusive, `[crdt]`), sorted."""
    eutils = _Eutils()

    def window(start: date, end: date) -> set[int]:
        term = f'({query}) AND ("{start:%Y/%m/%d}"[crdt] : "{end:%Y/%m/%d}"[crdt])'
        count, pmids = _esearch(eutils, term, MAX_PMIDS)
        if count <= MAX_PMIDS:
            return set(pmids)
        if start == end:
            raise ValueError(f"more than {MAX_PMIDS} PMIDs entered on {start}")
        middle = start + (end - start) // 2
        return window(start, middle) | window(middle + timedelta(days=1), end)

    return sorted(window(start, end))


def associate(
    conn: psycopg.Connection,
    run_id: int,
    query: str,
    start: date,
    end: date,
    *,
    search: Search = search,
) -> str:
    """Associates to the run, as `pending`, the PMIDs the query finds among the records entered in
    PubMed from `start` to `end`, except those already associated to another run of its type, and
    records the query and the window in its `info`. The new publications are inserted without
    metadata (`populated` false). One transaction, committed. A run that does not exist, or whose
    `info` is already set, is refused: a run is filled by one query, once."""
    require_idle(conn)
    query = " ".join(query.split())
    if not query:
        raise ValueError("the query is empty")
    if start > end:
        raise ValueError(f"the window starts after it ends: {start} > {end}")
    with conn.cursor() as cur:
        cur.execute("SELECT name, type, info FROM runs WHERE id = %s", (run_id,))
        run = cur.fetchone()
    conn.rollback()
    if run is None:
        raise ValueError(f"no run with ID {run_id}")
    name, run_type, info = run
    if info:
        raise ValueError(f"run {name} (ID {run_id}) already has its query: {info[:200]}")

    pmids = search(query, start, end)

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.pmid, a.run_id = %(run)s AS this_run
            FROM associations a
            JOIN runs r ON r.id = a.run_id
            WHERE r.type = %(type)s AND a.pmid = ANY(%(pmids)s)
            """,
            {"run": run_id, "type": run_type, "pmids": pmids},
        )
        associated = cur.fetchall()
        in_this = {pmid for pmid, this_run in associated if this_run}
        in_other = {pmid for pmid, this_run in associated if not this_run} - in_this
        new = [pmid for pmid in pmids if pmid not in in_this and pmid not in in_other]
        cur.execute(
            "INSERT INTO publications (pmid) SELECT unnest(%s::bigint[]) ON CONFLICT DO NOTHING",
            (new,),
        )
        inserted = cur.rowcount
        cur.execute(
            "INSERT INTO associations (run_id, pmid) SELECT %s, unnest(%s::bigint[])",
            (run_id, new),
        )
        window = {"query": query, "from": start.isoformat(), "to": end.isoformat()}
        cur.execute("UPDATE runs SET info = %s WHERE id = %s", (json.dumps(window), run_id))
    return "\n".join(
        [
            f"run {name} (ID {run_id}), records entered in PubMed from {start} to {end}:",
            f"{len(pmids)} PMIDs found",
            f"{len(in_other)} already associated to another {run_type} run, left out",
            f"{len(in_this)} already associated to this run, left as they are",
            f"{len(new)} associated as pending, {inserted} of them new publications",
        ]
    )


def _prepare(xml: str) -> str:
    """The PubMed XML as the original import prepared it before parsing (drakkar-cli,
    `src/Services/Efetch.php`): a line break between adjacent tags, the content of
    `ArticleTitle` and `AbstractText` wrapped in CDATA, so that their raw text is kept, and the
    empty `AbstractText` removed."""
    xml = xml.replace("><", ">\n<")
    xml = re.sub(
        r"<ArticleTitle(.*?)>(.+?)</ArticleTitle>",
        r"<ArticleTitle\1><![CDATA[\2]]></ArticleTitle>",
        xml,
        flags=re.S,
    )
    xml = re.sub(r"<AbstractText.*?/>", "", xml)
    return re.sub(
        r"<AbstractText(.*?)>(.+?)</AbstractText>",
        r"<AbstractText\1><![CDATA[\2]]></AbstractText>",
        xml,
        flags=re.S,
    )


def _json(element: Any) -> Any:
    """An element as SimpleXML gives it (see the module's docstring)."""
    children = [child for child in element if isinstance(child.tag, str)]
    attributes = dict(element.attrib)
    if not children:
        text = element.text or ""
        if text.strip():
            return text
        return {"@attributes": attributes} if attributes else {}
    out: dict[str, Any] = {"@attributes": attributes} if attributes else {}
    grouped: dict[str, list[Any]] = {}
    for child in children:
        grouped.setdefault(child.tag, []).append(_json(child))
    for tag, values in grouped.items():
        out[tag] = values[0] if len(values) == 1 else values
    return out


def records(xml: str) -> dict[int, dict[str, Any]]:
    """The records of a PubMed XML (efetch), by PMID, each as its `metadata`."""
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.fromstring(_prepare(xml).encode(), parser)
    out: dict[int, dict[str, Any]] = {}
    for record in root:
        pmid = record.findtext("MedlineCitation/PMID") or record.findtext("BookDocument/PMID")
        if isinstance(record.tag, str) and pmid:
            out[int(pmid)] = {record.tag: _json(record)}
    return out


def fetch(pmids: Sequence[int]) -> str:
    """The PubMed XML of the PMIDs (efetch), in one request."""
    return _Eutils()("efetch.fcgi", db="pubmed", id=",".join(map(str, pmids)), retmode="xml")


def populate(conn: psycopg.Connection, run_id: int, *, fetch: Fetch = fetch) -> str:
    """Writes the metadata of the run's publications that have none (`populated` false), fetched
    from PubMed, and sets them populated. One transaction, committed. A PMID PubMed does not
    return is left unpopulated and listed."""
    require_idle(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM runs WHERE id = %s", (run_id,))
        run = cur.fetchone()
        cur.execute(
            """
            SELECT p.pmid
            FROM associations a
            JOIN publications p ON p.pmid = a.pmid
            WHERE a.run_id = %s AND NOT p.populated
            ORDER BY p.pmid
            """,
            (run_id,),
        )
        pmids = [pmid for (pmid,) in cur.fetchall()]
    conn.rollback()
    if run is None:
        raise ValueError(f"no run with ID {run_id}")
    found: dict[int, dict[str, Any]] = {}
    for i in range(0, len(pmids), FETCH_SIZE):
        chunk = pmids[i : i + FETCH_SIZE]
        found |= {pmid: m for pmid, m in records(fetch(chunk)).items() if pmid in chunk}
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            "UPDATE publications SET metadata = %s, populated = true WHERE pmid = %s",
            [(json.dumps(metadata), pmid) for pmid, metadata in found.items()],
        )
    missing = [pmid for pmid in pmids if pmid not in found]
    lines = [
        f"run {run[0]} (ID {run_id}): {len(pmids)} publications without metadata",
        f"{len(found)} populated",
    ]
    if missing:
        lines.append(f"{len(missing)} not returned by PubMed, left unpopulated: {missing}")
    return "\n".join(lines)


def _get(value: Any, *keys: str) -> Any:
    """The value at the keys of nested objects, None where one is missing."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = cast(dict[str, Any], value).get(key)
    return value


def _list(value: Any) -> list[Any]:
    """A repeated element as a list: a list, one value, or none."""
    if value is None:
        return []
    return cast(list[Any], value) if isinstance(value, list) else [value]


def _summary(metadata: Any) -> tuple[Any, Any, Any]:
    """The publication types, title and abstract of a record, where the curators' web app reads
    the title and the abstract (drakkar-web, `MetadataExtension.php`): an article's
    `ArticleTitle`, its `Abstract`, else its `OtherAbstract`; a book's `ArticleTitle` and
    `Abstract`. Of an abstract in parts, only the parts that are text."""
    citation = _get(metadata, "PubmedArticle", "MedlineCitation")
    if citation is not None:
        article = _get(citation, "Article")
        abstract = _get(article, "Abstract") or _get(citation, "OtherAbstract")
        types = _get(article, "PublicationTypeList", "PublicationType")
    else:
        article = _get(metadata, "PubmedBookArticle", "BookDocument")
        abstract = _get(article, "Abstract")
        types = _get(article, "PublicationType")
    texts = [part for part in _list(_get(abstract, "AbstractText")) if isinstance(part, str)]
    return types, _get(article, "ArticleTitle"), texts


def _text(value: Any) -> str:
    """A title or an abstract as plain text: its parts joined, tags removed, entities decoded,
    spaces collapsed."""
    if isinstance(value, list):
        return " ".join(_text(part) for part in cast(list[Any], value))
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", value)).split())


def abstracts(cur: Any, run_id: int, offset: int, count: int) -> str:
    """The run's `pending` publications, ordered by PMID, `count` from `offset`, each as a block:
    `PMID`, `Types` (its publication types), `Title`, `Abstract`, as plain text."""
    if offset < 0 or count < 1:
        raise ValueError(f"offset {offset} and count {count}: an offset from 0, a count from 1")
    cur.execute(
        """
        SELECT a.pmid, p.metadata
        FROM associations a
        JOIN publications p ON p.pmid = a.pmid
        WHERE a.run_id = %s AND a.state = 'pending'
        ORDER BY a.pmid
        OFFSET %s LIMIT %s
        """,
        (run_id, offset, count),
    )
    blocks: list[str] = []
    for pmid, metadata in cur.fetchall():
        types, title, abstract = _summary(metadata)
        blocks.append(
            "\n".join(
                [
                    f"PMID {pmid}",
                    f"Types: {'; '.join(_text(t) for t in _list(types))}",
                    f"Title: {_text(title)}",
                    f"Abstract: {_text(abstract)}",
                ]
            )
        )
    return "\n\n".join(blocks)
