from __future__ import annotations

import gzip
import json

import pytest

from rdp.config import CONFIG_DIR
from rdp.reference.corpus import load_corpus
from rdp.reference.corridor import (
    load_corridor,
    resolve_corridor,
    search_candidates,
)

# Synthetic CORPUS rows (fake codes) in the source file's format: blanks are " ".
CORPUS = {
    "TIPLOCDATA": [
        {
            "NLC": 1,
            "STANOX": "99001",
            "TIPLOC": "AAAA",
            "3ALPHA": "AAA",
            "UIC": " ",
            "NLCDESC": "ALPHA",
            "NLCDESC16": " ",
        },
        {
            "NLC": 2,
            "STANOX": "99002",
            "TIPLOC": "AAAASDG",
            "3ALPHA": "AAA",
            "UIC": " ",
            "NLCDESC": "ALPHA SIDINGS",
            "NLCDESC16": " ",
        },
        {
            "NLC": 3,
            "STANOX": "99003",
            "TIPLOC": "BBJN",
            "3ALPHA": " ",
            "UIC": " ",
            "NLCDESC": "BRAVO JN",
            "NLCDESC16": "BRAVO JUNCTION",
        },
        {
            "NLC": 4,
            "STANOX": " ",
            "TIPLOC": "CCCC",
            "3ALPHA": "CCC",
            "UIC": " ",
            "NLCDESC": "CHARLIE",
            "NLCDESC16": " ",
        },
    ]
}

YAML = """
version: 1
nodes:
  - {id: A, name: Alpha, role: station, crs: AAA, exclude_tiplocs: [AAAASDG]}
  - {id: B, name: Bravo Junction, role: junction, search: [BRAVO]}
  - {id: B2, name: Bravo manual, role: junction, tiplocs: [BBJN, NOPE]}
  - {id: C, name: Charlie, role: station, crs: CCC}
main_line: [A, B, C]
branches:
  spur: [B2, B]
"""


@pytest.fixture
def corpus(tmp_path):
    path = tmp_path / "corpus.json.gz"
    path.write_bytes(gzip.compress(json.dumps(CORPUS).encode()))
    return load_corpus(path)


@pytest.fixture
def corridor(tmp_path):
    path = tmp_path / "corridor.yaml"
    path.write_text(YAML, encoding="utf-8")
    return load_corridor(path)


def test_load_corpus_normalises_blanks(corpus):
    assert corpus.loc[corpus.tiploc == "BBJN", "crs"].item() is None
    assert corpus.loc[corpus.tiploc == "CCCC", "stanox"].item() is None
    assert set(corpus.columns) >= {"tiploc", "stanox", "crs", "desc", "desc16"}


def test_resolve(corridor, corpus):
    res = resolve_corridor(corridor, corpus)
    nodes = {n["id"]: n for n in res["nodes"]}
    assert [c["tiploc"] for c in nodes["A"]["codes"]] == ["AAAA"]  # sidings excluded
    assert nodes["B"]["codes"] == []
    assert [c["how"] for c in nodes["B2"]["codes"]] == ["manual"]
    assert res["unresolved"] == ["B"]
    assert "B2: TIPLOC NOPE not in CORPUS" in res["problems"]
    assert "C: TIPLOC CCCC has no STANOX" in res["problems"]
    assert res["stanox"] == ["99001", "99003"]
    assert res["tiploc"] == ["AAAA", "BBJN", "CCCC"]


def test_search_candidates(corpus):
    assert list(search_candidates(corpus, ["bravo"]).tiploc) == ["BBJN"]
    assert len(search_candidates(corpus, [])) == 0


def test_bad_corridor_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "nodes:\n  - {id: A, name: A, role: station}\nmain_line: [A, Z]\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unknown node Z"):
        load_corridor(path)


def test_real_corridor_config_is_valid():
    corridor = load_corridor(CONFIG_DIR / "corridor.yaml")
    assert corridor.main_line[0] == "RDG" and corridor.main_line[-1] == "PAD"
    assert "AIRPORT_JN" in corridor.main_line
    assert corridor.branches["heathrow"] == ["HXX", "AIRPORT_JN"]
