"""CORPUS (Codes for Operations, Retail & Planning - a Unified Solution).

CORPUS maps each location's TIPLOC, STANOX, CRS (3-alpha), NLC and
description. Two source formats are supported:

- Network Rail Open Data JSON (``CORPUSExtract.json.gz``): ``{"TIPLOCDATA": [...]}``,
  missing values encoded as a single space.
- Rail Data Marketplace weekly XML (``NLCYYYYMMDD.xml.gz``): one ``TSDBDataItem``
  per location with ``NLC*`` child elements; missing values are a space or an
  absent element.
"""

from __future__ import annotations

import gzip
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)

# From community documentation; verify on first use (see docs/data-sources.md).
CORPUS_URL = (
    "https://publicdatafeeds.networkrail.co.uk/ntrod/SupportingFileAuthenticate?type=CORPUS"
)

COLUMN_MAP = {
    "TIPLOC": "tiploc",
    "STANOX": "stanox",
    "3ALPHA": "crs",
    "NLC": "nlc",
    "UIC": "uic",
    "NLCDESC": "desc",
    "NLCDESC16": "desc16",
}

# RDM XML element (local name) -> output column. The XML has no UIC field.
XML_COLUMN_MAP = {
    "NLCTiplocCode": "tiploc",
    "NLCStanoxCode": "stanox",
    "NLCCrsCode": "crs",
    "NLCLocationCode": "nlc",
    "NLCDescription": "desc",
    "NLCCapriDesc": "desc16",
}
COLUMNS = list(COLUMN_MAP.values())


def download_corpus(dest: Path, username: str, password: str, timeout_s: float = 120.0) -> Path:
    """Download CORPUS to ``dest`` (bytes as served, normally gzipped JSON)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(
        CORPUS_URL, auth=(username, password), timeout=timeout_s, stream=True
    ) as resp:
        resp.raise_for_status()
        tmp = dest.with_name(dest.name + ".tmp")
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
    tmp.replace(dest)
    log.info("downloaded CORPUS to %s (%d bytes)", dest, dest.stat().st_size)
    return dest


def _read_bytes(path: Path) -> bytes:
    data = Path(path).read_bytes()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def load_corpus(path: Path) -> pd.DataFrame:
    """Load CORPUS (JSON or RDM XML, optionally gzipped) into a normalised frame."""
    data = _read_bytes(path)
    if data.lstrip()[:1] == b"<":
        cleaned = _parse_xml(data)
    else:
        raw = json.loads(data)
        records = raw["TIPLOCDATA"] if isinstance(raw, dict) else raw
        cleaned = [
            {dst: _clean(rec.get(src)) for src, dst in COLUMN_MAP.items()} for rec in records
        ]
    # object dtype keeps missing values as None (pandas' string dtype would use NaN).
    return pd.DataFrame(cleaned, columns=COLUMNS, dtype=object)


def _parse_xml(data: bytes) -> list[dict[str, str | None]]:
    root = ET.fromstring(data)
    rows = []
    for item in root.iter():
        if _local(item.tag) != "TSDBDataItem":
            continue
        fields = {_local(child.tag): child.text for child in item}
        row: dict[str, str | None] = dict.fromkeys(COLUMNS)
        for src, dst in XML_COLUMN_MAP.items():
            row[dst] = _clean(fields.get(src))
        rows.append(row)
    if not rows:
        raise ValueError("no TSDBDataItem records found in CORPUS XML")
    return rows


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find_latest_corpus(directory: Path) -> Path | None:
    """Newest CORPUS file in ``directory``.

    RDM files are named ``NLCYYYYMMDD.xml[.gz]``, so the lexically last name is
    the newest. Falls back to the Network Rail JSON extract.
    """
    xml_files = sorted(Path(directory).glob("NLC[0-9]*.xml*"))
    if xml_files:
        return xml_files[-1]
    json_file = Path(directory) / "CORPUSExtract.json.gz"
    return json_file if json_file.exists() else None


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
