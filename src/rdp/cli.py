"""Command-line interface: ``rdp <command> ...``."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import date
from pathlib import Path

from rdp import config

log = logging.getLogger("rdp")

DEFAULT_CORPUS = Path("reference") / "CORPUSExtract.json.gz"
CORRIDOR_YAML = config.CONFIG_DIR / "corridor.yaml"
CORRIDOR_CODES = config.CONFIG_DIR / "corridor_codes.json"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("stomp").setLevel(logging.WARNING)


# --- reference ---------------------------------------------------------------


def cmd_download_corpus(args: argparse.Namespace) -> int:
    from rdp.reference.corpus import download_corpus

    dest = args.dest or config.data_dir() / DEFAULT_CORPUS
    download_corpus(
        dest,
        config.env("NR_USERNAME", required=True),
        config.env("NR_PASSWORD", required=True),
    )
    print(dest)
    return 0


def cmd_corridor_resolve(args: argparse.Namespace) -> int:
    from rdp.reference.corpus import find_latest_corpus, load_corpus
    from rdp.reference.corridor import (
        file_sha256,
        load_corridor,
        resolve_corridor,
        search_candidates,
    )

    corpus_path = args.corpus or find_latest_corpus(config.data_dir() / "reference")
    if corpus_path is None or not corpus_path.exists():
        print(
            "CORPUS not found. Download NLCYYYYMMDD.xml.gz from the RDM CORPUS product "
            "into data/local/reference/, or pass --corpus PATH."
        )
        return 2
    log.info("using CORPUS %s", corpus_path)
    corpus = load_corpus(corpus_path)
    corridor = load_corridor(args.config)
    result = resolve_corridor(corridor, corpus)

    for node in result["nodes"]:
        codes = ", ".join(f"{c['tiploc']}/{c['stanox']}({c['how']})" for c in node["codes"])
        print(f"{node['id']:<18} {node['role']:<9} {codes or '-- UNRESOLVED --'}")
    for problem in result["problems"]:
        print(f"PROBLEM: {problem}")
    for node_id in result["unresolved"]:
        node = corridor.nodes[node_id]
        cands = search_candidates(corpus, node.search or [node.name])
        print(f"\nCandidates for {node_id} (search {node.search or [node.name]}):")
        print(cands.to_string(index=False) if len(cands) else "  none")

    result["provenance"] = {
        "corpus_file": corpus_path.name,
        "corpus_sha256": file_sha256(corpus_path),
        "corridor_config": args.config.name,
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"\nWrote {args.out} ({len(result['stanox'])} STANOX, {len(result['tiploc'])} TIPLOC, "
        f"{len(result['unresolved'])} unresolved)"
    )
    return 0


# --- collect -----------------------------------------------------------------


def _load_codes() -> dict:
    if not CORRIDOR_CODES.exists():
        raise SystemExit(
            f"{CORRIDOR_CODES} missing; run `rdp corridor resolve` or use --filter all"
        )
    codes = json.loads(CORRIDOR_CODES.read_text(encoding="utf-8"))
    if codes.get("unresolved"):
        log.warning("corridor has unresolved nodes: %s", ", ".join(codes["unresolved"]))
    return codes


def cmd_collect(args: argparse.Namespace) -> int:
    from rdp.collector.filters import TokenFilter, TrustFilter
    from rdp.collector.run import run_collector

    trust_filter = token_filter = None
    if args.filter == "corridor":
        codes = _load_codes()
        trust_filter = TrustFilter(codes["stanox"])
        token_filter = TokenFilter(codes["tiploc"])

    host = config.host_tag()
    env = config.env

    if args.source == "nr-stomp":
        if args.feed != "trust":
            raise SystemExit("nr-stomp source only supports --feed trust")
        from rdp.collector.sources.stomp_source import StompConfig, run_stomp

        username = env("NR_USERNAME", required=True)
        stomp_cfg = StompConfig(
            host=env("NR_STOMP_HOST", "publicdatafeeds.networkrail.co.uk"),
            port=int(env("NR_STOMP_PORT", "61618")),
            username=username,
            password=env("NR_PASSWORD", required=True),
            client_id=env("NR_CLIENT_ID") or f"{username}-{host}",
        )

        def start(handler, flush, stop):
            run_stomp(stomp_cfg, handler, flush, stop)

    else:
        from rdp.collector.sources.kafka_source import KafkaConfig, run_kafka

        prefix = f"RDM_{args.feed.upper()}_"
        kafka_cfg = KafkaConfig(
            bootstrap=env("RDM_BOOTSTRAP", required=True),
            topic=env(prefix + "TOPIC", required=True),
            username=env(prefix + "USERNAME", required=True),
            password=env(prefix + "PASSWORD", required=True),
            group_id=env(prefix + "GROUP", required=True),
        )

        def start(handler, flush, stop):
            run_kafka(kafka_cfg, handler, flush, stop)

    run_collector(
        feed=args.feed,
        source=args.source,
        host=host,
        data_root=config.data_dir(),
        start_source=start,
        trust_filter=trust_filter,
        token_filter=token_filter,
        gap_threshold_s=args.gap_threshold,
    )
    return 0


# --- compact / health --------------------------------------------------------


def cmd_compact(args: argparse.Namespace) -> int:
    from rdp.collector.compact import compact_trust_day

    root = config.data_dir()
    summary = compact_trust_day(
        root / "raw", root / "processed", args.date, include_open=args.include_open
    )
    print(json.dumps(summary, indent=2))
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    from rdp.collector.health import check_status_files, ping

    root = config.data_dir()
    paths = sorted((root / "collector").glob("status_*.json"))
    problems = check_status_files(paths, max_age_s=args.max_age)
    if root.exists():
        free_gb = shutil.disk_usage(root).free / 1e9
        if free_gb < args.min_free_gb:
            problems.append(f"low disk: {free_gb:.1f} GB free under {root}")
    if problems:
        for p in problems:
            print(f"UNHEALTHY: {p}")
        return 1
    print(f"healthy: {len(paths)} collector(s)")
    url = config.env("HEALTHCHECK_URL")
    if url and not args.no_ping:
        ping(url)
    return 0


# --- parser ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rdp", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    ref = sub.add_parser("reference", help="reference data").add_subparsers(
        dest="ref_command", required=True
    )
    dl = ref.add_parser("download-corpus", help="download CORPUS from Network Rail")
    dl.add_argument("--dest", type=Path)
    dl.set_defaults(func=cmd_download_corpus)

    cor = sub.add_parser("corridor", help="corridor definition").add_subparsers(
        dest="corridor_command", required=True
    )
    res = cor.add_parser("resolve", help="resolve corridor.yaml against CORPUS")
    res.add_argument("--corpus", type=Path)
    res.add_argument("--config", type=Path, default=CORRIDOR_YAML)
    res.add_argument("--out", type=Path, default=CORRIDOR_CODES)
    res.set_defaults(func=cmd_corridor_resolve)

    col = sub.add_parser("collect", help="run a feed collector until stopped")
    col.add_argument("--source", choices=["nr-stomp", "rdm-kafka"], required=True)
    col.add_argument("--feed", choices=["trust", "darwin"], required=True)
    col.add_argument("--filter", choices=["all", "corridor"], default="all")
    col.add_argument(
        "--gap-threshold", type=float, default=300.0, help="seconds of silence logged as a gap"
    )
    col.set_defaults(func=cmd_collect)

    comp = sub.add_parser("compact", help="merge raw captures into Parquet")
    comp.add_argument("feed", choices=["trust"])
    comp.add_argument("--date", type=date.fromisoformat, required=True, help="UTC day")
    comp.add_argument(
        "--include-open", action="store_true", help="also read the uncompressed current hour"
    )
    comp.set_defaults(func=cmd_compact)

    health = sub.add_parser("health", help="exit non-zero if any collector is stale")
    health.add_argument("--max-age", type=float, default=900.0, help="seconds")
    health.add_argument("--min-free-gb", type=float, default=2.0)
    health.add_argument("--no-ping", action="store_true")
    health.set_defaults(func=cmd_health)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    config.load_env()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
