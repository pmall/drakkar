"""The read views: what a decision needs, from the test database."""

import subprocess
import sys
from pathlib import Path

from database.read import (
    Page,
    _rank,
    closest,
    entries,
    entry,
    methods,
    names,
    search,
    seq,
    sequence_of,
    taxa,
)


def _script(*args: str) -> subprocess.CompletedProcess[str]:
    """The read script, run with this Python."""
    script = Path(__file__).parents[1] / "scripts" / "read.py"
    return subprocess.run([sys.executable, script, *args], capture_output=True, text=True)


def test_methods(conn):
    """By name or synonym, case aside, many texts at once, with the detection flag; the closest
    names first, a list cut at its limit ending with how many there are; the terms holding a
    word of the text, punctuation aside, the most words first."""
    lines = methods(conn.cursor(), ["coimmuno", "Co-IP", "western blot"]).splitlines()
    assert lines[0] == "#text\tpsimi_id\tname (synonym matched)\tis_detection\tlive_descriptions"
    assert "coimmuno\tMI:0019\tcoimmunoprecipitation\tyes\t3" in lines
    assert "Co-IP\tMI:0019\tcoimmunoprecipitation (Co-IP)\tyes\t3" in lines
    assert "western blot\tMI:0113\twestern blot\tno\t0" in lines
    first = methods(conn.cursor(), ["two hybrid"], Page(3)).splitlines()
    assert first[1] == "two hybrid\tMI:0018\ttwo hybrid\tyes\t90"  # the exact name first
    assert len(first) == 1 + 3 + 1
    assert first[-1] == "two hybrid\t… 3 of 27 shown, cut by --limit 3"
    words = methods(conn.cursor(), ["biolayer interferometry", "pulldown"]).splitlines()
    assert words[1:] == [
        "biolayer interferometry\tMI:0969\tbio-layer interferometry\tyes\t0",
        "pulldown\tMI:0096\tpull down\tyes\t10",
    ]
    extra = methods(conn.cursor(), ["GST pull-down"]).splitlines()  # a word PSI-MI lacks
    assert extra[1] == "GST pull-down\tMI:0096\tpull down\tyes\t10"


def test_rank():
    """A name that is the text, then one that starts with it as a word, holds it as a word, holds
    it inside a word."""
    assert _rank("con1", ["Con1"]) == 0
    assert _rank("con1", ["Con1 virus"]) == 1
    assert _rank("con1", ["Hepatitis C virus (isolate Con1)"]) == 2
    assert _rank("con1", ["Vibrio sp. con10", "clone pCON11"]) == 3
    assert _rank("con1", ["JFH-1"]) == 4


def test_taxon(conn):
    """By any of its names, case aside, with the taxa above it up to its family; only the taxa
    that hold a current entry."""
    lines = taxa(conn.cursor(), ["cuhk", "Rabies"]).splitlines()
    assert lines[0] == "#text\ttaxon (name matched)\trank\tlineage"
    assert lines[1].startswith(
        "cuhk\t239241 SARS coronavirus CUHK-AG01\tno rank\t"
        "694009 Severe acute respiratory syndrome-related coronavirus < "
    )
    assert lines[1].endswith(" < 11118 Coronaviridae")
    assert (
        "Rabies\t11292 Lyssavirus rabies\tspecies\t"
        "11286 Lyssavirus < 2842407 Alpharhabdovirinae < 11270 Rhabdoviridae"
    ) in lines
    assert taxa(conn.cursor(), ["TW-HP2"]).splitlines()[1] == "TW-HP2\t(none)"  # no entry


def test_entry(conn):
    """Its lineage with the IDs, its chains and regions, the generic names on its current snapshot;
    many at once, a secondary accession followed."""
    text = entry(conn.cursor(), "P26662")
    assert "- 810-1026 chain: Protease NS2" in text
    assert "- 2-75 region: Disordered" in text
    assert "- 1027-1208 domain: Peptidase S29" in text
    assert "viral, taxon 11116 Hepatitis C virus (isolate Japanese) < 31647 " in text
    assert (
        "< 3052230 Orthohepacivirus hominis < 11102 Orthohepacivirus < 3700683 Hepaciviridae\n"
        in text
    )
    assert "\nGeneric names (live descriptions):\n- 810-1026 NS2-3 (" in text
    assert "Generic names" not in entry(conn.cursor(), "Q14258")  # human
    assert "obsolete" not in text  # the current snapshot only
    secondary = entry(conn.cursor(), "O00297")
    assert secondary.startswith("# O00297 is a secondary accession of O00499\n# O00499: ")
    assert entry(conn.cursor(), "o00499-2").startswith("# o00499-2 is an isoform of O00499\n")
    obsolete = entry(conn.cursor(), "Q6SRE2")  # obsolete snapshots only: never shown
    assert obsolete == "# Q6SRE2: no current entry has this accession, current or old"
    both = entries(conn.cursor(), ["P26662;", "X1", "Q9Y6K9"])
    assert both.startswith("# P26662: ")
    assert both.endswith(
        "\n\n# X1: not an accession"
        "\n\n# Q9Y6K9: no current entry has this accession, current or old"
    )


