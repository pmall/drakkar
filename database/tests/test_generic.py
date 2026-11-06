"""The generic viral proteins: the files kept in step with the test database."""

from pathlib import Path

import pytest

from database.generic import sync


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("".join(line + "\n" for line in lines))


def _lines(path: Path) -> list[list[str]]:
    return [line.split("\t") for line in path.read_text().splitlines()]


def test_sync(conn, tmp_path):
    """The species get their family and publications; the names of the vh descriptions dataset
    are added, those it no longer has removed; what a person decides is reported."""
    _write(
        tmp_path / "species.tsv",
        [
            "family_ncbi_taxon_id\tncbi_taxon_id\tname\tpublications",
            "\t694009\tSARS-CoV\t0",
            "\t3050299\tEBV\t0",
            "\t3052230\tHCV\t0",
            "\t2697049\tSARS-CoV-2\t0",
            "\t3048459\tZika virus\t0",
        ],
    )
    _write(
        tmp_path / "placed.tsv",
        [
            "ncbi_taxon_id\tspecies_ncbi_taxon_id\tname",
            "64320\t3048459\tZika virus",
            "663565\t694009\tBat SARS Cov Rs806/2006",
        ],
    )
    _write(
        tmp_path / "proteins.tsv",
        [
            "ncbi_taxon_id\tgeneric_name\tprotein\tnote",
            "694009\torf14\torf9c\tSARS-CoV-2's name of ORF14",
            "694009\tgone\tgone\t",
            "694009\tnsp5\tnsp6\t",
            "694009\tnsp6\tnsp7\t",
        ],
    )
    report = sync(conn.cursor(), tmp_path).splitlines()

    # sorted by family, then species; HCV's publications are of two strains, EBV's of
    # descriptions whose human interactor is on an obsolete snapshot
    assert _lines(tmp_path / "species.tsv") == [
        ["family_ncbi_taxon_id", "ncbi_taxon_id", "name", "publications"],
        ["11050", "3048459", "Zika virus", "1"],
        ["11118", "694009", "SARS-CoV", "2"],
        ["11118", "2697049", "SARS-CoV-2", "1"],
        ["3044472", "3050299", "EBV", "1"],
        ["3700683", "3052230", "HCV", "2"],
    ]
    assert _lines(tmp_path / "placed.tsv")[1:] == [  # sorted by species, then taxon
        ["663565", "694009", "Bat SARS Cov Rs806/2006"],
        ["64320", "3048459", "Zika virus"],
    ]
    proteins = _lines(tmp_path / "proteins.tsv")
    assert ["694009", "orf14", "orf9c", "SARS-CoV-2's name of ORF14"] in proteins  # kept
    assert ["694009", "nsp1", "", ""] in proteins  # a new name, to decide
    assert ["3048459", "C", "", ""] in proteins  # through placed.tsv
    assert not [p for p in proteins if p[1] in ("gone", "EBNA3")]  # EBNA3: obsolete human only
    hcv = [p[1] for p in proteins if p[0] == "3052230"]
    assert hcv == ["NS2-3", "NS5A"]
    sars = [p[1] for p in proteins if p[0] == "694009"]
    assert sars == sorted(sars, key=str.casefold)

    assert "removed\t694009 SARS-CoV\tgone\tgone" in report
    # a placed taxon under its species in the taxonomy can go; one outside it is placed
    assert "placed, now under its species in the NCBI taxonomy (its line can go)\t64320" in report
    assert not [line for line in report if line.endswith("\t663565")]
    assert (
        "taxon under no species\t10280 Molluscum contagiosum virus subtype 1 < 10279 Molluscum "
        "contagiosum virus < 3430922 Molluscipoxvirus molluscum < 10278 Molluscipoxvirus < 10241 "
        "Chordopoxvirinae < 10240 Poxviridae\tvFLIP (2)"
    ) in report
    assert "no protein\t694009 SARS-CoV\tnsp1\t9 descriptions" in report
    assert "protein named elsewhere\t694009 SARS-CoV\tnsp5 → nsp6, but nsp6 → nsp7" in report

    # once decided, only the taxa under no species are left
    _write(
        tmp_path / "proteins.tsv",
        ["ncbi_taxon_id\tgeneric_name\tprotein\tnote"]
        + [f"{t}\t{n}\t{n}\t" for t, n, _, _ in proteins[1:]],
    )
    _write(
        tmp_path / "placed.tsv",
        ["ncbi_taxon_id\tspecies_ncbi_taxon_id\tname", "663565\t694009\tBat SARS Cov Rs806/2006"],
    )
    report = sync(conn.cursor(), tmp_path).splitlines()
    decide = report[report.index("To decide:") + 1 :]
    assert decide and all(line.startswith("taxon under no species") for line in decide)
    assert "proteins.tsv: 30 names, 30 proteins; 0 added, 0 removed" in report


def test_header(conn, tmp_path):
    """A file whose header is not its format is refused."""
    _write(tmp_path / "species.tsv", ["ncbi_taxon_id\tname", "694009\tSARS-CoV"])
    with pytest.raises(ValueError, match="the header must be"):
        sync(conn.cursor(), tmp_path)


def test_placed_subtree(conn, tmp_path):
    """A placed taxon places its whole subtree: MHV-A59 and rat coronavirus, under Betacoronavirus
    muris, placed in SARS-CoV."""
    _write(
        tmp_path / "species.tsv",
        ["family_ncbi_taxon_id\tncbi_taxon_id\tname\tpublications", "\t694009\tSARS-CoV\t0"],
    )
    _write(
        tmp_path / "placed.tsv",
        ["ncbi_taxon_id\tspecies_ncbi_taxon_id\tname", "3433759\t694009\tBetacoronavirus muris"],
    )
    sync(conn.cursor(), tmp_path)
    assert ["694009", "HE", "", ""] in _lines(tmp_path / "proteins.tsv")
