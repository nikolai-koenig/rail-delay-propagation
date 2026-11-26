"""CORPUS (Codes for Operations, Retail & Planning - a Unified Solution).

CORPUS maps each location's TIPLOC, STANOX, CRS (3-alpha), NLC and
description. Missing values are encoded as a single space in the source file.
"""

from __future__ import annotations

import gzip
import json
import logging
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
    raw = json.loads(_read_bytes(path))
    records = raw["TIPLOCDATA"] if isinstance(raw, dict) else raw
    cleaned = [{dst: _clean(rec.get(src)) for src, dst in COLUMN_MAP.items()} for rec in records]
    # object dtype keeps missing values as None (pandas' string dtype would use NaN).
    return pd.DataFrame(cleaned, columns=list(COLUMN_MAP.values()), dtype=object)


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
