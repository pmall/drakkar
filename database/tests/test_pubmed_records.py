"""The PubMed XML converted to the stored metadata format, and a run's publications populated."""

from datetime import date

from database.pubmed import abstracts, associate, populate, records

XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
<PubmedArticle><MedlineCitation Status="MEDLINE" Owner="NLM"><PMID Version="1">990000001</PMID>
<Article PubModel="Print"><ArticleTitle>Nsp1&#x3b1; binds <i>in vitro</i>.</ArticleTitle>
<Abstract><AbstractText Label="AIMS"><i>K</i><sub><i>A</i></sub> &lt; 25 &#x3bc;M</AbstractText>
<AbstractText>Second.</AbstractText>
<CopyrightInformation>&#xa9; 2026</CopyrightInformation></Abstract>
<AuthorList CompleteYN="Y"><Author ValidYN="Y"><LastName>Doe</LastName></Author></AuthorList>
<PublicationTypeList>
<PublicationType UI="D016428">Journal Article</PublicationType></PublicationTypeList>
<ArticleDate DateType="Electronic"><Year>2026</Year></ArticleDate></Article>
<CoiStatement><b>None</b> declared.</CoiStatement><Empty/></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def test_a_record_is_converted_as_stored():
    ((pmid, metadata),) = records(XML).items()
    citation = metadata["PubmedArticle"]["MedlineCitation"]
    article = citation["Article"]
    assert pmid == 990000001
    assert citation["@attributes"] == {"Status": "MEDLINE", "Owner": "NLM"}
    assert citation["PMID"] == "990000001"
    assert article["ArticleTitle"] == "Nsp1&#x3b1; binds <i>in vitro</i>."
    assert article["Abstract"] == {
        "AbstractText": ["\n<i>K</i>\n<sub>\n<i>A</i>\n</sub> &lt; 25 &#x3bc;M", "Second."],
        "CopyrightInformation": "© 2026",
    }
    assert article["AuthorList"] == {
        "@attributes": {"CompleteYN": "Y"},
        "Author": {"@attributes": {"ValidYN": "Y"}, "LastName": "Doe"},
    }
    assert article["PublicationTypeList"] == {"PublicationType": "Journal Article"}
    assert citation["CoiStatement"] == {"b": "None"}
    assert citation["Empty"] == {}


def test_the_publications_of_the_run_without_metadata_are_populated(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO runs (type, name) VALUES ('vh', '99') RETURNING id")
        (run_id,) = cur.fetchone()
    conn.commit()
    associate(
        conn,
        run_id,
        "q",
        date(2026, 1, 1),
        date(2026, 1, 1),
        search=lambda q, a, b: [990000001, 990000002],
    )
    report = populate(conn, run_id, fetch=lambda pmids: XML)
    assert "2 publications without metadata" in report
    assert "1 populated" in report
    assert "not returned by PubMed, left unpopulated: [990000002]" in report
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pmid, populated, metadata IS NOT NULL FROM publications "
            "WHERE pmid IN (990000001, 990000002) ORDER BY pmid"
        )
        assert cur.fetchall() == [(990000001, True, True), (990000002, False, False)]


def test_the_pending_publications_are_printed_as_plain_text(conn):
    test_the_publications_of_the_run_without_metadata_are_populated(conn)
    (run_id,) = conn.execute("SELECT id FROM runs WHERE name = '99'").fetchone()
    with conn.cursor() as cur:
        text = abstracts(cur, run_id, 0, 1)
    assert text == "\n".join(
        [
            "PMID 990000001",
            "Types: Journal Article",
            "Title: Nsp1\u03b1 binds in vitro.",
            "Abstract: K A < 25 \u03bcM Second.",
        ]
    )
