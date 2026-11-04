"""The GenBank tool, on NCBI answers recorded here (no network)."""

import json
from urllib.parse import parse_qs, urlparse

from curation.fetch import EFETCH, Response
from curation.genbank import ELINK, ESEARCH, ESUMMARY, SOURCES, Eutils, Page, search, seq

POLYPROTEIN = "MSTNPKPQRKTKRNTNRRPEDVKFPGGGQIVGGVYLLPRRGPRLGVRTTRKTSERSQPRGRRQPIPKDRR"
FASTA = (
    f">BAB32872.1 polyprotein [Hepatitis C virus JFH-1]\n{POLYPROTEIN[:40]}\n{POLYPROTEIN[40:]}\n"
)


def ok(text: str) -> Response:
    return Response("", 200, "text/plain", text.encode())


def ncbi(url: str, limit: int | None = None) -> Response:
    """NCBI as recorded: BAB32872 a protein, AB047639 a genome coding for two, any other search
    three records, anything else unknown."""
    base = url.split("?")[0]
    query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert query["tool"] == "curation"
    if base == EFETCH and query["db"] == "protein" and query["id"] == "BAB32872":
        return ok(FASTA)
    if base == ESEARCH and query["term"] == f"(AB047639) AND ({SOURCES})":  # a genome: no protein
        return ok(json.dumps({"esearchresult": {"count": "0", "idlist": []}}))
    if base == ESEARCH and query["db"] == "nuccore" and query["term"] == "AB047639[accn]":
        return ok(json.dumps({"esearchresult": {"count": "1", "idlist": ["13122260"]}}))
    if base == ELINK and query["id"] == "13122260":
        links = [{"linkname": "nuccore_protein", "links": ["13122262", "13122263"]}]
        return ok(json.dumps({"linksets": [{"linksetdbs": links}]}))
    if base == ESEARCH:
        assert query["term"].endswith(f" AND ({SOURCES})")  # GenBank and RefSeq only
        ids = ["13122262", "13122263", "13122264"][: int(query["retmax"])]
        return ok(json.dumps({"esearchresult": {"count": "3", "idlist": ids}}))
    if base == ESUMMARY:
        result = {
            uid: {
                "accessionversion": f"BAB3287{i}.1",
                "title": "x" * 300,
                "slen": 3033,
                "taxid": 356411,
                "organism": "Hepatitis C virus JFH-1",
            }
            for i, uid in enumerate(query["id"].split(","))
        }
        return ok(json.dumps({"result": result}))
    return Response(url, 400, "", b"Error")


def test_seq():
    """A protein whole or between coordinates; a genome's accession, no protein record."""
    eutils = Eutils(ncbi, pause=0)
    lines = seq(eutils, ["BAB32872:1-15", "BAB32872", "AB047639", "BAB32872:1-999"])
    assert lines.splitlines() == [
        "#location\taccession\ttitle\tlength\tsequence",
        "BAB32872:1-15\tBAB32872.1\tpolyprotein [Hepatitis C virus JFH-1]\t15\tMSTNPKPQRKTKRNT",
        f"BAB32872\tBAB32872.1\tpolyprotein [Hepatitis C virus JFH-1]\t70\t{POLYPROTEIN}",
        "AB047639\tno protein record at NCBI (a genome: search lists its proteins)",
        "BAB32872:1-999\t1-999 is not a stretch of 1-70",
    ]


def test_search_is_paged():
    eutils = Eutils(ncbi, pause=0)
    lines = search(eutils, ["JFH-1"], Page(limit=2)).splitlines()
    assert lines[1] == (
        "JFH-1\tBAB32870.1\t" + "x" * 120 + "…\t3033\t356411 Hepatitis C virus JFH-1"
    )
    assert lines[-1] == "JFH-1\t… 2 of 3 shown, cut by --limit 2"


def test_search_reads_a_genome_accession():
    """A nucleotide accession, which the protein search does not find: the proteins it codes."""
    lines = search(Eutils(ncbi, pause=0), ["AB047639"]).splitlines()
    assert [line.split("\t")[:2] for line in lines[1:]] == [
        ["AB047639", "BAB32870.1"],
        ["AB047639", "BAB32871.1"],
    ]