def test_search(conn):
    """By the `search` text, case aside, several texts, Swiss-Prot first; under a taxon, its
    whole subtree."""
    lines = search(conn.cursor(), ["brf1", "nothing such"]).splitlines()
    assert lines == [
        "#text\taccession\tdb\tgene\tprotein\ttaxon\tlength",
        "brf1\tQ92994\tSP\tBRF1\tTranscription factor IIIB 90 kDa subunit\t9606 Homo sapiens\t677",
        "nothing such\t(none)",
    ]
    dbs = [line.split("\t")[2] for line in search(conn.cursor(), ["protein"]).splitlines()[1:-1]]
    assert dbs == sorted(dbs)  # Swiss-Prot first
    under = search(conn.cursor(), ["Uncharacterized"], taxon=694009, page=Page(3)).splitlines()
    assert (
        "Uncharacterized\tQ6VA95\tTR\tN/A\tUncharacterized protein\t"
        "239241 SARS coronavirus CUHK-AG01\t63"
    ) in under
    assert under[-1] == "Uncharacterized\t… 3 of 5 shown, cut by --limit 3"
    assert search(conn.cursor(), ["brf1"], taxon=694009).splitlines()[1] == "brf1\t(none)"


def test_search_accessions_as_written(conn):
    """An accession as publications write it gives its current entry: a group one by one, an
    isoform's, a version, an old accession, case aside; an accession of no entry, none."""
    texts = ["o00297; Q92994", "O00499-2", "Q92994.1", "Q9Y6K9"]
    found = [line.split("\t")[:2] for line in search(conn.cursor(), texts).splitlines()[1:]]
    assert found == [
        ["o00297", "O00499"],
        ["Q92994", "Q92994"],
        ["O00499-2", "O00499"],
        ["Q92994.1", "Q92994"],
        ["Q9Y6K9", "(none)"],
    ]


SARS = "694009 Severe acute respiratory syndrome-related coronavirus"


def test_closest(conn):
    """The entries of the taxon subtree by the score of their best isoform, Swiss-Prot first
    among equals, as `search` shows them; every entry counted; an accession refused."""
    query = sequence_of(conn.cursor(), "P0C6X7:1-20")
    lines = closest(conn.cursor(), query, 694009, Page(3)).splitlines()
    assert lines == [
        "#accession\tdb\tgene\tprotein\ttaxon\tlength\tidentity\tcoverage\tregion",
        f"P0C6U8\tSP\t1a\tReplicase polyprotein 1a\t{SARS}\t4382\t100.0 %\t100.0 %\t1-20",
        f"P0C6X7\tSP\trep\tReplicase polyprotein 1ab\t{SARS}\t7073\t100.0 %\t100.0 %\t1-20",
        "P0C6W6\tSP\trep\tReplicase polyprotein 1ab\t349344 Bat SARS CoV Rp3/2004\t7071"
        "\t95.0 %\t100.0 %\t1-20",
        "… 3 of 18 shown, cut by --limit 3",
    ]
    assert closest(conn.cursor(), "X1", 694009) == "an accession: closest takes a sequence"
    assert closest(conn.cursor(), "NS-protease", 694009) == "not an amino acid sequence"
    assert (
        closest(conn.cursor(), "MESLVLGVNE\n", 694009)
        == "leading or trailing whitespace around the argument"
    )
    assert (
        closest(conn.cursor(), "MESLVLGVNE KTHVQLSLPV", 694009)
        == "2 parts separated by whitespace: one sequence per argument"
    )


def test_closest_searches_the_first_sequence(dbname):
    """More sequences: the first one's list, then a warning that the others are not searched."""
    first = _script("closest", "MESLVLGVNE", "--taxon", "694009", "--limit", "1")
    more = _script("closest", "MESLVLGVNE", "WWWWW", "X1", "--taxon", "694009", "--limit", "1")
    assert more.stdout == (
        first.stdout + "warning: 2 more sequences not searched: closest searches the first only\n"
    )


