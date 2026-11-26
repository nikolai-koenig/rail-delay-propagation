# Project Brief: Rail Delay Propagation on the Great Western Main Line

## Who and why
I'm applying for an ML MSc (starting next year) and building this as a public GitHub portfolio project. It should be rigorous, reproducible and honestly written up, not flashy. Depth and clear methodology matter more than model complexity. I'm based in England and know the UK rail context.

## The project
Model how train delays propagate along the **Great Western Main Line (GWML) between Reading (RDG) and London Paddington (PAD)**, a busy four-track corridor shared by:
- GWR intercity and stopping services
- Elizabeth line services (these continue through central London, not terminating at Paddington)
- Heathrow Express (shares track east of Airport Junction)
- Freight

### Research questions
1. How far does an initial delay travel along the corridor, and how much is absorbed by timetable slack?
2. Does a freight train's presence in a section increase delay on following passenger services, compared with passenger-on-passenger interactions?
3. Do graph-based models predict propagation better than sequence models or gradient boosting?

## Data sources
| Source | Covers | Use |
|---|---|---|
| Darwin **HSP** (Historical Service Performance) via Rail Data Marketplace | Passenger services, up to ~1 year back | Phase 1 + validation |
| Network Rail open data: **TRUST** (train movements) | All services incl. freight, at timing points | Phase 2 |
| Network Rail **SCHEDULE (CIF)** and **CORPUS** | Planned timetable, location code mapping | Both phases |
| Weather (Open-Meteo or Met Office) and UK bank holidays / school terms | Context features | Both phases |

Verification of the assumptions originally listed here is recorded in [docs/data-sources.md](docs/data-sources.md).

## Plan

### Phase 1: Passenger-only (HSP)
1. HSP downloader: resumable, rate-limited, retries with backoff, caches raw responses to disk, logs gaps. Start with ~3 months to prove the pipeline, then extend.
2. Clean dataset (Parquet / DuckDB). Per train per stop: scheduled vs actual times, delay in minutes, planned running time and dwell (slack), headway to previous train, service type, time of day, day of week, weather, bank holiday flag.
3. EDA: delay distributions per station, how delay grows or shrinks along the line.
4. Baselines: persistence, linear regression, LightGBM. Task: given delay at stop k, predict delay at stops k+1 to k+n. Metrics: MAE and share within ±1 minute.
5. Models: temporal GNN (PyTorch Geometric / PyG Temporal, or graph conv over stations + GRU) vs sequence model (LSTM or small transformer).
6. Analysis: ablations (weather, graph edges, history length), SHAP, error analysis (peaks, terminals, disruption), prediction intervals (quantile regression or conformal).

### Phase 2: Mixed traffic (TRUST)
1. **Start the TRUST collector early** so data accumulates while Phase 1 proceeds (subscribe to the feed, write movements to Parquet; designed to run unattended on a Pi or cheap VPS, with reconnect handling).
2. Map TRUST timing points to stations via CORPUS and unify passenger and freight in one data model.
3. Add interaction features: freight in section in last hour, headway to nearest freight train, fast vs slow line.
4. Re-run models and ablations including freight; report sample sizes honestly.

Phase 1 must stand alone as a finished project in case freight data accumulates slowly.

## Engineering conventions
- Python, pandas/DuckDB, scikit-learn, LightGBM, PyTorch + PyTorch Geometric, SHAP, Streamlit (small demo at the end).
- **Split train/test by date, never randomly** (avoid leakage).
- Fixed seeds, pinned dependencies (`pyproject.toml` or `environment.yml`), a `Makefile` with `make data / train / eval`.
- Small, regular commits from day one. Tests for the data pipeline and feature code.
- **Never commit raw data or API keys.** Credentials go in `.env` (gitignored), with a `.env.example`. Publish code plus, at most, a small sample, subject to licence terms.
- Be explicit about limitations in the README: single corridor, data gaps, cancellation handling, freight sample size.

## Decisions taken after the brief (2026-11-26)
- **Collector hosts:** Oracle VPS (primary) runs RDM Kafka feeds (TRUST + Darwin Push Port); Raspberry Pi (backup) runs Network Rail STOMP (TRUST). Captures are merged and de-duplicated.
- **GPU:** local RX 9070 XT is optional acceleration; all code must run on CPU.
- **Corridor scope:** Heathrow branch is an entry edge at Airport Junction. Elizabeth line services are modelled up to where they leave the GWML for the central tunnel (Portobello Junction / Westbourne Park area), with Paddington low level as their exit node. Which of those locations actually have TRUST reports is to be checked empirically.
- **Heathrow Express** has no intermediate calling points in the corridor, so in Phase 1 it only enters as Paddington occupancy / headway context.
