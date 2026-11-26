"""Corridor definition (config/corridor.yaml) and resolution against CORPUS.

Stations are resolved automatically by CRS code (all TIPLOCs sharing it).
Junctions and other non-station locations must have their TIPLOCs listed by
hand in the YAML after reviewing the candidates printed by ``resolve``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROLES = frozenset({"station", "junction", "entry", "exit"})


@dataclass
class Node:
    id: str
    name: str
    role: str
    crs: str | None = None
    tiplocs: list[str] = field(default_factory=list)
    exclude_tiplocs: list[str] = field(default_factory=list)
    search: list[str] = field(default_factory=list)
    notes: str | None = None


@dataclass
class Corridor:
    nodes: dict[str, Node]
    main_line: list[str]
    branches: dict[str, list[str]]


def load_corridor(path: Path) -> Corridor:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    nodes: dict[str, Node] = {}
    for raw in spec["nodes"]:
        node = Node(
            id=raw["id"],
            name=raw["name"],
            role=raw["role"],
            crs=raw.get("crs"),
            tiplocs=list(raw.get("tiplocs") or []),
            exclude_tiplocs=list(raw.get("exclude_tiplocs") or []),
            search=list(raw.get("search") or []),
            notes=raw.get("notes"),
        )
        if node.role not in ROLES:
            raise ValueError(f"node {node.id}: unknown role {node.role!r}")
        if node.id in nodes:
            raise ValueError(f"duplicate node id {node.id}")
        nodes[node.id] = node
    corridor = Corridor(
        nodes=nodes,
        main_line=list(spec["main_line"]),
        branches={k: list(v) for k, v in (spec.get("branches") or {}).items()},
    )
    for seq_name, seq in [("main_line", corridor.main_line), *corridor.branches.items()]:
        for node_id in seq:
            if node_id not in nodes:
                raise ValueError(f"{seq_name}: unknown node {node_id}")
    return corridor


def resolve_corridor(corridor: Corridor, corpus: pd.DataFrame) -> dict[str, Any]:
    """Map every node to TIPLOC/STANOX rows. Returns a JSON-serialisable dict."""
    by_tiploc = corpus.dropna(subset=["tiploc"]).drop_duplicates("tiploc").set_index("tiploc")
    resolved_nodes = []
    unresolved = []
    problems = []
    for node in corridor.nodes.values():
        entries: dict[str, dict[str, Any]] = {}
        if node.crs:
            for row in corpus[corpus["crs"] == node.crs].itertuples():
                if row.tiploc and row.tiploc not in node.exclude_tiplocs:
                    entries[row.tiploc] = {"how": "crs"}
        for tiploc in node.tiplocs:
            if tiploc not in by_tiploc.index:
                problems.append(f"{node.id}: TIPLOC {tiploc} not in CORPUS")
                continue
            entries.setdefault(tiploc, {"how": "manual"})
        rows = []
        for tiploc, info in sorted(entries.items()):
            ref = by_tiploc.loc[tiploc]
            rows.append(
                {
                    "tiploc": tiploc,
                    "stanox": ref["stanox"],
                    "crs": ref["crs"],
                    "desc": ref["desc"],
                    "how": info["how"],
                }
            )
            if ref["stanox"] is None:
                problems.append(f"{node.id}: TIPLOC {tiploc} has no STANOX")
        if not rows:
            unresolved.append(node.id)
        resolved_nodes.append({"id": node.id, "name": node.name, "role": node.role, "codes": rows})

    stanox = sorted({r["stanox"] for n in resolved_nodes for r in n["codes"] if r["stanox"]})
    tiplocs = sorted({r["tiploc"] for n in resolved_nodes for r in n["codes"]})
    return {
        "nodes": resolved_nodes,
        "stanox": stanox,
        "tiploc": tiplocs,
        "unresolved": unresolved,
        "problems": problems,
    }


def search_candidates(corpus: pd.DataFrame, terms: list[str], limit: int = 20) -> pd.DataFrame:
    """CORPUS rows whose description contains any of ``terms`` (case-insensitive)."""
    if not terms:
        return corpus.iloc[0:0]
    desc = corpus["desc"].fillna("") + " | " + corpus["desc16"].fillna("")
    mask = pd.Series(False, index=corpus.index)
    for term in terms:
        mask |= desc.str.contains(term, case=False, regex=False)
    return corpus[mask].head(limit)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