def test_closest_identity_counts_the_gaps(conn):
    """A residue deleted from the query: one gap column among the aligned columns."""
    query = sequence_of(conn.cursor(), "P0C6X7:1-41")
    gapped = query[:20] + query[21:]  # 40 residues, 41 columns
    line = closest(conn.cursor(), gapped, 694009, Page(1)).splitlines()[1]
    fields = line.split("\t")
    assert [fields[0], *fields[-3:]] == ["P0C6U8", "97.6 %", "100.0 %", "1-41"]


def test_seq(conn):
    lines = seq(conn.cursor(), ["P0C6X7:1-20", "Q6VA95", "P0C6X7:8000-8001"]).splitlines()
    assert lines[0] == "#location\tsequence"
    assert lines[1] == "P0C6X7:1-20\tMESLVLGVNEKTHVQLSLPV"
    assert lines[2].startswith("Q6VA95\tMFHLVDFQVT") and len(lines[2].split("\t")[1]) == 63
    assert lines[3] == "P0C6X7:8000-8001\t8000-8001 is not a stretch of 1-7073"
    written = seq(conn.cursor(), ["p0c6x7.2:1-5", "O00297:1-5", "Q9Y6K9"]).splitlines()
    assert written[1:] == [  # an accession as written, on its current entry
        "p0c6x7.2:1-5\tMESLV",
        f"O00297:1-5\t{sequence_of(conn.cursor(), 'O00499:1-5')}",
        "Q9Y6K9\tno current entry has Q9Y6K9, current or old",
    ]


def test_names(conn):
    """Under each taxon, its whole subtree: the most used names first, with their three most
    used interactors, on current snapshots only; never cut."""
    lines = names(conn.cursor(), [239241, 694009]).splitlines()
    assert lines[:4] == [
        "#taxon\tgeneric_name\tlive_descriptions\tinteractors (live descriptions)",
        "239241\torf3b\t3\tQ6VA98:1-154 (3)",
        "239241\tN\t2\tQ6VA95:1-63 (2)",
        "239241\torf7a\t2\tQ6VA94:1-122 (2)",
    ]
    sars = [line for line in lines if line.startswith("694009\t")]
    assert sars[:3] == [
        "694009\tnsp3\t19\tP0C6U8:819-2740 (8), P0C6X7:819-2740 (5), D3W8N4:1-1922 (4), 1 more",
        "694009\tN\t13\tP59595:1-422 (7), Q3I5I7:1-421 (4), Q6VA95:1-63 (2)",
        "694009\tnsp12\t11\tP0C6X7:4370-5301 (11)",
    ]
    assert len(sars) == 19 and not any("shown, cut" in line for line in lines)
    every = names(conn.cursor(), [3418604]).splitlines()
    assert not any("Q6SRE2" in line for line in every)  # an obsolete snapshot: left out


def test_a_taxon_is_given_by_its_id(dbname):
    result = _script("names", "SARS coronavirus CUHK-AG01")
    assert result.returncode == 2 and "invalid int value" in result.stderr


def test_an_unknown_option_is_ignored(dbname):
    result = _script("names", "239241", "--limit", "5")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == _script("names", "239241").stdout


def test_sql_is_guarded(dbname):
    """Every row and every cell whole; past 10 kB of output, the rest left out with a line that
    says so; a write refused."""
    result = _script("sql", "SELECT accession, sequences FROM proteins ORDER BY id LIMIT 2")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "#accession\tsequences" and len(lines) == 1 + 2
    assert max(len(line) for line in lines) > 300  # a sequence, not cut
    lines = _script("sql", "SELECT generate_series(1, 1000) AS n").stdout.splitlines()
    assert len(lines) == 1 + 1000 and lines[-1] == "1000"
    query = "SELECT repeat('x', 1000) AS x FROM generate_series(1, 20)"
    lines = _script("sql", query).stdout.splitlines()
    assert lines[-1] == "… cut at 10 kB: select fewer columns or rows"
    assert sum(len(line) + 1 for line in lines[:-1]) <= 10_000 and len(lines) - 2 == 9
    result = _script("sql", "UPDATE methods SET name = 'x' WHERE psimi_id = 'MI:0018'")
    assert "read-only transaction" in result.stdout
