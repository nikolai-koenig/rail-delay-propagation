# Feed collector

TRUST has no public historical archive (see [data-sources.md](data-sources.md)). The freight data for Phase 2 is therefore only as long as this collector has been running. It is built to run unattended.

## Topology

| Host | Source | Feeds | Role |
|---|---|---|---|
| Oracle VPS | Rail Data Marketplace Kafka | TRUST, Darwin Push Port | primary |
| Raspberry Pi | Network Rail Open Data STOMP | TRUST | backup |

The two TRUST collectors use **different sources** for three reasons:

- An RDM Kafka product issues one consumer group. Two consumers in the same group would *split* the stream rather than each receive a full copy.
- It avoids one account connecting from two places.
- An outage of either platform is covered by the other.

`rdp compact` merges both captures and de-duplicates them. It also reports how many messages only one collector saw, which measures each collector's gaps.

## Guarantees and their limits

- **Write before acknowledge.** STOMP frames are acknowledged (client-individual) and Kafka offsets committed only after the data is flushed and fsync'd to disk. A crash causes duplicates, not loss. Duplicates are removed at compaction by hashing each message's canonical JSON.
- **Durable STOMP subscription.** The broker keeps messages while the Pi is briefly disconnected. How long it keeps them is set by Network Rail and is not guaranteed.
- **Gaps are logged.** `data/local/collector/events_*.jsonl` records every restart (with the previous run's last-message time) and every silence longer than `--gap-threshold` (default 300 s). These logs feed the "data coverage" section of the write-up.
- **Not guaranteed:** feed uptime (Network Rail makes no availability promise), or completeness of TRUST itself (e.g. missed automatic reports).

## On-disk layout (`RDP_DATA_DIR`, default `data/local/`, gitignored)

```
raw/<feed>/YYYY/MM/DD/<feed>_YYYYMMDDTHH_<host>-<source>.jsonl[.gz]   hourly, UTC
collector/status_<feed>_<host>-<source>.json                          live counters
collector/events_<feed>_<host>-<source>.jsonl                         restarts, gaps
processed/trust/date=YYYY-MM-DD/part-0.parquet + summary.json          after compaction
```

Each raw line is an envelope: `recv_ts`, `host`, `source`, `feed`, `topic`, `meta` (message id or Kafka partition/offset), and either `msg` (parsed TRUST message) or `raw` (Darwin payload, or anything that failed to parse, with `parse_error`).

## Filtering and disk budget

- Collectors start with `--filter all`. The first 24–48 hours measure real volume per feed: compressed bytes per day, from `du` on `raw/`.
- After that we decide whether to switch to `--filter corridor`. That filter keeps TRUST messages mentioning a corridor STANOX (including `next_report_stanox`, so trains about to enter are kept) plus all activations, and keeps Darwin payloads mentioning a corridor TIPLOC.
- `rdp health` flags low disk (default under 2 GB free).
- The corridor filter needs `config/corridor_codes.json` from `rdp corridor resolve`, which needs CORPUS.

## Deployment (Pi or VPS, Linux, ARM64 or x86-64)

```bash
# 1. uv and the code
curl -LsSf https://astral.sh/uv/install.sh | sh     # or your package manager
git clone https://github.com/<you>/rail-delay-propagation.git ~/rail-delay-propagation
cd ~/rail-delay-propagation
uv sync --locked --no-dev

# 2. credentials
cp .env.example .env && chmod 600 .env && $EDITOR .env    # set RDP_HOST_TAG=pi or vps

# 3. try it in the foreground first (Ctrl+C to stop)
.venv/bin/rdp collect --source nr-stomp --feed trust     # Pi
.venv/bin/rdp collect --source rdm-kafka --feed trust    # VPS

# 4. install as user services that survive logout and reboot
mkdir -p ~/.config/systemd/user
cp deploy/systemd/rdp-trust-stomp.service deploy/systemd/rdp-health.* ~/.config/systemd/user/   # Pi
cp deploy/systemd/rdp-trust-kafka.service deploy/systemd/rdp-darwin-kafka.service \
   deploy/systemd/rdp-health.* ~/.config/systemd/user/                                       # VPS
systemctl --user daemon-reload
systemctl --user enable --now rdp-trust-stomp.service rdp-health.timer   # Pi (adjust names on VPS)
sudo loginctl enable-linger "$USER"

# 5. check
systemctl --user status 'rdp-*'
journalctl --user -u rdp-trust-stomp -f
.venv/bin/rdp health
```

### Host notes

- **Oracle Always Free:** Oracle may reclaim instances it considers idle (95th-percentile CPU under 20% over 7 days, per the [docs](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm)). A collector looks idle. Upgrading the account to Pay As You Go is widely reported to prevent this, but that isn't confirmed officially. The Pi backup and the health ping are the real mitigations.
- **Raspberry Pi:** prefer an SSD or high-endurance SD card. Hourly files with fsync per batch are gentle, but SD cards do wear out.
- **Health alerts:** set `HEALTHCHECK_URL` to a dead-man's-switch service of your choice. `rdp health` pings it only when every collector is fresh, so missed pings mean trouble.

## Merging captures from both hosts

Copy the Pi's `raw/` tree into the VPS's (or both into one workstation) with `rsync -a`. Filenames include host and source, so nothing collides. Then:

```bash
.venv/bin/rdp compact trust --date 2026-11-27
```

## First-connection checklist (unverified details)

- [ ] Network Rail STOMP host/port (`publicdatafeeds.networkrail.co.uk:61618`) and durable subscription headers accepted.
- [ ] RDM TRUST Kafka message format: is each Kafka message one JSON array (like STOMP) or one message? The handler accepts both; confirm in the raw files.
- [ ] RDM Darwin topic format (JSON wrapper vs XML). Stored raw either way.
- [ ] CORPUS download URL works with Network Rail credentials.
- [ ] Measured compressed volume per feed per day → decide on filtering.
